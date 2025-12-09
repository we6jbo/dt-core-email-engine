#!/bin/bash
# dt-core-restore.sh
# Check for /tmp/reset-back-to-nov-28.txt and, if present, restore /var/lib/dt-core
# to a known Git ref.

FLAG_FILE="/tmp/reset-back-to-nov-28.txt"
REPO_DIR="/var/lib/dt-core"
TARGET_REF="restore-2025-11-28e"   # Tag or commit hash to restore to
LOG_FILE="/var/log/dt-core-restore.log"

# If the flag file doesn't exist, just exit quietly
if [ ! -f "$FLAG_FILE" ]; then
    exit 0
fi

{
    echo "[$(date)] Restore triggered because $FLAG_FILE exists."

    # Remove the flag file first so it doesn't retrigger if something fails later
    rm -f "$FLAG_FILE" || echo "Warning: failed to remove $FLAG_FILE"

    # Go to the repo
    if ! cd "$REPO_DIR"; then
        echo "Error: cannot cd to $REPO_DIR"
        exit 1
    fi

    echo "[$(date)] Fetching from origin..."
    git fetch --all --prune || echo "Warning: git fetch failed (using local refs only)."

    echo "[$(date)] Hard-reset to $TARGET_REF..."
    git reset --hard "$TARGET_REF" || {
        echo "Error: git reset --hard $TARGET_REF failed."
        exit 1
    }

    echo "[$(date)] Cleaning untracked files..."
    git clean -fdx || echo "Warning: git clean failed."

    echo "[$(date)] Restore completed."
} >> "$LOG_FILE" 2>&1

