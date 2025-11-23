#!/usr/bin/env python3
"""
push_lessons.py

If /tmp/files-will-get-deleted-1123/ready-to-push.txt exists, delete it
and run /var/lib/dt-core/commit_and_verify.py.
"""

import os
import subprocess
import sys
from pathlib import Path
import datetime

READY_FILE = Path("/tmp/files-will-get-deleted-1123/ready-to-push.txt")
COMMIT_SCRIPT = Path("/var/lib/dt-core/commit_and_verify.py")


def _stderr(msg: str) -> None:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sys.stderr.write(f"[push_lessons {now}] {msg}\n")
    sys.stderr.flush()


def run_if_ready() -> None:
    """Check ready marker, delete it, run commit script."""
    if not READY_FILE.exists():
        _stderr("Ready marker does not exist. Nothing to do.")
        return

    # Remove ready-to-push.txt
    try:
        READY_FILE.unlink()
        _stderr(f"Removed {READY_FILE}")
    except Exception as e:  # noqa: BLE001
        _stderr(f"Failed removing ready marker: {e!r}")
        return

    # Execute commit_and_verify.py
    try:
        _stderr(f"Running {COMMIT_SCRIPT}")
        subprocess.run(
            ["python3", str(COMMIT_SCRIPT)],
            check=True
        )
        _stderr("commit_and_verify.py completed successfully.")
    except subprocess.CalledProcessError as e:
        _stderr(f"commit_and_verify.py failed: {e!r}")
    except Exception as e:
        _stderr(f"Unexpected error: {e!r}")


if __name__ == "__main__":
    run_if_ready()

