#!/usr/bin/env bash
set -euo pipefail

FLAG_FILE="/var/lib/dt-core/RCRA3.restore_older_version"
REPO_DIR="/var/lib/dt-core"
LOG_FILE="/var/lib/dt-core/restore_github.log"
HISTORY_LOG="/var/lib/dt-core/restore_logA.txt"
FLOOR_FILE="/var/lib/dt-core/.restore_floor"
DEFAULT_FLOOR=98

[[ -f "$FLAG_FILE" ]] || exit 0

exec >>"$LOG_FILE" 2>&1
echo "========================================"
echo "Restore requested at $(date -u '+%Y-%m-%d %H:%M:%S UTC')"

TARGET_REF="$(head -n 1 "$FLAG_FILE" | tr -d '\r' | xargs)"
[[ -n "$TARGET_REF" ]] || {
    echo "ERROR: restore flag is empty."
    exit 1
}

cd "$REPO_DIR"
git rev-parse --is-inside-work-tree >/dev/null
git fetch origin --prune || echo "WARNING: fetch failed; using local refs."

FLOOR="$DEFAULT_FLOOR"
if [[ -f "$FLOOR_FILE" ]]; then
    FLOOR="$(tr -d '[:space:]' < "$FLOOR_FILE")"
fi
[[ "$FLOOR" =~ ^[0-9]+$ ]] || {
    echo "ERROR: invalid restore floor: $FLOOR"
    exit 1
}
(( FLOOR >= DEFAULT_FLOOR )) || {
    echo "ERROR: restore floor $FLOOR is below mandatory minimum $DEFAULT_FLOOR"
    exit 1
}

git rev-parse --verify "${TARGET_REF}^{commit}" >/dev/null || {
    echo "ERROR: target ref does not exist: $TARGET_REF"
    exit 1
}

TARGET_VERSION="$(git show "${TARGET_REF}:commit_ver.txt" 2>/dev/null | tr -d '[:space:]')" || {
    echo "ERROR: target has no readable commit_ver.txt."
    exit 1
}
[[ "$TARGET_VERSION" =~ ^[0-9]+$ ]] || {
    echo "ERROR: target commit_ver is invalid: $TARGET_VERSION"
    exit 1
}
if (( TARGET_VERSION < FLOOR )); then
    echo "REFUSED: target version $TARGET_VERSION is below protected floor $FLOOR."
    exit 98
fi

CURRENT_COMMIT="$(git rev-parse HEAD)"
CURRENT_VERSION="$(tr -d '[:space:]' < commit_ver.txt)"
printf '%s current=%s version=%s target=%s target_version=%s\n' \
    "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
    "$CURRENT_COMMIT" "$CURRENT_VERSION" "$TARGET_REF" "$TARGET_VERSION" \
    >> "$HISTORY_LOG"

BACKUP_TAG="before-restore-$(date +%Y%m%d-%H%M%S)"
git tag "$BACKUP_TAG" "$CURRENT_COMMIT"
git reset --hard "$TARGET_REF"

RESTORED_VERSION="$(tr -d '[:space:]' < commit_ver.txt)"
if (( RESTORED_VERSION < FLOOR )); then
    echo "CRITICAL: restored version fell below $FLOOR; rolling back."
    git reset --hard "$BACKUP_TAG"
    exit 99
fi

rm -f "$FLAG_FILE"
echo "Restore completed at version $RESTORED_VERSION."
