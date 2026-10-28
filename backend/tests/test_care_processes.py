"""N24 actual process death/restart, durable pending scan, and stale token fencing."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from app.database import SessionLocal
from app.care.models import AnalysisJob, AnalysisResult, SupportPolicy


BACKEND = Path(__file__).resolve().parents[1]
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


@pytest.fixture(autouse=True)
def analysis_process_environment(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("ROBOT_CARE_ANALYSIS_ENGINE", "rules")
    monkeypatch.setenv("ROBOT_CARE_ASSESSMENT_PROVIDER", "disabled")
    monkeypatch.setenv("ROBOT_CARE_SIMULATOR_ENABLED", "false")
    monkeypatch.setenv("ROBOT_CARE_LEASE_SECONDS", "1")


def wait_json(proc, path):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        if proc.poll() is not None:
            output, errors = proc.communicate()
            raise AssertionError("Analysis subprocess failed: " + errors.decode("utf-8", errors="replace"))
        time.sleep(0.025)
    proc.kill()
    proc.communicate(timeout=10)
    raise AssertionError("Analysis subprocess barrier timeout")


def child(mode, clock, tmp_path):
    ready = tmp_path / (mode + ".ready.json")
    environment = {**os.environ, "PYTHONUTF8": "1", "PYTHONPATH": str(BACKEND),
                   "CARE_PROCESS_MODE": mode, "CARE_PROCESS_READY": str(ready),
                   "CARE_PROCESS_CLOCK": clock,
                   "CARE_PROCESS_CLAIM_STATE": str(tmp_path / "claim_private_runtime.json"),
                   "CARE_PROCESS_RESUME": str(tmp_path / "resume"),
                   "CARE_PROCESS_DONE": str(tmp_path / "complete.json")}
    command = [sys.executable, str(BACKEND / "tests" / "care_process_harness.py")]
    proc = subprocess.Popen(command, cwd=BACKEND, env=environment, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, creationflags=NO_WINDOW)
    return proc, ready, command


def clean(proc):
    if proc.poll() is None:
        proc.kill()
    return proc.communicate(timeout=10)


def test_care_N24_real_worker_kill_restart_scan_and_stale_attempt(actors, tmp_path, trace):
    a, _ = actors
    sid = a.create("fictional_analysis_process").json()["recording_session_id"]
    texts = ["虚构进程短标记甲：我今天很开心。", "虚构进程短标记乙：我有些孤独。"]
    for sequence, text in enumerate(texts, 1):
        assert a.send(sid, sequence, content=text).status_code == 201
    with SessionLocal() as db:
        assert db.query(AnalysisJob).count() == 0  # No trigger was called; durable scan must discover both.
    first, ready, command = child("claim_pause", "2026-10-28T10:00:00.000000Z", tmp_path)
    second = stale = None
    first_public = second_public = None
    try:
        first_public = wait_json(first, ready)
        assert first_public["scan_created"] == 2 and first_public["attempt"] == 1
        with SessionLocal() as db:
            assert [row.state for row in db.query(AnalysisJob).order_by(AnalysisJob.id)] == ["running", "pending"]
            assert db.query(AnalysisResult).count() == db.query(SupportPolicy).count() == 0
        killed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        first.kill()
        first_output, first_errors = first.communicate(timeout=10)
        assert first.returncode != 0
        trace.append({"phase": "first_worker_terminated", "command": command, "pid": first.pid,
                      "ready": first_public, "killed_at": killed_at, "exit_code": first.returncode,
                      "persistent_database": os.environ["DATABASE_URL"]})
        second, ready2, command2 = child("reclaim_pause", "2026-10-28T10:00:02.000000Z", tmp_path)
        second_public = wait_json(second, ready2)
        assert second.pid != first.pid
        assert second_public["scan_created"] == 0 and second_public["attempt"] == 2
        assert second_public["job_id"] == first_public["job_id"]
        assert second_public["token_sha256"] != first_public["token_sha256"]
        stale, stale_ready, _ = child("stale_finish", "2026-10-28T10:00:02.000000Z", tmp_path)
        stale_public = wait_json(stale, stale_ready)
        stale_output, stale_errors = stale.communicate(timeout=10)
        assert stale.returncode == 0 and stale_public["accepted"] is False
        with SessionLocal() as db:
            job = db.get(AnalysisJob, second_public["job_id"])
            assert job.state == "running" and job.attempt == 2
            assert db.query(AnalysisResult).count() == db.query(SupportPolicy).count() == 0
        (tmp_path / "resume").write_text("resume", encoding="ascii")
        second_output, second_errors = second.communicate(timeout=15)
        assert second.returncode == 0, second_errors.decode("utf-8", errors="replace")
        complete = json.loads((tmp_path / "complete.json").read_text(encoding="utf-8"))
        assert complete["further_processed"] == 1
        assert complete["result_count"] == complete["policy_count"] == 2
        assert [job["state"] for job in complete["jobs"]] == ["succeeded", "succeeded"]
        assert [job["attempt"] for job in complete["jobs"]] == [2, 1]
        assert not any(job["has_snapshot"] for job in complete["jobs"])
        # A separately opened API transaction queries the same persistent source/result IDs.
        response = a.request("GET", f"/api/robot-insights/sessions/{sid}/analyses")
        assert response.status_code == 200
        items = response.json()["items"]
        assert len(items) == 2 and len({row["result_id"] for row in items}) == 2
        assert [row["emotion_label"] for row in items] == ["positive", "negative"]
        output = b"".join((first_output, first_errors, stale_output, stale_errors, second_output, second_errors))
        assert all(text.encode("utf-8") not in output for text in texts)
        trace.append({"phase": "analysis_process_recovered", "command": command2, "pid": second.pid,
                      "reclaimed": second_public, "stale_process": stale_public,
                      "completion": complete, "api_results": items,
                      "child_default_logs_contain_input": False,
                      "controlled_clock_used_for_lease_expiry": True})
    finally:
        clean(first)
        if second:
            clean(second)
        if stale:
            clean(stale)
