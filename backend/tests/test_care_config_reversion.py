"""D01: config identity, cache restoration/requeue, and execution fencing."""

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

import care_core.core as core
from care_core import CoreAnalysisError, analyze, safety
from app.database import SessionLocal
from app.care.models import AnalysisJob, AnalysisResult, SupportPolicy
from app.care.worker import Worker


P = "/api/robot-insights"


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("ROBOT_CARE_ANALYSIS_ENGINE", "rules")
    monkeypatch.setenv("ROBOT_CARE_ASSESSMENT_PROVIDER", "disabled")
    monkeypatch.setenv("ROBOT_CARE_SIMULATOR_ENABLED", "true")
    original = copy.deepcopy(core._RULES)
    alternate = copy.deepcopy(original)
    alternate["rules_version"] = "rules-d01-alternate-B"
    alternate["positive"] = {}
    alternate["negative"]["emotion_negative_sadness"].append("开心")

    def switch(which):
        monkeypatch.setattr(core, "_RULES", copy.deepcopy(original if which == "A" else alternate))
    switch("A")
    return switch


def source(api):
    sid = api.create("fictional_D01_config_cycle").json()["recording_session_id"]
    response = api.send(sid, content="我今天很开心。")
    assert response.status_code == 201
    return sid, response.json()["record_id"]


def job(api, jid):
    response = api.request("GET", f"{P}/analysis-jobs/{jid}")
    assert response.status_code == 200
    return response.json()


def all_jobs(api, sid):
    return api.request("GET", f"{P}/sessions/{sid}/analyses").json()["items"]


def execute_stage(worker, stage):
    claim = None
    if stage == "completed":
        assert worker.step()
    elif stage in ("running", "failed"):
        claim = worker.claim()
        assert claim
        if stage == "failed":
            assert worker.finish(claim, error=CoreAnalysisError("fictional_model_failure", safety_result=safety(claim["text"])))
    return claim


@pytest.mark.parametrize("a_stage", ["completed", "queued", "running", "failed"])
@pytest.mark.parametrize("b_stage", ["completed", "queued", "running"])
@pytest.mark.parametrize("restore_by", ["scan", "manual"])
def test_D01_A_B_A_restores_one_current_result(a_stage, b_stage, restore_by, actors, configured, trace):
    a, _ = actors
    sid, rid = source(a)
    worker = Worker()
    config_a = worker.config["config_version"]
    assert worker.scan() == 1
    a_id = all_jobs(a, sid)[0]["job_id"]
    old_a_claim = execute_stage(worker, a_stage)
    cached_policy = None
    cached_expiry = None
    if a_stage == "completed":
        cached_policy = job(a, a_id)["support_policy_id"]
        cached_expiry = a.request("GET", f"{P}/policies/{cached_policy}").json()["expires_at"]
    configured("B")
    assert job(a, a_id)["is_current"] is False  # Configuration check applies even before scan.
    assert worker.scan() == 1  # An existing worker also refreshes server configuration.
    config_b = worker.config["config_version"]
    assert config_b != config_a
    b_id = next(row["job_id"] for row in all_jobs(a, sid) if row["config_version"] == config_b)
    old_b_claim = execute_stage(worker, b_stage)
    if b_stage == "completed":
        assert job(a, b_id)["emotion_label"] == "negative"  # Different actual rule behavior.
    configured("A")
    assert job(a, b_id)["is_current"] is False
    # Summary/report must never show B as current while waiting for automatic discovery.
    before = a.request("GET", f"{P}/sessions/{sid}/summary").json()
    assert before["emotion_counts"] == {"positive": 0, "neutral": 0, "negative": 0}
    restarted = Worker()
    assert restarted.config["config_version"] == config_a
    if restore_by == "scan":
        assert restarted.scan() == (0 if a_stage == "completed" else 1)
    else:
        restored = a.request("POST", P + "/analysis-jobs", json={"record_id": rid})
        assert restored.status_code == (200 if a_stage == "completed" else 202)
        assert restored.json()["job_id"] == a_id
    repeated = a.request("POST", P + "/analysis-jobs", json={"record_id": rid})
    assert repeated.status_code == 200 and repeated.json()["job_id"] == a_id
    if a_stage == "completed":
        assert restarted.step() is False
        assert job(a, a_id)["support_policy_id"] == cached_policy
        assert a.request("GET", f"{P}/policies/{cached_policy}").json()["expires_at"] == cached_expiry
    else:
        pending = job(a, a_id)
        assert pending["state"] == "pending" and pending["emotion_label"] is None
        with SessionLocal() as db:
            value = db.get(AnalysisJob, a_id)
            assert value.input_snapshot == "我今天很开心。" and value.attempt == 0
            assert value.execution_token is None and value.lease_until is None
        new_claim = restarted.claim()
        assert new_claim["job_id"] == a_id
        if old_a_claim:
            assert new_claim["token"] != old_a_claim["token"]
            assert restarted.finish(old_a_claim, result=analyze("我今天很难过。")) is False
        # Duplicate trigger during execution must preserve this new lease/token.
        assert a.request("POST", P + "/analysis-jobs", json={"record_id": rid}).status_code == 200
        assert restarted.finish(new_claim, result=analyze(new_claim["text"])) is True
    if old_b_claim:
        assert restarted.finish(old_b_claim, result=analyze("我今天很难过。")) is False
    assert restarted.scan() == 0 and restarted.step() is False
    rows = all_jobs(a, sid)
    current = [row for row in rows if row["is_current"]]
    assert len(rows) == 2 and len(current) == 1
    assert current[0]["job_id"] == a_id and current[0]["emotion_label"] == "positive"
    assert job(a, b_id)["state"] == "invalidated"
    summary = a.request("GET", f"{P}/sessions/{sid}/summary").json()
    report = a.request("POST", P + "/reports/preview", json={"scope": {"session_ids": [sid]}})
    assert report.status_code == 200
    assert summary["emotion_counts"] == report.json()["emotion_counts"] == {"positive": 1, "neutral": 0, "negative": 0}
    assert report.json()["source_references"][0]["config_version"] == config_a
    assert report.json()["source_references"][0]["task_id"] == a_id
    with SessionLocal() as db:
        assert db.query(AnalysisJob).count() == 2
        assert db.query(AnalysisResult).filter_by(job_id=a_id).count() == 1
        assert db.query(SupportPolicy).filter_by(job_id=a_id).count() == 1
    trace.append({"initial_A": a_stage, "B": b_stage, "restore_by": restore_by,
                  "A_config": config_a, "B_config": config_b,
                  "after_return_A": rows, "summary": summary,
                  "report_current_sources": report.json()["source_references"],
                  "restored_cache": a_stage == "completed", "stale_attempts_rejected": True})


def test_D01_deleted_source_cannot_be_reactivated(actors, configured, trace):
    a, _ = actors
    sid, rid = source(a)
    first = Worker()
    assert first.scan() == 1
    stale = first.claim()
    configured("B")
    assert Worker().scan() == 1
    assert a.request("DELETE", f"/api/robot-records/sessions/{sid}").status_code == 204
    configured("A")
    restarted = Worker()
    assert restarted.scan() == 0 and restarted.step() is False
    assert restarted.finish(stale, result=analyze("我今天很开心。")) is False
    assert a.request("POST", P + "/analysis-jobs", json={"record_id": rid}).status_code == 410
    with SessionLocal() as db:
        assert db.query(AnalysisJob).count() == db.query(AnalysisResult).count() == db.query(SupportPolicy).count() == 0
    trace.append({"deleted_source_reactivation": "rejected", "old_lease_result": "rejected"})


def test_D01_config_return_preserves_correction_revision_identity(actors, configured, trace):
    a, _ = actors
    sid, rid = source(a)
    assert Worker().scan() == 1 and Worker().step()
    first = all_jobs(a, sid)[0]
    configured("B")
    assert Worker().scan() == 1 and Worker().step()
    correction = a.request("POST", f"{P}/messages/{rid}/corrections", json={
        "request_id": "D01_input_B", "base_revision": 0, "content": "我今天很难过。"})
    assert correction.status_code == 201
    assert Worker().step()
    configured("A")
    assert Worker().scan() == 1 and Worker().step()
    back = a.request("POST", f"{P}/messages/{rid}/corrections", json={
        "request_id": "D01_input_back_A", "base_revision": 1, "content": "我今天很开心。"})
    assert back.status_code == 201 and Worker().step()
    rows = all_jobs(a, sid)
    current = [row for row in rows if row["is_current"]]
    assert len(current) == 1 and current[0]["input_revision"] == 2
    assert current[0]["job_id"] != first["job_id"]
    assert current[0]["input_snapshot_hash"] == first["input_snapshot_hash"]
    assert current[0]["emotion_label"] == "positive"
    trace.append({"input_A_B_A_remains_distinct": True, "jobs": rows})


def test_D01_real_worker_processes_restore_config_A_after_B(actors, monkeypatch, trace):
    """Three real worker PIDs share the durable DB; B uses only localhost HTTP."""
    from test_care_core import MODEL_NAME, envelope, fake_ollama

    a, _ = actors
    sid, rid = source(a)
    backend = Path(__file__).resolve().parents[1]
    processes = []

    def run_worker(phase):
        command = [sys.executable, "-m", "app.care.worker", "--once"]
        started = time.monotonic()
        process = subprocess.Popen(command, cwd=backend,
                                   env={**os.environ, "PYTHONUTF8": "1", "PYTHONPATH": str(backend)},
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            output, errors = process.communicate(timeout=20)
        except BaseException:
            process.kill()
            process.communicate(timeout=10)
            raise
        assert process.returncode == 0, errors.decode("utf-8", errors="replace")
        assert "我今天很开心" not in (output + errors).decode("utf-8", errors="replace")
        entry = {"phase": phase, "pid": process.pid, "exit_code": process.returncode,
                 "command": command, "elapsed_seconds": round(time.monotonic() - started, 6),
                 "worker_output": output.decode("utf-8", errors="replace").strip()}
        processes.append(entry)
        return entry

    run_worker("A_initial_rules")
    initial = all_jobs(a, sid)
    assert len(initial) == 1 and initial[0]["state"] == "succeeded"
    assert initial[0]["emotion_label"] == "positive" and initial[0]["is_current"]
    a_id, config_a = initial[0]["job_id"], initial[0]["config_version"]
    model_reply = json.dumps(envelope({"classification_status": "classified",
                                      "emotion_label": "negative", "reason_code": "model_classified"}))
    with fake_ollama(raw=model_reply) as (local, received):
        monkeypatch.setenv("ROBOT_CARE_ANALYSIS_ENGINE", "ollama")
        monkeypatch.setenv("ROBOT_CARE_MODEL_BASE_URL", local.model_base_url)
        monkeypatch.setenv("ROBOT_CARE_MODEL_NAME", MODEL_NAME)
        run_worker("B_localhost_ollama_adapter")
        middle = all_jobs(a, sid)
        b = next(row for row in middle if row["engine_kind"] == "ollama")
        assert b["is_current"] and b["emotion_label"] == "negative" and b["state"] == "succeeded"
        assert not job(a, a_id)["is_current"]
        assert len(received) == 1 and received[0]["path"] == "/api/chat"
        monkeypatch.setenv("ROBOT_CARE_ANALYSIS_ENGINE", "rules")
        monkeypatch.delenv("ROBOT_CARE_MODEL_BASE_URL")
        monkeypatch.delenv("ROBOT_CARE_MODEL_NAME")
        assert job(a, b["job_id"])["is_current"] is False
        run_worker("A_restart_restores_persisted_cache")
        assert len(received) == 1  # Returning to rules does not silently call the model.
    assert len({item["pid"] for item in processes}) == 3
    rows = all_jobs(a, sid)
    active = [row for row in rows if row["is_current"]]
    assert len(rows) == 2 and len(active) == 1
    assert active[0]["job_id"] == a_id and active[0]["config_version"] == config_a
    assert active[0]["state"] == "succeeded" and active[0]["emotion_label"] == "positive"
    assert job(a, b["job_id"])["state"] == "invalidated"
    summary = a.request("GET", f"{P}/sessions/{sid}/summary").json()
    report = a.request("POST", P + "/reports/preview", json={"scope": {"session_ids": [sid]}})
    assert report.status_code == 200
    assert summary["emotion_counts"] == report.json()["emotion_counts"] == {"positive": 1, "neutral": 0, "negative": 0}
    assert report.json()["source_references"][0]["task_id"] == a_id
    assert report.json()["source_references"][0]["config_version"] == config_a
    duplicate = a.request("POST", P + "/analysis-jobs", json={"record_id": rid})
    assert duplicate.status_code == 200 and duplicate.json()["job_id"] == a_id
    with SessionLocal() as db:
        assert db.query(AnalysisJob).count() == 2
        assert db.query(AnalysisResult).count() == db.query(SupportPolicy).count() == 2
    trace.append({"real_worker_processes": processes, "persistent_database": os.environ["DATABASE_URL"],
                  "local_ollama_requests": 1, "after_B": middle, "after_restart_A": rows,
                  "summary": summary, "report_current_sources": report.json()["source_references"],
                  "same_key_manual_status": duplicate.status_code})
