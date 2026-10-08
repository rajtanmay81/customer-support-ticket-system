#!/usr/bin/env bash
#
# Generic MySQL -> S3 backup script.
# Usage: ./backup-mysql-to-s3.sh /path/to/backup.conf
# If no path is given, defaults to backup.conf next to this script.
#
# All project-specific values (DB creds, S3 path) live in the config file,
# so this script can be reused unmodified across projects.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${1:-$SCRIPT_DIR/backup.conf}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

fail() {
    log "ERROR: $*"
    exit 1
}

[[ -f "$CONFIG_FILE" ]] || fail "Config file not found: $CONFIG_FILE"
# shellcheck disable=SC1090
source "$CONFIG_FILE"

for var in DB_HOST DB_PORT DB_USER DB_PASSWORD DB_NAME S3_PATH BACKUP_DIR; do
    [[ -n "${!var:-}" ]] || fail "Required config value '$var' is not set in $CONFIG_FILE"
done

[[ "$S3_PATH" == s3://* ]] || fail "S3_PATH must start with s3:// (got: $S3_PATH)"

command -v mysqldump >/dev/null 2>&1 || fail "mysqldump not found in PATH"
command -v aws >/dev/null 2>&1 || fail "aws CLI not found in PATH"

COMPRESS="${COMPRESS:-true}"
DELETE_LOCAL_AFTER_UPLOAD="${DELETE_LOCAL_AFTER_UPLOAD:-true}"
LOCAL_RETENTION_DAYS="${LOCAL_RETENTION_DAYS:-0}"
AWS_PROFILE_ARGS=()
[[ -n "${AWS_PROFILE:-}" ]] && AWS_PROFILE_ARGS=(--profile "$AWS_PROFILE")

# Normalize S3 path to always end with a single trailing slash
S3_PATH="${S3_PATH%/}/"

mkdir -p "$BACKUP_DIR"

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
DUMP_FILE="$BACKUP_DIR/${DB_NAME}_${TIMESTAMP}.sql"

# Remove a partial dump if the script dies partway through, so failed runs
# don't leave a corrupt/empty file behind that could be confused for a good backup.
cleanup_on_error() {
    rm -f "$DUMP_FILE" "${DUMP_FILE}.gz"
}
trap cleanup_on_error ERR

log "Starting backup of database '$DB_NAME' from $DB_HOST:$DB_PORT"

# Credentials passed via env var (MYSQL_PWD) instead of --password on the
# command line, so they don't show up in `ps` output or shell history.
MYSQL_PWD="$DB_PASSWORD" mysqldump \
    --host="$DB_HOST" \
    --port="$DB_PORT" \
    --user="$DB_USER" \
    --single-transaction \
    --quick \
    --routines \
    --triggers \
    "$DB_NAME" > "$DUMP_FILE" \
    || fail "mysqldump failed for database '$DB_NAME'"

[[ -s "$DUMP_FILE" ]] || fail "Dump file is empty — check DB credentials/permissions ($DUMP_FILE)"

log "Dump written to $DUMP_FILE"

UPLOAD_FILE="$DUMP_FILE"
if [[ "$COMPRESS" == "true" ]]; then
    gzip -f "$DUMP_FILE" || fail "gzip compression failed"
    UPLOAD_FILE="${DUMP_FILE}.gz"
    log "Compressed to $UPLOAD_FILE"
fi

DEST="${S3_PATH}$(basename "$UPLOAD_FILE")"
log "Uploading to $DEST"

aws s3 cp "$UPLOAD_FILE" "$DEST" "${AWS_PROFILE_ARGS[@]}" \
    || fail "Upload to S3 failed"

log "Upload complete: $DEST"

if [[ "$DELETE_LOCAL_AFTER_UPLOAD" == "true" ]]; then
    rm -f "$UPLOAD_FILE"
    log "Removed local file $UPLOAD_FILE"
elif [[ "$LOCAL_RETENTION_DAYS" -gt 0 ]]; then
    find "$BACKUP_DIR" -name "${DB_NAME}_*.sql*" -mtime "+$LOCAL_RETENTION_DAYS" -delete
    log "Pruned local backups older than $LOCAL_RETENTION_DAYS days"
fi

log "Backup finished successfully"
