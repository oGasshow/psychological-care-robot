"""Read one fictional text event from stdin; emit an unmistakable local preview."""

import argparse
import json
import sys

from . import CoreAnalysisError, input_eligibility, local_preview


def main():
    parser = argparse.ArgumentParser(description="Unsaved, non-clinical local text preview")
    parser.add_argument("--engine", choices=("rules", "ollama"), default="rules")
    args = parser.parse_args()
    try:
        # Bounded input; argv never contains the psychological text or model settings.
        raw = sys.stdin.buffer.read(40000)
        if len(raw) >= 40000:
            raise ValueError()
        event = json.loads(raw)
        if not isinstance(event, dict) or set(event) - {"text", "role", "text_status"}:
            raise ValueError()
        eligibility = input_eligibility(event.get("role", "user"), event.get("text_status", "completed"), event.get("text"))
        if eligibility["eligible"]:
            output = local_preview(event["text"], args.engine)
        else:
            output = {"schema_version": "1.0", "source_kind": "local_preview", "is_persisted": False,
                      "is_test": True, "classification_status": "excluded", **eligibility}
        print(json.dumps(output, ensure_ascii=False))
        return 0
    except CoreAnalysisError as exc:
        print(json.dumps({"error": {"code": exc.code, "retryable": exc.retryable},
                          "source_kind": "local_preview", "is_persisted": False,
                          "safety": exc.safety_result}, ensure_ascii=False))
        return 2
    except (ValueError, TypeError, KeyError, UnicodeError):
        print(json.dumps({"error": {"code": "preview_event_invalid", "retryable": False}}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
