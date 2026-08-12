"""Maintenance hooks fired by the existing 5-min cron (via /process/run-now).

Both scripts self-gate, so invoking them every tick is cheap:
  - backup_code.sh --auto : creates a backup only if >=55min passed AND code changed.
  - cleanup_backups.sh    : actually deletes at most once per day.
Fire-and-forget, fully detached; never affects email processing.
"""
import logging
import subprocess

logger = logging.getLogger("mailguard.maintenance")

APP_DIR = "/opt/iris-mailguard"
SCRIPTS = f"{APP_DIR}/scripts"


def _spawn(args):
    subprocess.Popen(
        args,
        cwd=APP_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,   # detach: survives gunicorn worker recycling
        close_fds=True,
    )


def fire_maintenance():
    """Trigger conditional backup + daily cleanup. Best-effort."""
    try:
        _spawn([f"{SCRIPTS}/backup_code.sh", "--auto"])
        _spawn([f"{SCRIPTS}/cleanup_backups.sh"])
    except Exception as e:  # pragma: no cover - never break the caller
        logger.warning(f"fire_maintenance failed: {e}")
