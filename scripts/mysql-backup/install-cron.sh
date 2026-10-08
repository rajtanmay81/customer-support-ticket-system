#!/usr/bin/env bash
#
# Installs (or updates) the crontab entry that runs this project's nightly
# backup. Safe to re-run: it replaces any existing entry for the same
# backup.conf rather than duplicating it.
#
# Usage: install-cron.sh /path/to/backup.conf ["cron schedule"]
#   Default schedule is "0 0 * * *" (every day at midnight, server-local time).
#
# Example:
#   ./install-cron.sh /Users/mac/Desktop/cuw_backend/backup.conf
#   ./install-cron.sh /path/to/other-project/backup.conf "30 1 * * *"
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${1:?Usage: install-cron.sh /path/to/backup.conf [\"cron schedule\"]}"
SCHEDULE="${2:-0 0 * * *}"

[[ -f "$CONFIG_FILE" ]] || { echo "Config file not found: $CONFIG_FILE" >&2; exit 1; }
CONFIG_FILE="$(cd "$(dirname "$CONFIG_FILE")" && pwd)/$(basename "$CONFIG_FILE")"

WRAPPER="$SCRIPT_DIR/cron-wrapper.sh"
MARKER="# mysql-backup:${CONFIG_FILE}"
CRON_LINE="${SCHEDULE} ${WRAPPER} ${CONFIG_FILE} ${MARKER}"

TMP_CRON="$(mktemp)"
trap 'rm -f "$TMP_CRON"' EXIT

crontab -l 2>/dev/null | grep -vF "$MARKER" > "$TMP_CRON" || true
echo "$CRON_LINE" >> "$TMP_CRON"
crontab "$TMP_CRON"

echo "Installed/updated cron entry:"
echo "  $CRON_LINE"
echo
echo "Current crontab:"
crontab -l
