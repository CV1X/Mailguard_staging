#!/usr/bin/env bash
# NOVA Cargo360 — restore application CODE from a backup archive.
# Usage: restore_code.sh mailguard_code_YYYYMMDD_HHMMSS.tar.gz [actor]
# Steps: validate name -> pre-restore backup of current code (attributed to actor) ->
#        stage-extract -> rsync --delete (code only, preserving .env/venv/storage/logs) -> restart.
# Re-execs from /tmp so rsync can safely overwrite our own scripts/ dir.
set -euo pipefail

APP_DIR="/opt/iris-mailguard"
BACKUP_DIR="$APP_DIR/storage/backups"
RLOG="$BACKUP_DIR/restore.log"

if [[ "${MG_RESTORE_REEXEC:-}" != "1" ]]; then
  SELF_TMP="$(mktemp /tmp/restore_code_XXXXXX.sh)"
  cp -- "$0" "$SELF_TMP"
  chmod +x "$SELF_TMP"
  export MG_RESTORE_REEXEC=1
  exec "$SELF_TMP" "$@"
fi

ARCHIVE_NAME="${1:-}"
ACTOR="${2:-}"
log(){ echo "$(date -Is) $*" >> "$RLOG"; }

if [[ ! "$ARCHIVE_NAME" =~ ^mailguard_code_[0-9]{8}_[0-9]{6}\.tar\.gz$ ]]; then
  log "REJECT invalid name: '$ARCHIVE_NAME'"; echo "invalid archive name" >&2; exit 2
fi
ARCHIVE="$BACKUP_DIR/$ARCHIVE_NAME"
if [[ ! -f "$ARCHIVE" ]]; then
  log "REJECT missing: $ARCHIVE_NAME"; echo "archive not found" >&2; exit 3
fi

log "START restore from $ARCHIVE_NAME by ${ACTOR:-unknown}"

if "$APP_DIR/scripts/backup_code.sh" --force prerestore "pre-restore inainte de $ARCHIVE_NAME" "$ACTOR" >> "$RLOG" 2>&1; then
  log "pre-restore backup created"
else
  log "WARN pre-restore backup failed (continuing)"
fi

STAGE="$(mktemp -d /tmp/mg_restore_XXXXXX)"
trap 'rm -rf "$STAGE"' EXIT
tar -xzf "$ARCHIVE" -C "$STAGE"

rsync -a --delete \
  --exclude='.env' \
  --exclude='venv/' \
  --exclude='storage/' \
  --exclude='logs/' \
  --exclude='.git/' \
  "$STAGE"/ "$APP_DIR"/ >> "$RLOG" 2>&1

log "RESTORED $ARCHIVE_NAME — restarting mailguard-api"

if systemctl restart mailguard-api >> "$RLOG" 2>&1; then
  log "DONE $ARCHIVE_NAME"
else
  log "WARN restart failed for $ARCHIVE_NAME"
fi
exit 0
