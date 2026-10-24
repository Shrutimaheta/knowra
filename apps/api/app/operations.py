"""Internal operational checks. Produces sanitized state for host monitoring."""

import json
import os
import shutil
import sys
import time
from pathlib import Path

from app.store import db


def status():
    with db() as c:
        jobs = c.execute(
            "SELECT COUNT(*) AS pending,MIN(available) AS oldest FROM ingestion_jobs WHERE status IN ('queued','running')"
        ).fetchone()
        failed = c.execute("SELECT COUNT(*) AS n FROM ingestion_jobs WHERE status='failed'").fetchone()["n"]
    storage = shutil.disk_usage(os.getenv("OPS_DISK_PATH", "/tmp"))
    backlog_age = max(0, int(time.time() - jobs["oldest"])) if jobs["oldest"] else 0
    alerts = []
    if failed:
        alerts.append("failed_ingestion")
    if backlog_age > 900:
        alerts.append("ingestion_backlog")
    if storage.free / storage.total < 0.1:
        alerts.append("low_disk_space")
    backup = os.getenv("BACKUP_SUCCESS_FILE")
    backup_age = None
    if backup:
        try:
            backup_age = int(time.time() - int(Path(backup).read_text().strip()))
            if not 0 <= backup_age <= 93600:
                alerts.append("stale_backup")
        except (OSError, ValueError):
            alerts.append("missing_backup")
    return {
        "status": "attention" if alerts else "ok", "alerts": alerts,
        "pending_jobs": jobs["pending"], "failed_jobs": failed,
        "oldest_job_seconds": backlog_age, "backup_age_seconds": backup_age,
    }


if __name__ == "__main__":
    if "--alert" in sys.argv:
        from app.security import deliver

        recipient = os.getenv("OPS_ALERT_TO", "").strip()
        if not recipient or "@" not in recipient:
            raise SystemExit("OPS_ALERT_TO must be configured before enabling monitoring alerts")
        deliver(recipient, "Knowra deployment needs attention", "A scheduled deployment check failed. Inspect the private host journal and run scripts/check_deployment.py for details. No document content is included in this alert.")
        raise SystemExit(0)
    result = status()
    print(json.dumps(result))
    raise SystemExit(1 if result["alerts"] else 0)
