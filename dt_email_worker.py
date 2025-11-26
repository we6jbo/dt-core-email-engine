#!/usr/bin/env python3
import sys
import traceback
from datetime import datetime
from pathlib import Path

from models import DTRequest
from decision_engine import generate_answer

LOG = Path("/var/log/dt-core-email.log")

def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}\n"
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception:
        sys.stderr.write(line)

class FakeMessage:
    def __init__(self) -> None:
        self.subject = "dt-in RQ:TEST-LOCAL-001"
        self.request_id = "TEST-LOCAL-001"
        self.question_text = "What are some good federal jobs?"

def main() -> int:
    try:
        msg = FakeMessage()
        log(f"processing dt-in subject={msg.subject!r} rq={msg.request_id!r} q={msg.question_text!r}")

        req = DTRequest(question=msg.question_text)
        log("DTRequest created, calling generate_answer()")

        try:
            answer = generate_answer(req)
        except Exception:
            tb = traceback.format_exc()
            log("ERROR in generate_answer:\n" + tb)
            print("generate_answer crashed, see log", file=sys.stderr)
            return 1

        if not answer:
            log("WARNING: generate_answer returned empty/None")
            print("no answer generated", file=sys.stderr)
            return 1

        log(f"generate_answer OK, len={len(answer)}")
        print("=== ANSWER START ===")
        print(answer)
        print("=== ANSWER END ===")
        return 0

    except Exception:
        tb = traceback.format_exc()
        log("FATAL in dt_email_worker:\n" + tb)
        print("fatal error, see log", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())

