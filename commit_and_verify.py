#!/usr/bin/env python3
"""
commit_and_verify.py

- Increments commit_ver.txt locally.
- Commits ALL non-ignored files in /var/lib/dt-core.
- Pushes to origin/main.
- Polls the remote raw URL for commit_ver.txt.
- If the remote value does not match the new local value after retries,
  exits non-zero so a wrapper can "try something else".
"""

import os
import sys
import time
import subprocess
from urllib.request import urlopen
from urllib.error import URLError, HTTPError

REPO_DIR = "/var/lib/dt-core"
LOCAL_FILE = "commit_ver.txt"
REMOTE_URL = (
    "https://raw.githubusercontent.com/we6jbo/dt-core-email-engine/"
    "refs/heads/main/commit_ver.txt"
)

MAX_RETRIES = 10
SLEEP_SECONDS = 10


def run_cmd(cmd: list[str]) -> subprocess.CompletedProcess:
    """Run a command and return CompletedProcess, raising on error."""
    print(f"[commit-bot] Running: {' '.join(cmd)}")
    return subprocess.run(cmd, check=True, text=True, capture_output=True)


def read_local_version() -> int:
    """Read local commit_ver.txt as an int. If missing/invalid, treat as 0."""
    path = os.path.join(REPO_DIR, LOCAL_FILE)
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read().strip()
        return int(raw)
    except FileNotFoundError:
        print("[commit-bot] No local commit_ver.txt found, starting at 0.")
        return 0
    except ValueError:
        print("[commit-bot] Invalid local commit_ver.txt, treating as 0.")
        return 0


def write_local_version(new_ver: int) -> None:
    """Write new integer version to commit_ver.txt."""
    path = os.path.join(REPO_DIR, LOCAL_FILE)
    print(f"[commit-bot] Writing local {LOCAL_FILE} = {new_ver}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"{new_ver}\n")


def read_remote_version() -> int | None:
    """Fetch remote commit_ver.txt. Return int or None if not available/invalid."""
    print(f"[commit-bot] Checking remote {REMOTE_URL}")
    try:
        with urlopen(REMOTE_URL, timeout=10) as resp:
            raw = resp.read().decode("utf-8").strip()
        print(f"[commit-bot] Remote raw content: {raw!r}")
        return int(raw)
    except (HTTPError, URLError) as e:
        print(f"[commit-bot] Remote fetch error: {e}")
        return None
    except ValueError:
        print("[commit-bot] Remote commit_ver.txt not an integer.")
        return None


def main() -> int:
    # 1. cd into repo
    try:
        os.chdir(REPO_DIR)
    except OSError as e:
        print(f"[commit-bot] ERROR: Cannot chdir to {REPO_DIR}: {e}")
        return 1

    # 2. Increment local commit_ver
    current_local = read_local_version()
    new_ver = current_local + 1
    write_local_version(new_ver)

    # 3. Stage ALL changes (respects .gitignore)
    try:
        run_cmd(["git", "add", "."])

        commit_msg = f"Auto commit_ver {new_ver}"
        try:
            result = run_cmd(["git", "commit", "-m", commit_msg])
            print(result.stdout)
        except subprocess.CalledProcessError as e:
            # If there's truly nothing to commit, we can still try pushing.
            text = (e.stdout or "") + (e.stderr or "")
            if "nothing to commit" in text:
                print("[commit-bot] Nothing to commit after bumping commit_ver.txt (unexpected).")
                # In theory this should not happen because we just wrote commit_ver.txt.
                # Still, continue to push in case remote is behind.
            else:
                print("[commit-bot] git commit failed:")
                print(e.stdout)
                print(e.stderr)
                return 1

        # 4. Push to origin/main
        result = run_cmd(["git", "push", "origin", "main"])
        print(result.stdout)
    except subprocess.CalledProcessError as e:
        print("[commit-bot] Git command failed:")
        print(e.stdout)
        print(e.stderr)
        return 1

    # 5. Verify the remote commit_ver.txt matches new_ver
    print(f"[commit-bot] Verifying remote version reaches {new_ver}...")
    for attempt in range(1, MAX_RETRIES + 1):
        remote_ver = read_remote_version()
        if remote_ver is None:
            print(f"[commit-bot] Attempt {attempt}/{MAX_RETRIES}: remote version unavailable.")
        elif remote_ver == new_ver:
            print(f"[commit-bot] SUCCESS: Remote commit_ver.txt is now {remote_ver}.")
            return 0
        else:
            print(
                f"[commit-bot] Attempt {attempt}/{MAX_RETRIES}: "
                f"remote_ver={remote_ver}, expected={new_ver}"
            )

        if attempt < MAX_RETRIES:
            print(f"[commit-bot] Sleeping {SLEEP_SECONDS} seconds before retry...")
            time.sleep(SLEEP_SECONDS)

    print(f"[commit-bot] FAILURE: Remote commit_ver.txt did not reach {new_ver}.")
    # Exit 2 = push seemed ok but GitHub never reflected new_ver.
    return 2


if __name__ == "__main__":
    sys.exit(main())

