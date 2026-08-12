#!/bin/bash
# Cargo360 — aplică migrările SQL din migrations/ ÎNAINTE de pornirea mailguard-api.
# Apelat ca ExecStartPre în unit-ul systemd (deci la fiecare `systemctl restart`, inclusiv în
# fluxul de release `git pull && systemctl restart`) ȘI utilizabil standalone.
#
# Proprietăți cerute:
#  - idempotent: migrările au IF NOT EXISTS; în plus tabelul _release_migrations marchează ce s-a
#    aplicat, ca să nu re-ruleze inutil;
#  - ordine cronologică după numele fișierului (prefix dată, ex. 20260625_*.sql);
#  - FAIL-FAST: dacă o migrare eșuează → exit 1 → ExecStartPre eșuează → serviciul NU pornește pe
#    cod incompatibil cu schema;
#  - conexiune prin containerul Docker Postgres (user/db din .env, fallback cargo360/cargo360).
set -uo pipefail

APP_DIR="/opt/iris-mailguard"
MIG_DIR="$APP_DIR/migrations"
DB_CONTAINER="${MAILGUARD_DB_CONTAINER:-mailguard-db}"
_envval(){ grep -E "^$1=" "$APP_DIR/.env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'" ; }
DB_USER="$(_envval DB_USER)"; DB_USER="${DB_USER:-cargo360}"
DB_NAME="$(_envval DB_NAME)"; DB_NAME="${DB_NAME:-cargo360}"

log(){ echo "[migrate $(date +%H:%M:%S)] $*"; }
# query helper (-c), fără stdin
pq(){ sudo docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" "$@"; }

[ -d "$MIG_DIR" ] || { log "fără director migrations ($MIG_DIR) — nimic de făcut"; exit 0; }

# 1) Așteaptă DB-ul (max ~60s) — tolerează race-ul de boot (container Postgres pornește după docker.service)
ready=0
for i in $(seq 1 30); do
  if pq -tAc "SELECT 1" >/dev/null 2>&1; then ready=1; break; fi
  log "aștept DB ($DB_CONTAINER) ($i/30)..."; sleep 2
done
[ "$ready" = "1" ] || { log "EROARE: DB '$DB_CONTAINER' inaccesibil după 60s — opresc (fail-fast)"; exit 1; }

# 2) Tabel de evidență (reutilizăm _release_migrations — folosit deja de orchestratorul de release)
if ! pq -v ON_ERROR_STOP=1 -q -c \
  "CREATE TABLE IF NOT EXISTS _release_migrations (filename text PRIMARY KEY, applied_at timestamptz DEFAULT now());" >/dev/null 2>&1; then
  log "EROARE: nu pot crea/accesa _release_migrations — opresc"; exit 1
fi

# 3) Aplică în ordine cronologică (sort C pe nume); skip ce e deja marcat
applied=0; skipped=0; total=0
while IFS= read -r f; do
  [ -n "$f" ] || continue
  total=$((total+1))
  fn="$(basename "$f")"
  if [ "$(pq -tAc "SELECT 1 FROM _release_migrations WHERE filename='$fn'" 2>/dev/null)" = "1" ]; then
    skipped=$((skipped+1)); continue
  fi
  log "aplic: $fn"
  if sudo docker exec -i "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 -q < "$f"; then
    pq -v ON_ERROR_STOP=1 -q -c "INSERT INTO _release_migrations(filename) VALUES('$fn') ON CONFLICT DO NOTHING;" >/dev/null 2>&1
    applied=$((applied+1))
  else
    log "EROARE la migrarea '$fn' — OPRESC (fail-fast; NU pornesc cod incompatibil cu schema)"
    exit 1
  fi
done < <(ls -1 "$MIG_DIR"/*.sql 2>/dev/null | LC_ALL=C sort)

log "OK — aplicate: $applied, deja prezente: $skipped, total fișiere: $total"
exit 0
