#!/usr/bin/env bash
#
# Restore-verification test for the MySQL -> S3 backup script.
#
# Proves a backup is actually usable, not just "a file exists in S3":
#   1. Spin up a brand-new, empty MySQL server in Docker.
#   2. Pull the latest (or a specific) backup from S3.
#   3. Restore it into that empty server.
#   4. Check that tables + rows actually landed.
#   5. Tear the container down.
#
# Usage:
#   ./restore-test.sh /path/to/backup.conf                # restore latest backup for DB_NAME
#   ./restore-test.sh /path/to/backup.conf s3://.../file.sql.gz   # restore a specific backup
#
# Reuses the same config file as backup-mysql-to-s3.sh (needs at least
# DB_NAME, S3_PATH, and AWS_PROFILE if the bucket needs one). Only used here
# for locating backups and naming the test database — no write access to
# the real DB is needed or used.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${1:-}"
EXPLICIT_BACKUP="${2:-}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

fail() {
    log "ERROR: $*"
    exit 1
}

[[ -n "$CONFIG_FILE" ]] || fail "Usage: $0 /path/to/backup.conf [s3://bucket/path/file.sql.gz]"
[[ -f "$CONFIG_FILE" ]] || fail "Config file not found: $CONFIG_FILE"
# shellcheck disable=SC1090
source "$CONFIG_FILE"

for var in DB_NAME S3_PATH; do
    [[ -n "${!var:-}" ]] || fail "Required config value '$var' is not set in $CONFIG_FILE"
done

command -v docker >/dev/null 2>&1 || fail "docker not found in PATH"
command -v aws >/dev/null 2>&1 || fail "aws CLI not found in PATH"
docker info >/dev/null 2>&1 || fail "Docker daemon is not running (or no permission to talk to it)"

AWS_PROFILE_ARGS=()
[[ -n "${AWS_PROFILE:-}" ]] && AWS_PROFILE_ARGS=(--profile "$AWS_PROFILE")

S3_PATH="${S3_PATH%/}/"

RESTORE_DOCKER_IMAGE="${RESTORE_DOCKER_IMAGE:-mysql:8.4}"
RESTORE_CONTAINER_NAME="${RESTORE_CONTAINER_NAME:-mysql-restore-test-${DB_NAME}}"
RESTORE_ROOT_PASSWORD="${RESTORE_ROOT_PASSWORD:-$(openssl rand -hex 16)}"
KEEP_CONTAINER="${KEEP_CONTAINER:-false}"

WORK_DIR="$(mktemp -d /tmp/restore-test.XXXXXX)"

CONTAINER_STARTED="false"

cleanup() {
    local exit_code=$?
    if [[ "$CONTAINER_STARTED" == "true" && "$KEEP_CONTAINER" != "true" ]]; then
        log "Removing test container '$RESTORE_CONTAINER_NAME'"
        docker rm -f "$RESTORE_CONTAINER_NAME" >/dev/null 2>&1 || true
    elif [[ "$CONTAINER_STARTED" == "true" ]]; then
        log "KEEP_CONTAINER=true — leaving '$RESTORE_CONTAINER_NAME' running for inspection"
    fi
    rm -rf "$WORK_DIR"
    exit "$exit_code"
}
trap cleanup EXIT

# --- 1. Locate the backup file ---
if [[ -n "$EXPLICIT_BACKUP" ]]; then
    SOURCE_KEY="$EXPLICIT_BACKUP"
else
    log "Finding latest backup for '$DB_NAME' under $S3_PATH"
    LATEST_NAME="$(aws s3 ls "$S3_PATH" "${AWS_PROFILE_ARGS[@]}" \
        | awk '{print $4}' \
        | grep "^${DB_NAME}_" \
        | sort \
        | tail -n1)"
    [[ -n "$LATEST_NAME" ]] || fail "No backups found for '$DB_NAME' under $S3_PATH"
    SOURCE_KEY="${S3_PATH}${LATEST_NAME}"
fi

log "Using backup: $SOURCE_KEY"

LOCAL_FILE="$WORK_DIR/$(basename "$SOURCE_KEY")"
aws s3 cp "$SOURCE_KEY" "$LOCAL_FILE" "${AWS_PROFILE_ARGS[@]}" \
    || fail "Failed to download $SOURCE_KEY"

if [[ "$LOCAL_FILE" == *.gz ]]; then
    gunzip "$LOCAL_FILE"
    LOCAL_FILE="${LOCAL_FILE%.gz}"
fi

[[ -s "$LOCAL_FILE" ]] || fail "Downloaded backup is empty: $LOCAL_FILE"
log "Backup ready locally: $LOCAL_FILE ($(du -h "$LOCAL_FILE" | cut -f1))"

# --- 2. Start a fresh, empty MySQL container ---
log "Starting empty MySQL container '$RESTORE_CONTAINER_NAME' ($RESTORE_DOCKER_IMAGE)"
docker rm -f "$RESTORE_CONTAINER_NAME" >/dev/null 2>&1 || true
docker run -d \
    --name "$RESTORE_CONTAINER_NAME" \
    -e MYSQL_ROOT_PASSWORD="$RESTORE_ROOT_PASSWORD" \
    -P \
    "$RESTORE_DOCKER_IMAGE" >/dev/null \
    || fail "Failed to start Docker container"
CONTAINER_STARTED="true"

RESTORE_PORT="$(docker port "$RESTORE_CONTAINER_NAME" 3306/tcp | head -n1 | cut -d: -f2)"
[[ -n "$RESTORE_PORT" ]] || fail "Could not determine mapped port for container"
log "Container listening on 127.0.0.1:$RESTORE_PORT (root password generated for this test only)"

log "Waiting for MySQL to accept connections..."
READY="false"
for _ in $(seq 1 30); do
    if MYSQL_PWD="$RESTORE_ROOT_PASSWORD" mysql -h 127.0.0.1 -P "$RESTORE_PORT" -u root -e "SELECT 1;" >/dev/null 2>&1; then
        READY="true"
        break
    fi
    sleep 2
done
[[ "$READY" == "true" ]] || fail "MySQL in container never became ready after 60s"

# --- 3. Create empty target DB and restore into it ---
log "Creating empty database '$DB_NAME' in the test container"
MYSQL_PWD="$RESTORE_ROOT_PASSWORD" mysql -h 127.0.0.1 -P "$RESTORE_PORT" -u root \
    -e "CREATE DATABASE \`$DB_NAME\`;" \
    || fail "Failed to create database '$DB_NAME' in test container"

log "Restoring backup into '$DB_NAME'..."
MYSQL_PWD="$RESTORE_ROOT_PASSWORD" mysql -h 127.0.0.1 -P "$RESTORE_PORT" -u root "$DB_NAME" < "$LOCAL_FILE" \
    || fail "Restore failed — the backup file did not load cleanly"

# --- 4. Verify data actually landed ---
TABLE_COUNT="$(MYSQL_PWD="$RESTORE_ROOT_PASSWORD" mysql -h 127.0.0.1 -P "$RESTORE_PORT" -u root -N \
    -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='$DB_NAME';")"

[[ "$TABLE_COUNT" -gt 0 ]] || fail "Restore produced 0 tables — backup is not usable"

log "Restore produced $TABLE_COUNT table(s). Row counts:"
MYSQL_PWD="$RESTORE_ROOT_PASSWORD" mysql -h 127.0.0.1 -P "$RESTORE_PORT" -u root -N \
    -e "SELECT table_name, table_rows FROM information_schema.tables WHERE table_schema='$DB_NAME' ORDER BY table_name;" \
    | while IFS=$'\t' read -r tbl rows; do
        log "  - $tbl: ~$rows rows"
    done

log "RESTORE TEST PASSED — backup '$SOURCE_KEY' is valid and restorable"
