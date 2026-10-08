#!/usr/bin/env bash
#
# Cron entrypoint for backup-mysql-to-s3.sh — point cron at THIS file,
# not the backup script directly.
#
# Adds three things cron needs that the backup script itself doesn't do:
#   - locking, so a slow run can't overlap with the next scheduled one
#   - timestamped logging to a file (cron discards stdout/stderr by default)
#   - an optional Slack alert if the backup fails
#
# Usage: cron-wrapper.sh /path/to/backup.conf
#
set -euo pipefail

# Cron invokes this with a minimal environment (typically just PATH=/usr/bin:/bin),
# NOT the interactive-shell PATH that has Homebrew/manual installs on it. Without
# this, mysqldump/aws/flock can all be missing even though they work fine when
# you run this script by hand. Confirmed by testing under real cron, not assumed.
# EXTRA_PATH (set in backup.conf) covers any project-specific install location
# beyond these common ones.
export PATH="/usr/local/bin:/usr/local/sbin:/opt/homebrew/bin:/opt/homebrew/sbin:${EXTRA_PATH:+$EXTRA_PATH:}$PATH"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${1:?Usage: cron-wrapper.sh /path/to/backup.conf}"

[[ -f "$CONFIG_FILE" ]] || { echo "Config file not found: $CONFIG_FILE" >&2; exit 1; }
# shellcheck disable=SC1090
source "$CONFIG_FILE"

# Config may set its own EXTRA_PATH; fold it in now that it's known.
export PATH="${EXTRA_PATH:+$EXTRA_PATH:}$PATH"

command -v flock >/dev/null 2>&1 || { echo "flock not found in PATH (ships with util-linux on most Linux distros; on macOS run 'brew install flock', or set EXTRA_PATH in backup.conf)" >&2; exit 1; }

# Identify this run by the config file's absolute path, not just its
# filename — every project's config is conventionally named "backup.conf",
# so a name-only identifier would make every project share the same lock
# and log file (one project's midnight run would silently "skip" thinking
# ITSELF was still running, when it was actually a different project's job).
CONFIG_ABS_PATH="$(cd "$(dirname "$CONFIG_FILE")" && pwd)/$(basename "$CONFIG_FILE")"
# cksum is POSIX-standard and present in cron's default minimal PATH on both
# macOS and Linux, unlike md5/md5sum (paths/availability differ per platform).
CONFIG_HASH="$(printf '%s' "$CONFIG_ABS_PATH" | cksum | cut -d' ' -f1)"
CONFIG_NAME="${DB_NAME:-backup}-${CONFIG_HASH}"
LOG_DIR="${LOG_DIR:-${BACKUP_DIR:-/tmp/mysql-backups}/logs}"
LOG_FILE="${LOG_FILE:-$LOG_DIR/${CONFIG_NAME}.log}"
LOCK_FILE="/tmp/mysql-backup-${CONFIG_NAME}.lock"

mkdir -p "$LOG_DIR"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Skipped: a previous run for '$CONFIG_NAME' is still in progress" >> "$LOG_FILE"
    exit 0
fi

{
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ==== Starting backup run ($CONFIG_NAME) ===="
    if "$SCRIPT_DIR/backup-mysql-to-s3.sh" "$CONFIG_FILE"; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ==== Backup run OK ($CONFIG_NAME) ===="
    else
        STATUS=$?
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ==== Backup run FAILED ($CONFIG_NAME), exit $STATUS ===="
        if [[ -n "${SLACK_WEBHOOK_URL:-}" ]]; then
            curl -sf -X POST -H 'Content-type: application/json' \
                --data "{\"text\":\":x: MySQL backup failed for *${CONFIG_NAME}* (exit ${STATUS}) on $(hostname). Log: ${LOG_FILE}\"}" \
                "$SLACK_WEBHOOK_URL" >/dev/null 2>&1 \
                || echo "[$(date '+%Y-%m-%d %H:%M:%S')] (Slack notification also failed to send)"
        fi
        exit "$STATUS"
    fi
} >> "$LOG_FILE" 2>&1
