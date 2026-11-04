"""Pure mock probe: an unrelated Linux command must never receive a stop signal.

No actual process is created, queried, or signaled. This exercises the Linux
branch on the current host; it is not a Linux device/runtime verification.
The exit code is 1 when the implementation would signal the unrelated PID.
"""
import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import signal
import sys
import tempfile
import types


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True,
                        help="Absolute path to the frozen backend/tools/demo_care.py")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    spec = importlib.util.spec_from_file_location("demo_lifecycle_probe_target", source)
    target = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(target)
    unrelated_pid = 123456
    expected_argv = ["/usr/bin/python3", "-m", "uvicorn", "app.main:app",
                     "--host", "127.0.0.1", "--port", "41234"]
    actual_argv = ["/usr/bin/python3", "-m", "http.server", "9000"]
    signal_calls = []
    proc_reads = []
    original_path_class = Path

    # Substitute the module-local os object. Never modify global os.name or kill.
    target.os = types.SimpleNamespace(
        name="posix", kill=lambda pid, sig: signal_calls.append({"pid": pid, "signal": sig}))

    class MockProcPath:
        def __init__(self, path):
            self.path = str(path)

        def read_bytes(self):
            proc_reads.append(self.path)
            assert self.path == f"/proc/{unrelated_pid}/cmdline"
            return b"\0".join(part.encode("utf-8") for part in actual_argv) + b"\0"

    target.Path = MockProcPath
    stdout = io.StringIO()
    with tempfile.TemporaryDirectory(prefix="module236-lifecycle-mock-") as temp:
        root = original_path_class(temp)
        (root / "pids.json").write_text(json.dumps([
            {"label": "backend", "pid": unrelated_pid, "command": expected_argv}
        ]), encoding="utf-8")
        with contextlib.redirect_stdout(stdout):
            target.stop(root, {})
        removed_process_record = not (root / "pids.json").exists()

    violation = any(call["pid"] == unrelated_pid for call in signal_calls)
    result = {
        "probe": "linux_stop_rejects_reused_pid_with_unrelated_command",
        "source": str(source),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "python_executable": sys.executable,
        "pure_mock": True,
        "actual_kill_or_process_query_performed": False,
        "linux_runtime_test_performed": False,
        "scenario": "A persisted demo PID has since been reused by python -m http.server",
        "recorded_argv": expected_argv,
        "mock_current_argv": actual_argv,
        "mock_proc_reads": proc_reads,
        "mock_signal_calls": signal_calls,
        "expected_signal_calls": [],
        "process_record_removed": removed_process_record,
        "captured_stop_output": stdout.getvalue().strip(),
        "contract_failure": violation,
        "observed": "unrelated_pid_would_receive_sigterm" if violation else "unrelated_pid_not_signaled",
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 1 if violation else 0


if __name__ == "__main__":
    raise SystemExit(main())
