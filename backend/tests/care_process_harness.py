"""Fault-only real process harness; never imported by application startup."""

import hashlib
import json
import os
from pathlib import Path
import threading
import time

from app.main import app  # Register the same schema/startup guards as the real worker.
from app.database import SessionLocal
from app.care.models import AnalysisJob, AnalysisResult, SupportPolicy
from app.care.worker import Worker
from care_core import analyze


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def public_claim(claim, started, worker):
    with SessionLocal() as db:
        job = db.get(AnalysisJob, claim["job_id"])
        return {"pid": os.getpid(), "job_id": job.id, "state": job.state, "attempt": job.attempt,
                "lease_until": job.lease_until, "controlled_clock": worker.clock(),
                "token_sha256": hashlib.sha256(claim["token"].encode("ascii")).hexdigest(),
                "elapsed_seconds": round(time.monotonic() - started, 6)}


def main():
    started = time.monotonic()
    mode = os.environ["CARE_PROCESS_MODE"]
    ready = Path(os.environ["CARE_PROCESS_READY"])
    state_path = Path(os.environ["CARE_PROCESS_CLAIM_STATE"])
    worker = Worker(clock=lambda: os.environ["CARE_PROCESS_CLOCK"])
    if mode in {"claim_pause", "reclaim_pause"}:
        created = worker.scan()
        claim = worker.claim()
        assert claim is not None
        public = {**public_claim(claim, started, worker), "scan_created": created, "phase": mode}
        if mode == "claim_pause":
            atomic_json(state_path, {"job_id": claim["job_id"], "token": claim["token"]})
        atomic_json(ready, public)
        if mode == "claim_pause":
            threading.Event().wait()  # Parent must terminate this real process.
        else:
            resume = Path(os.environ["CARE_PROCESS_RESUME"])
            deadline = time.monotonic() + 20
            while not resume.exists():
                if time.monotonic() >= deadline:
                    raise RuntimeError("care_process_resume_timeout")
                threading.Event().wait(0.025)
            assert worker.finish(claim, result=analyze(claim["text"]))
            further = 0
            while worker.step():
                further += 1
            with SessionLocal() as db:
                final = {"pid": os.getpid(), "phase": "recovery_complete", "further_processed": further,
                         "jobs": [{"job_id": row.id, "state": row.state, "attempt": row.attempt,
                                   "has_snapshot": row.input_snapshot is not None}
                                  for row in db.query(AnalysisJob).order_by(AnalysisJob.id)],
                         "result_count": db.query(AnalysisResult).count(),
                         "policy_count": db.query(SupportPolicy).count(),
                         "elapsed_seconds": round(time.monotonic() - started, 6)}
            atomic_json(os.environ["CARE_PROCESS_DONE"], final)
    elif mode == "stale_finish":
        old = json.loads(state_path.read_text(encoding="utf-8"))
        old["text"] = "虚构旧尝试输入"  # The stale token is rejected before any result is written.
        accepted = worker.finish(old, result=analyze("我很难过。"))
        atomic_json(ready, {"pid": os.getpid(), "phase": mode, "accepted": accepted,
                            "elapsed_seconds": round(time.monotonic() - started, 6)})
    else:
        raise RuntimeError("unknown_care_process_mode")


if __name__ == "__main__":
    main()
