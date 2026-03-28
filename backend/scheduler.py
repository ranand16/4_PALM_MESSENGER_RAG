"""
scheduler.py
------------
Uses APScheduler to periodically run the RAG digest pipeline and e-mail the
result. The schedule is configured via environment variables.
"""

from __future__ import annotations

import logging
import os

from apscheduler.schedulers.background import BackgroundScheduler

from email_sender import send_digest
from notification_store import clear_notifications
from rag_engine import build_digest

logger = logging.getLogger(__name__)


def _run_digest_job() -> None:
    """Build a digest, e-mail it, then clear the notification store."""
    logger.info("Digest job started.")
    try:
        digest = build_digest()
        send_digest(digest)
        clear_notifications()
        logger.info("Digest sent and notification store cleared.")
    except Exception:
        logger.exception("Digest job failed.")


def create_scheduler() -> BackgroundScheduler:
    """
    Create and return a BackgroundScheduler configured from env vars.

    DIGEST_CRON_HOUR   – cron hour expression  (default: "*/1" = every hour)
    DIGEST_CRON_MINUTE – cron minute expression (default: "0")
    """
    scheduler = BackgroundScheduler()
    hour = os.getenv("DIGEST_CRON_HOUR", "*/1")
    minute = os.getenv("DIGEST_CRON_MINUTE", "0")

    scheduler.add_job(
        _run_digest_job,
        trigger="cron",
        hour=hour,
        minute=minute,
        id="digest_job",
        replace_existing=True,
    )
    return scheduler
