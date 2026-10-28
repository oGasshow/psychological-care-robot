"""Independent, predeclared semantic expectations and real localhost HTTP faults.

These tests run with unittest without importing the application's DB/conftest.
All text is fictional. No real Ollama service or model weights are required.
"""

from contextlib import contextmanager
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

from care_core import (CoreAnalysisError, CoreSettings, analyze, configuration,
                       input_eligibility, local_preview, safety)


MODEL_NAME = "fictional-contract-model:fixed-v1"
SHORT_SECRET = "短密甲"
LONG_SECRET = "FICTIONAL_LONG_PSYCHOLOGICAL_TEXT_MUST_NOT_APPEAR_" * 5


def envelope(content=None, **updates):
    content = content or {"classification_status": "classified", "emotion_label": "positive", "reason_code": "model_classified"}
    return {"model": MODEL_NAME, "done": True,
            "message": {"role": "assistant", "content": json.dumps(content, ensure_ascii=False)}, **updates}


@contextmanager
def fake_ollama(*, raw=None, status=200, delay=0, location=None):
    received = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            received.append({"path": self.path, "body": json.loads(body), "headers": dict(self.headers)})
            if delay:
                time.sleep(delay)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            if location:
                self.send_header("Location", location)
            self.end_headers()
            payload = raw if raw is not None else json.dumps(envelope(), ensure_ascii=False).encode("utf-8")
            if isinstance(payload, str):
                payload = payload.encode("utf-8")
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    settings = CoreSettings(model_base_url=f"http://127.0.0.1:{server.server_port}", model_name=MODEL_NAME,
                            timeout_seconds=1)
    try:
        yield settings, received
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


class CoreRuleTests(unittest.TestCase):
    def test_predeclared_positive_neutral_negative_and_unknown(self):
        # Expectations are written independently of matching rule IDs/fixture positions.
        examples = [
            ("今天见到老朋友，我很开心。", "classified", "positive"),
            ("我今天去公园散步了。", "classified", "neutral"),
            ("最近我感到孤独，没人陪我聊天。", "classified", "negative"),
            ("我担心明天的事情，压力很大。", "classified", "negative"),
            ("我今天很难过。", "classified", "negative"),
            ("嗯，那个事情就这样吧。", "unable_to_determine", None),
            ("我很开心，也有些难过。", "unable_to_determine", None),
        ]
        for text, status, label in examples:
            with self.subTest(expected=label, status=status):
                actual = analyze(text)
                self.assertEqual((actual["classification_status"], actual["emotion_label"]), (status, label))
                self.assertEqual(actual["emotion_tags"], [])

    def test_negation_does_not_invent_a_positive_or_neutral_emotion(self):
        self.assertEqual(analyze("我今天不开心。")["emotion_label"], "negative")
        for text in ("我并不难过。", "我一点也不担心。", "我并没有感到孤独。"): 
            with self.subTest(text=text):
                actual = analyze(text)
                self.assertEqual(actual["classification_status"], "unable_to_determine")
                self.assertIsNone(actual["emotion_label"])
        self.assertEqual(analyze("我不难过，今天很开心。")["emotion_label"], "positive")
        self.assertEqual(analyze("我不是不开心。")["reason_code"], "complex_negation")

    def test_quotation_report_and_desire_are_not_current_self_expression(self):
        for text in ('书里写着“我很难过”。', '“我很开心”', "朋友说他很难过。", "我听说他很难过。", "她今天很开心。", "我希望开心。"): 
            with self.subTest(text=text):
                self.assertIsNone(analyze(text)["emotion_label"])
        self.assertEqual(analyze('朋友说“我很难过”，我今天很开心。')["emotion_label"], "positive")

    def test_three_support_scenarios_are_input_driven(self):
        examples = [
            ("我有些孤独。", "loneliness_listening", "listening"),
            ("我很担心明天，压力很大。", "worry_optional_relaxation", "optional_relaxation"),
            ("我今天很开心。", "positive_encouragement", "encouragement"),
        ]
        for text, template_id, kind in examples:
            with self.subTest(kind=kind):
                actual = analyze(text)["support"]
                self.assertEqual((actual["template_id"], actual["policy_kind"]), (template_id, kind))
                self.assertEqual(actual["review_state"], "draft_pending_professional_review")
                self.assertEqual(actual["template_version"], "support-v1")
        self.assertEqual(analyze("我开心又难过。")["support"]["template_id"], "unknown_listening")

    def test_safety_signal_is_separate_from_negative_emotion(self):
        ordinary = analyze("我最近很难过，有点孤独。")
        self.assertEqual((ordinary["emotion_label"], ordinary["safety_signal"]), ("negative", "none_detected"))
        for text in ("我不想活了。", "我想伤害自己。", "我想结束自己的生命。", "我要伤害别人。"): 
            with self.subTest(text=text):
                signal = safety(text)
                self.assertEqual(signal["safety_signal"], "explicit_danger_expression")
                self.assertEqual(signal["support"]["policy_kind"], "safety_prompt")
                self.assertIn("可信任的人", signal["support"]["text"])
        self.assertEqual(safety('朋友说“我不想活了”。')["safety_signal"], "undetermined")
        self.assertEqual(safety("我不会伤害自己。")["safety_signal"], "undetermined")
        self.assertEqual(analyze("我不想活了。")["support"]["template_id"], "safety_human_help")

    def test_input_eligibility_excludes_assistant_canceled_and_blank(self):
        for role, status, text, expected in [
            ("assistant", "completed", "开心", "excluded_non_user"),
            ("user", "canceled", "开心", "excluded_non_completed"),
            ("user", "completed", " \n", "excluded_empty_text"),
            ("user", "completed", None, "excluded_empty_text"),
        ]:
            self.assertEqual(input_eligibility(role, status, text), {"eligible": False, "reason_code": expected})
        self.assertTrue(input_eligibility("user", "completed", "我今天很开心")["eligible"])

    def test_actual_configuration_hash_and_json_preview(self):
        config = configuration()
        self.assertEqual(len(config["config_sha256"]), 64)
        self.assertIn(config["config_sha256"][:24], config["config_version"])
        self.assertEqual(config, configuration())
        preview = local_preview("我今天很开心。")
        self.assertEqual(preview["source_kind"], "local_preview")
        self.assertFalse(preview["is_persisted"])
        self.assertTrue(preview["is_test"])
        self.assertNotIn("result_id", preview)
        self.assertNotIn("input_snapshot", preview)
        json.dumps(preview)

    def test_templates_no_unreviewed_phone_numbers_or_model_generated_advice(self):
        data = json.loads((Path(__file__).resolve().parents[1] / "care_core/templates.v1.json").read_text(encoding="utf-8"))
        self.assertIn("pending", data["review_state"])
        for template in data["templates"].values():
            self.assertNotRegex(template["text"], r"\d{3,}|保证治愈|你患有|服用|加药|停药")

    def test_cli_reads_event_from_stdin_without_db_audio_dependencies(self):
        environment = {**os.environ, "PYTHONUTF8": "1"}
        for event, expected in [({"text": "我今天很开心。"}, "classified"),
                                ({"text": "开心", "role": "assistant"}, "excluded")]:
            process = subprocess.run([sys.executable, "-m", "care_core"],
                                     input=json.dumps(event, ensure_ascii=False).encode("utf-8"),
                                     capture_output=True, env=environment, cwd=Path(__file__).resolve().parents[1])
            self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8"))
            output = json.loads(process.stdout)
            self.assertEqual(output["classification_status"], expected)
            self.assertFalse(output["is_persisted"])
        process = subprocess.run([sys.executable, "-m", "care_core"], input=SHORT_SECRET.encode("utf-8"),
                                 capture_output=True, env=environment, cwd=Path(__file__).resolve().parents[1])
        self.assertEqual(process.returncode, 2)
        self.assertNotIn(SHORT_SECRET.encode("utf-8"), process.stdout + process.stderr)


class OllamaProtocolTests(unittest.TestCase):
    def test_real_http_request_schema_and_response(self):
        with fake_ollama() as (settings, received):
            actual = analyze("我今天很开心。", "ollama", settings=settings)
            self.assertEqual(actual["engine_kind"], "ollama")
            self.assertEqual(actual["engine_version"], "ollama-chat-v1")
            self.assertEqual(actual["emotion_label"], "positive")
            payload = received[0]["body"]
            self.assertEqual(received[0]["path"], "/api/chat")
            self.assertEqual(payload["model"], MODEL_NAME)
            self.assertFalse(payload["stream"])
            self.assertFalse(payload["format"]["additionalProperties"])
            self.assertEqual(payload["options"], {"temperature": 0})
            self.assertEqual(payload["messages"][1], {"role": "user", "content": "我今天很开心。"})
            self.assertEqual(len(received), 1)

    def test_unknown_labels_shapes_and_illegal_json_fail_without_fallback(self):
        cases = [
            b"not-json", json.dumps({"error": SHORT_SECRET}),
            json.dumps(envelope({"classification_status": "classified", "emotion_label": "happy", "reason_code": "model_classified"})),
            json.dumps(envelope({"classification_status": "unable_to_determine", "emotion_label": "neutral", "reason_code": "insufficient_evidence"})),
            json.dumps(envelope({"classification_status": "classified", "emotion_label": "positive", "reason_code": "model_classified", "advice": LONG_SECRET})),
            json.dumps(envelope(done=False)), json.dumps(envelope(model="different-model")),
            json.dumps(envelope(message={"role": "assistant", "content": '{"classification_status":"classified","emotion_label":"positive","emotion_label":"negative","reason_code":"model_classified"}'})),
        ]
        for raw in cases:
            with self.subTest(case_type=type(raw).__name__), fake_ollama(raw=raw) as (settings, received):
                with self.assertRaises(CoreAnalysisError) as caught:
                    analyze(SHORT_SECRET + LONG_SECRET, "ollama", settings=settings)
                self.assertEqual(caught.exception.code, "model_protocol_invalid")
                self.assertEqual(len(received), 1)
                self.assertNotIn(SHORT_SECRET, str(caught.exception) + repr(caught.exception))
                self.assertNotIn(LONG_SECRET, str(caught.exception) + repr(caught.exception))

    def test_unknown_is_successful_and_has_no_neutral_label(self):
        raw = json.dumps(envelope({"classification_status": "unable_to_determine", "emotion_label": None, "reason_code": "insufficient_evidence"}))
        with fake_ollama(raw=raw) as (settings, _):
            actual = analyze("还好吧", "ollama", settings=settings)
            self.assertEqual(actual["classification_status"], "unable_to_determine")
            self.assertIsNone(actual["emotion_label"])

    def test_timeout_preserves_independent_safety_prompt(self):
        with fake_ollama(delay=0.2) as (settings, received):
            with self.assertRaises(CoreAnalysisError) as caught:
                analyze("我不想活了。" + SHORT_SECRET, "ollama", settings=replace(settings, timeout_seconds=0.03))
            self.assertEqual(caught.exception.code, "model_timeout")
            self.assertTrue(caught.exception.retryable)
            signal = caught.exception.safety_result
            self.assertEqual(signal["safety_signal"], "explicit_danger_expression")
            self.assertEqual(signal["support"]["template_id"], "safety_human_help")
            self.assertNotIn(SHORT_SECRET, repr(caught.exception))
            self.assertEqual(len(received), 1)

    def test_http_failure_size_limit_redirect_and_missing_config_are_safe(self):
        with fake_ollama(status=500, raw=SHORT_SECRET + LONG_SECRET) as (settings, _):
            with self.assertRaises(CoreAnalysisError) as caught:
                analyze(SHORT_SECRET, "ollama", settings=settings)
            self.assertEqual(caught.exception.code, "model_http_error")
            self.assertTrue(caught.exception.retryable)
            self.assertNotIn(SHORT_SECRET, str(caught.exception))
        with fake_ollama(raw=b"x" * 2048) as (settings, _):
            with self.assertRaises(CoreAnalysisError) as caught:
                analyze("开心", "ollama", settings=replace(settings, max_response_bytes=1024))
            self.assertEqual(caught.exception.code, "model_response_too_large")
        with fake_ollama() as (trap, trap_received):
            with fake_ollama(status=307, location=trap.model_base_url + "/api/chat") as (settings, _):
                with self.assertRaises(CoreAnalysisError) as caught:
                    analyze(SHORT_SECRET, "ollama", settings=settings)
                self.assertEqual(caught.exception.code, "model_http_error")
                self.assertEqual(trap_received, [])
        with self.assertRaises(CoreAnalysisError) as caught:
            analyze("我不想活了", "ollama", settings=CoreSettings())
        self.assertEqual(caught.exception.code, "model_configuration_missing")
        self.assertEqual(caught.exception.safety_result["safety_signal"], "explicit_danger_expression")

    def test_configuration_changes_are_visible_and_credentials_rejected(self):
        settings = CoreSettings("http://localhost:1234", MODEL_NAME)
        one = configuration("ollama", settings)
        for changed in (replace(settings, timeout_seconds=2), replace(settings, model_name="other-model:v2"),
                        replace(settings, model_base_url="http://localhost:1235")):
            self.assertNotEqual(one["config_version"], configuration("ollama", changed)["config_version"])
        for bad in ("http://u:secret@localhost:1234", "https://localhost/api?secret=value", "file:///sensitive"):
            with self.assertRaises(CoreAnalysisError) as caught:
                configuration("ollama", replace(settings, model_base_url=bad))
            self.assertEqual(str(caught.exception), "model_configuration_invalid")
        self.assertNotIn("localhost", json.dumps(one))
        self.assertNotIn("secret", repr(settings))
        with patch.dict(os.environ, {"ROBOT_CARE_MODEL_TIMEOUT_SECONDS": "secret-invalid"}):
            with self.assertRaises(CoreAnalysisError) as caught:
                CoreSettings.from_env()
            self.assertEqual(str(caught.exception), "model_configuration_invalid")

    def test_default_model_exceptions_emit_no_source_or_response(self):
        captured = io.StringIO()
        with redirect_stdout(captured), redirect_stderr(captured):
            with fake_ollama(status=500, raw=SHORT_SECRET + LONG_SECRET) as (settings, _):
                try:
                    analyze(SHORT_SECRET + LONG_SECRET, "ollama", settings=settings)
                except CoreAnalysisError as exc:
                    # The same safe representation is suitable for default application logging.
                    print(str(exc), repr(exc))
        output = captured.getvalue()
        self.assertIn("model_http_error", output)
        self.assertNotIn(SHORT_SECRET, output)
        self.assertNotIn(LONG_SECRET, output)


if __name__ == "__main__":
    unittest.main()
