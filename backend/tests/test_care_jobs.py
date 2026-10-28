"""API/worker invariants against the same isolated SQLite and JWT users as 2.4."""

import pytest
from sqlalchemy import event

from app.database import SessionLocal
from app.robot_records import RecordMessage, RecordSession
from app.care.models import (AnalysisJob, AnalysisResult, Correction, InputRevision,
                             StrategyDelivery, SupportPolicy)
from app.care.worker import Worker
from care_core import CoreAnalysisError, analyze, safety


ROOT = "/api/robot-insights"


@pytest.fixture(autouse=True)
def care_environment(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("ROBOT_CARE_ANALYSIS_ENGINE", "rules")
    monkeypatch.setenv("ROBOT_CARE_ASSESSMENT_PROVIDER", "disabled")
    monkeypatch.setenv("ROBOT_CARE_SIMULATOR_ENABLED", "true")


def saved(api, external="care_session", text="我今天很开心。", **updates):
    response = api.create(external)
    assert response.status_code == 201, response.text
    sid = response.json()["recording_session_id"]
    response = api.send(sid, content=text, **updates)
    assert response.status_code == 201, response.text
    rid = api.messages(sid).json()["items"][0]["record_id"]
    return sid, rid


def start(api, rid):
    response = api.request("POST", ROOT + "/analysis-jobs", json={"record_id": rid})
    assert response.status_code == 202, response.text
    return response.json()["task_id"]


def get_job(api, jid):
    response = api.request("GET", f"{ROOT}/analysis-jobs/{jid}")
    assert response.status_code == 200, response.text
    return response.json()


def correction(api, rid, request_id, revision, content):
    return api.request("POST", f"{ROOT}/messages/{rid}/corrections", json={
        "request_id": request_id, "base_revision": revision, "content": content})


def counts(db):
    return {cls.__tablename__: db.query(cls).count() for cls in
            (RecordMessage, InputRevision, Correction, AnalysisJob, AnalysisResult, SupportPolicy, StrategyDelivery)}


def test_care_N04_N17_N23_scan_idempotence_and_input_exclusions(actors, trace):
    a, b = actors
    first = a.request("GET", ROOT + "/profile").json()["anonymous_id"]
    assert a.request("GET", ROOT + "/profile").json()["anonymous_id"] == first
    assert b.request("GET", ROOT + "/profile").json()["anonymous_id"] != first
    sid, rid = saved(a)
    assert a.send(sid, 2, role="assistant", playback_status="unknown", content="我很开心").status_code == 201
    assert a.send(sid, 3, text_status="canceled", content="").status_code == 201
    with SessionLocal() as db:
        assert db.query(AnalysisJob).count() == 0  # The 2.4 write never invokes inference or creates a task.
    worker = Worker()
    assert worker.scan() == 1
    assert worker.scan() == 0
    duplicate = a.request("POST", ROOT + "/analysis-jobs", json={"record_id": rid})
    assert duplicate.status_code == 200
    assert worker.step() is True
    assert worker.step() is False
    result = get_job(a, duplicate.json()["task_id"])
    assert (result["state"], result["emotion_label"], result["attempt"]) == ("succeeded", "positive", 1)
    assert result["support_policy_id"] and result["result_id"]
    entries = a.request("GET", f"{ROOT}/sessions/{sid}/analyses").json()
    assert len(entries["items"]) == 1
    assert {row["reason_code"] for row in entries["excluded_records"]} == {"assistant_not_analysis_input", "canceled_not_analysis_input"}
    summary = a.request("GET", f"{ROOT}/sessions/{sid}/summary").json()
    assert summary["emotion_counts"] == {"positive": 1, "neutral": 0, "negative": 0}
    assert summary["analysis_counts"]["excluded"] == 2
    for row in a.messages(sid).json()["items"][1:]:
        assert a.request("POST", ROOT + "/analysis-jobs", json={"record_id": row["record_id"]}).status_code == 422
    with SessionLocal() as db:
        assert db.query(AnalysisJob).count() == db.query(AnalysisResult).count() == db.query(SupportPolicy).count() == 1
    trace.append({"anonymous_stable": True, "scan_created": 1, "duplicate_new_jobs": 0,
                  "final_task": result, "exclusions": entries["excluded_records"]})


def test_care_N23_lease_reclaim_fences_old_attempt(actors, trace):
    a, _ = actors
    _, rid = saved(a)
    jid = start(a, rid)
    clock = ["2026-10-28T10:00:00.000000Z"]
    worker = Worker(clock=lambda: clock[0])
    old = worker.claim()
    assert old["job_id"] == jid
    clock[0] = "2026-10-28T10:01:00.000000Z"
    new = worker.claim()
    assert new["job_id"] == jid and new["token"] != old["token"]
    assert worker.finish(old, result=analyze("我很难过。")) is False
    assert worker.finish(new, result=analyze(new["text"])) is True
    assert worker.finish(new, result=analyze("我很难过。")) is False
    actual = get_job(a, jid)
    assert (actual["attempt"], actual["state"], actual["emotion_label"]) == (2, "succeeded", "positive")
    with SessionLocal() as db:
        assert db.query(AnalysisResult).count() == db.query(SupportPolicy).count() == 1
        assert db.get(AnalysisJob, jid).input_snapshot is None
    trace.append({"old_attempt_rejected": True, "new_attempt_committed": True, "task": actual})


def test_care_N23_result_and_policy_are_one_transaction(actors, trace):
    a, _ = actors
    _, rid = saved(a)
    jid = start(a, rid)
    worker = Worker()
    claim = worker.claim()

    def fail_policy_flush(db, flush_context, instances):
        if any(isinstance(row, SupportPolicy) for row in db.new):
            raise RuntimeError("fictional_policy_storage_fault")

    event.listen(SessionLocal, "before_flush", fail_policy_flush)
    try:
        with pytest.raises(RuntimeError, match="fictional_policy_storage_fault"):
            worker.finish(claim, result=analyze(claim["text"]))
    finally:
        event.remove(SessionLocal, "before_flush", fail_policy_flush)
    with SessionLocal() as db:
        assert db.query(AnalysisResult).count() == db.query(SupportPolicy).count() == 0
        assert db.get(AnalysisJob, jid).state == "running"
    assert worker.finish(claim, result=analyze(claim["text"])) is True
    assert get_job(a, jid)["state"] == "succeeded"
    trace.append({"forced_policy_storage_failure": "rolled_back_result_and_state", "same_attempt_retry": "committed"})


def test_care_N25_N26_A_B_A_revision_identity_and_old_attempt_fencing(actors, trace):
    a, _ = actors
    original = "我今天很开心。"
    sid, rid = saved(a, text=original)
    job0 = start(a, rid)
    worker = Worker()
    claim0 = worker.claim()
    b = correction(a, rid, "edit_to_B", 0, "我今天很难过。")
    assert b.status_code == 201
    job1 = b.json()["task_id"]
    claim1 = worker.claim()
    again_a = correction(a, rid, "edit_back_to_A", 1, original)
    assert again_a.status_code == 201
    job2 = again_a.json()["task_id"]
    claim2 = worker.claim()
    assert len({job0, job1, job2}) == 3
    assert worker.finish(claim0, result=analyze(claim0["text"])) is False
    assert worker.finish(claim1, result=analyze(claim1["text"])) is False
    assert worker.finish(claim2, result=analyze(claim2["text"])) is True
    values = [get_job(a, jid) for jid in (job0, job1, job2)]
    assert [v["input_revision"] for v in values] == [0, 1, 2]
    assert [v["state"] for v in values] == ["invalidated", "invalidated", "succeeded"]
    assert values[0]["input_snapshot_hash"] == values[2]["input_snapshot_hash"]
    assert values[2]["is_current"] is True and values[2]["emotion_label"] == "positive"
    assert all(not v["is_current"] for v in values[:2])
    actual = a.request("GET", f"{ROOT}/messages/{rid}/effective").json()
    assert actual["original_content"] == actual["effective_content"] == original
    assert actual["input_revision"] == 2
    replay = correction(a, rid, "edit_to_B", 0, "我今天很难过。")
    assert replay.status_code == 200 and replay.json()["input_revision"] == 1
    assert correction(a, rid, "edit_to_B", 0, "不同内容").status_code == 409
    assert correction(a, rid, "stale_base", 0, "另一段内容").status_code == 409
    assert a.send(sid, content=original).status_code == 200  # Immutable 2.4 source still deduplicates.
    with SessionLocal() as db:
        assert db.query(AnalysisJob).count() == 3
        assert db.query(AnalysisResult).count() == db.query(SupportPolicy).count() == 1
    summary = a.request("GET", f"{ROOT}/sessions/{sid}/summary").json()
    assert summary["emotion_counts"]["positive"] == 1
    assert summary["emotion_counts"]["negative"] == 0
    trace.append({"revision_tasks": values, "effective_input": actual, "old_attempts_rejected": 2})


def test_care_N26_prior_result_policy_expire_after_correction(actors, trace):
    a, _ = actors
    _, rid = saved(a)
    old_job = start(a, rid)
    worker = Worker()
    assert worker.step()
    old = get_job(a, old_job)
    old_policy = old["support_policy_id"]
    edit = correction(a, rid, "replace_positive_with_negative", 0, "我很难过。")
    assert edit.status_code == 201
    assert get_job(a, old_job)["classification_status"] == "invalidated"
    assert a.request("GET", f"{ROOT}/policies/{old_policy}").json()["is_current"] is False
    assert worker.step()
    current = get_job(a, edit.json()["task_id"])
    assert current["emotion_label"] == "negative" and current["is_current"] is True
    assert current["support_policy_id"] != old_policy
    rejected = a.request("POST", ROOT + "/strategy-deliveries/simulate", json={"policy_id": old_policy, "request_id": "old_policy_rejected"})
    assert rejected.status_code == 201
    assert rejected.json()["delivery_status"] == "simulated_rejected"
    trace.append({"prior_policy_is_current": False, "prior_delivery": rejected.json(), "new_task": current})


def test_care_N27_delete_cleanup_is_same_transaction_and_no_new_report(actors, monkeypatch, trace):
    from app.care import service

    a, _ = actors
    sid, rid = saved(a)
    jid = start(a, rid)
    assert Worker().step()
    policy = get_job(a, jid)["support_policy_id"]
    assert a.request("POST", ROOT + "/strategy-deliveries/simulate", json={"policy_id": policy, "request_id": "before_delete"}).status_code == 201
    assert correction(a, rid, "sensitive_revision", 0, "虚构更正后很难过。").status_code == 201
    with SessionLocal() as db:
        before = counts(db)
    real_clear = service.clear_session

    def failing_clear(db, session_id):
        real_clear(db, session_id)
        raise RuntimeError("fictional_delete_transaction_fault")

    with monkeypatch.context() as temporary:
        temporary.setattr(service, "clear_session", failing_clear)
        with pytest.raises(RuntimeError, match="fictional_delete_transaction_fault"):
            a.request("DELETE", f"/api/robot-records/sessions/{sid}")
    with SessionLocal() as db:
        assert counts(db) == before
        assert db.get(RecordSession, sid).state != "deleted"
    assert a.request("DELETE", f"/api/robot-records/sessions/{sid}").status_code == 204
    with SessionLocal() as db:
        after = counts(db)
        assert all(number == 0 for number in after.values())
        assert db.get(RecordSession, sid).state == "deleted"
    assert a.request("GET", f"{ROOT}/messages/{rid}/effective").status_code == 410
    assert a.request("GET", f"{ROOT}/analysis-jobs/{jid}").status_code == 410
    assert a.request("POST", ROOT + "/reports/preview", json={"scope": {"session_ids": [sid]}}).status_code == 410
    trace.append({"cleanup_failure": "whole_transaction_rolled_back", "before": before, "after": after})


def test_care_N27_delete_during_inference_cannot_resurrect(actors, trace):
    a, _ = actors
    sid, rid = saved(a)
    jid = start(a, rid)

    def delayed_analyzer(text, *args, **kwargs):
        assert a.request("DELETE", f"/api/robot-records/sessions/{sid}").status_code == 204
        return analyze(text)

    assert Worker(analyzer=delayed_analyzer).step() is True
    with SessionLocal() as db:
        assert all(value == 0 for value in counts(db).values())
    assert a.request("GET", f"{ROOT}/analysis-jobs/{jid}").status_code == 410
    trace.append({"source_deleted_inside_inference": True, "late_worker_result": "not_committed"})


def test_care_N20_N28_three_scenarios_simulated_receiver_and_rejections(actors, trace):
    a, b = actors
    sid, _ = saved(a, text="我感到孤独。")
    assert a.send(sid, 2, content="我很担心明天，压力很大。").status_code == 201
    assert a.send(sid, 3, content="我今天很开心。").status_code == 201
    worker = Worker()
    assert worker.scan() == 3
    while worker.step():
        pass
    jobs = a.request("GET", f"{ROOT}/sessions/{sid}/analyses").json()["items"]
    templates, deliveries = [], []
    for index, job in enumerate(jobs):
        pid = job["support_policy_id"]
        templates.append(a.request("GET", f"{ROOT}/policies/{pid}").json()["template_id"])
        payload = {"policy_id": pid, "request_id": f"scenario_{index}"}
        received = a.request("POST", ROOT + "/strategy-deliveries/simulate", json=payload)
        assert received.status_code == 201
        actual = received.json()
        assert (actual["consumer_kind"], actual["delivery_status"], actual["real_delivery_status"]) == ("local_simulator", "simulated_received", "not_connected")
        assert a.request("POST", ROOT + "/strategy-deliveries/simulate", json=payload).status_code == 200
        assert b.request("GET", f"{ROOT}/policies/{pid}").status_code == 404
        assert b.request("POST", ROOT + "/strategy-deliveries/simulate", json=payload).status_code == 404
        assert b.request("GET", f"{ROOT}/strategy-deliveries/{actual['delivery_id']}").status_code == 404
        deliveries.append(actual)
    assert templates == ["loneliness_listening", "worry_optional_relaxation", "positive_encouragement"]
    assert a.request("POST", ROOT + "/strategy-deliveries/simulate", json={"policy_id": jobs[1]["support_policy_id"], "request_id": "scenario_0"}).status_code == 409
    assert a.request("POST", ROOT + "/strategy-deliveries/simulate", json={"policy_id": jobs[0]["support_policy_id"], "request_id": "forged", "consumer_kind": "real", "delivery_status": "applied"}).status_code == 422
    pid = jobs[0]["support_policy_id"]
    with SessionLocal() as db:
        db.get(SupportPolicy, pid).expires_at = "2020-01-01T00:00:00.000000Z"
        db.commit()
    expired = a.request("POST", ROOT + "/strategy-deliveries/simulate", json={"policy_id": pid, "request_id": "expired"})
    assert expired.status_code == 201 and expired.json()["delivery_status"] == "simulated_rejected"
    assert a.request("POST", ROOT + "/strategy-deliveries/simulate", json={"policy_id": 9223372036854775807, "request_id": "unknown"}).status_code == 404
    trace.append({"scenario_templates": templates, "actual_local_receipts": deliveries, "expired": expired.json()})


def test_care_N21_failure_keeps_safety_policy_and_never_invents_label(actors, trace):
    a, _ = actors
    _, rid = saved(a, text="我不想活了。")
    jid = start(a, rid)

    def failing_model(text, *args, **kwargs):
        raise CoreAnalysisError("model_timeout", retryable=False, safety_result=safety(text))

    assert Worker(analyzer=failing_model).step()
    job = get_job(a, jid)
    assert job["state"] == job["classification_status"] == "failed"
    assert job["emotion_label"] is None
    assert job["safety_signal"] == "explicit_danger_expression"
    assert job["error_code"] == "model_timeout"
    policy = a.request("GET", f"{ROOT}/policies/{job['support_policy_id']}")
    assert policy.status_code == 200
    assert policy.json()["policy_kind"] == "safety_prompt"
    assert policy.json()["template_id"] == "safety_human_help"
    receipt = a.request("POST", ROOT + "/strategy-deliveries/simulate", json={"policy_id": job["support_policy_id"], "request_id": "safety_after_model_failure"})
    assert receipt.status_code == 201 and receipt.json()["delivery_status"] == "simulated_received"
    trace.append({"failed_task": job, "independent_safety_policy": policy.json(), "simulated_receipt": receipt.json()})


def test_care_N05_N06_owner_and_strict_request_boundaries(actors, trace):
    a, b = actors
    sid, rid = saved(a)
    jid = start(a, rid)
    for path in (f"/messages/{rid}/effective", f"/analysis-jobs/{jid}", f"/sessions/{sid}/analyses", f"/sessions/{sid}/summary"):
        assert b.request("GET", ROOT + path).status_code == 404
    assert correction(b, rid, "foreign_edit", 0, "虚构文字").status_code == 404
    assert b.request("POST", ROOT + "/analysis-jobs", json={"record_id": rid}).status_code == 404
    assert b.request("POST", ROOT + "/reports/preview", json={"scope": {"session_ids": [sid]}}).status_code == 404
    for invalid in (True, 1.0, 0, -1, 9223372036854775808, "1"):
        assert a.request("POST", ROOT + "/analysis-jobs", json={"record_id": invalid}).status_code == 422
    marker = "短标记_虚构敏感内容"
    bad = a.request("POST", ROOT + "/analysis-jobs", json={"record_id": rid, "user_id": b.uid, "engine_kind": marker})
    assert bad.status_code == 422 and marker not in bad.text
    assert a.request("GET", f"{ROOT}/analysis-jobs/{jid}", params={"user_id": b.uid}).status_code == 422
    assert a.request("GET", ROOT + "/profile").headers["Cache-Control"] == "no-store"
    assert correction(a, rid, "cursor_revision", 0, "我很难过。").status_code == 201
    page = a.request("GET", f"{ROOT}/sessions/{sid}/analyses", params={"limit": 1}).json()
    assert page["next_cursor"]
    other_sid, _ = saved(b, external="different_owner_session")
    assert b.request("GET", f"{ROOT}/sessions/{other_sid}/analyses", params={"cursor": page["next_cursor"]}).status_code == 422
    trace.append({"foreign_resource_policy": 404, "strict_id_cases": 6, "sensitive_input_not_echoed": True})


def test_care_N23_retry_schedule_limit_and_single_final_result(actors, monkeypatch, trace):
    a, _ = actors
    _, rid = saved(a)
    jid = start(a, rid)
    monkeypatch.setenv("ROBOT_CARE_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("ROBOT_CARE_RETRY_SECONDS", "1")
    clock = ["2026-10-28T10:00:00.000000Z"]
    worker = Worker(clock=lambda: clock[0])
    first = worker.claim()
    assert worker.finish(first, error=CoreAnalysisError("model_timeout", retryable=True, safety_result=safety(first["text"])))
    retry = get_job(a, jid)
    assert retry["state"] == "retry_wait" and retry["attempt"] == 1
    assert worker.claim() is None  # No busy retry before the persisted next_retry_at.
    clock[0] = "2026-10-28T10:00:02.000000Z"
    second = worker.claim()
    assert second["job_id"] == jid
    assert worker.finish(second, error=CoreAnalysisError("model_timeout", retryable=True, safety_result=safety(second["text"])))
    final = get_job(a, jid)
    assert final["state"] == "failed" and final["attempt"] == 2
    clock[0] = "2026-10-28T12:00:00.000000Z"
    assert worker.claim() is None
    with SessionLocal() as db:
        assert db.query(AnalysisResult).filter_by(job_id=jid).count() == 1
        assert db.get(AnalysisJob, jid).input_snapshot is None
    trace.append({"first_retry": retry, "terminal_failure": final, "bounded_attempts": 2})
