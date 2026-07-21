#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

REPO = Path("/var/lib/dt-core")
VERSION_FILE = REPO / "commit_ver.txt"
FLOOR_FILE = REPO / ".restore_floor"
REMOTE = "origin"
BRANCH = "main"
DEFAULT_FLOOR = 98
VERIFY_RETRIES = 10
VERIFY_DELAY = 10


def run(*args: str, capture: bool = False) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(args), flush=True)
    return subprocess.run(
        args,
        cwd=REPO,
        check=True,
        text=True,
        capture_output=capture,
    )


def read_int(path: Path, label: str) -> int:
    raw = path.read_text(encoding="utf-8").strip()
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{label} is not an integer: {raw!r}") from exc


def protected_floor() -> int:
    if not FLOOR_FILE.exists():
        return DEFAULT_FLOOR
    floor = read_int(FLOOR_FILE, str(FLOOR_FILE))
    if floor < DEFAULT_FLOOR:
        raise RuntimeError(
            f"Restore floor {floor} is below mandatory minimum {DEFAULT_FLOOR}"
        )
    return floor


def remote_version() -> int | None:
    try:
        run("git", "fetch", REMOTE, BRANCH)
        raw = run(
            "git", "show", f"{REMOTE}/{BRANCH}:commit_ver.txt", capture=True
        ).stdout.strip()
        return int(raw)
    except (subprocess.CalledProcessError, ValueError):
        return None


def validate() -> None:
    py_files = [
        str(path.relative_to(REPO))
        for path in REPO.glob("*.py")
        if path.is_file()
    ]
    if py_files:
        run(sys.executable, "-m", "py_compile", *py_files)

    for name in ("restore_github.sh", "dt-core-restore.sh", "lesson.sh"):
        path = REPO / name
        if path.exists():
            run("bash", "-n", str(path))


def main() -> int:
    floor = protected_floor()
    local = read_int(VERSION_FILE, str(VERSION_FILE))
    if local < floor:
        raise RuntimeError(
            f"Local version {local} is below protected floor {floor}; refusing."
        )

    remote = remote_version()
    if remote is not None and remote < floor:
        raise RuntimeError(
            f"Remote version {remote} is below protected floor {floor}; refusing."
        )

    new_version = max(local, remote or floor, floor) + 1
    validate()
    VERSION_FILE.write_text(f"{new_version}\n", encoding="utf-8")

    run("git", "add", "-A")
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO)
    if diff.returncode == 0:
        print("Nothing to commit.")
        return 0

    run("git", "commit", "-m", f"Auto commit_ver {new_version}")
    run("git", "push", REMOTE, f"HEAD:{BRANCH}")

    for attempt in range(1, VERIFY_RETRIES + 1):
        verified = remote_version()
        if verified == new_version:
            print(f"SUCCESS: remote commit_ver is {verified}.")
            return 0
        print(
            f"Verification {attempt}/{VERIFY_RETRIES}: "
            f"remote={verified!r}, expected={new_version}"
        )
        if attempt < VERIFY_RETRIES:
            time.sleep(VERIFY_DELAY)

    print("ERROR: push completed but remote verification failed.")
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
