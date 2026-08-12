#!/usr/bin/env bash
# NOVA MailGuard — daily backup cleanup.
# Deletes code archives older than MAX_AGE_DAYS, but ALWAYS keeps the newest MIN_KEEP
# regardless of age (safety floor so a quiet stretch never wipes all restore points).
# Daily gate via stamp file; --force ignores the gate.
set -euo pipefail

APP_DIR="/opt/iris-mailguard"
BACKUP_DIR="$APP_DIR/storage/backups"
LOG="$BACKUP_DIR/backup.log"
STAMP="$BACKUP_DIR/.last_cleanup"
MAX_AGE_DAYS=3
MIN_KEEP=3

FORCE="${1:-}"

mkdir -p "$BACKUP_DIR"
log(){ echo "$(date -Is) $*" >> "$LOG"; }

today="$(date +%Y-%m-%d)"
if [[ "$FORCE" != "--force" ]]; then
  if [[ -f "$STAMP" && "$(cat "$STAMP" 2>/dev/null)" == "$today" ]]; then
    exit 0                                   # already ran today
  fi
fi

# Dump-uri ad-hoc de reset+reimport in /tmp: 1 zi de gratie pt. restaurare manuala, apoi sterse
# (nu incarca serverul). Acopera si reset-urile viitoare. Best-effort.
find /tmp -maxdepth 1 -name 'mailguard_pre_reset_*' -mtime +1 -delete 2>/dev/null || true

mapfile -t arcs < <(ls -1t "$BACKUP_DIR"/mailguard_code_*.tar.gz 2>/dev/null || true)
n=${#arcs[@]}
deleted=0

if (( n > MIN_KEEP )); then
  for ((i=MIN_KEEP; i<n; i++)); do
    f="${arcs[$i]}"
    if [[ -n "$(find "$f" -mtime +"$MAX_AGE_DAYS" -print 2>/dev/null)" ]]; then
      rm -f "$f" "$f.meta" "$f.manifest" "$f.worklog.json"
      deleted=$((deleted+1))
    fi
  done
fi

echo "$today" > "$STAMP"
log "CLEANUP deleted=$deleted kept_min=$MIN_KEEP age_gt=${MAX_AGE_DAYS}d total_before=$n"
exit 0
