#!/bin/bash
# Instalare cron lunar pentru snapshot satisfacție clienți.
# Rulează pe mailguard-staging ca root (sau user cu crontab access).
# Utilizare: sudo bash /opt/iris-mailguard/scripts/satisfaction_cron_install.sh

CRON_FILE="/etc/cron.d/cargo360-satisfaction"
LOG_DIR="/opt/iris-mailguard/storage/logs"
PYTHON="/opt/iris-mailguard/venv/bin/python3"
SCRIPT="/opt/iris-mailguard/scripts/satisfaction_monthly.py"

mkdir -p "$LOG_DIR"

cat > "$CRON_FILE" << 'CRONEOF'
# Snapshot lunar satisfactie clienti — rulează la 03:00 in ziua 1 a fiecarei luni
0 3 1 * * root /opt/iris-mailguard/venv/bin/python3 /opt/iris-mailguard/scripts/satisfaction_monthly.py >> /opt/iris-mailguard/storage/logs/satisfaction_monthly.log 2>&1
CRONEOF

chmod 644 "$CRON_FILE"
echo "Cron instalat in $CRON_FILE"
cat "$CRON_FILE"
