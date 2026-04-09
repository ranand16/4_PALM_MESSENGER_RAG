"""
scheduler.py
------------
Uses APScheduler to periodically run the RAG digest pipeline and e-mail the
result. The schedule is configured via environment variables.
"""

# [PYTHON] This future import postpones annotation evaluation, helping avoid some import-time type-hint issues.
from __future__ import annotations

# [PYTHON] `logging` is Python's standard library module for structured runtime logs.
import logging
# [PYTHON] `os` is used here to read environment variables for schedule configuration.
import os

# [FUNCTIONALITY] APScheduler background scheduler runs jobs in-process without blocking the main thread.
from apscheduler.schedulers.background import BackgroundScheduler

# [FUNCTIONALITY] Function to send the final digest via SMTP.
from email_sender import send_digest
# [FUNCTIONALITY] Function to clear stored notifications after successful digest delivery.
from notification_store import clear_notifications
# [FUNCTIONALITY] Function that runs RAG map-reduce pipeline and returns digest text.
from rag_engine import build_digest

# [PYTHON] `__name__` contains module name; using it ties log records to this file's logger namespace.
logger = logging.getLogger(__name__)


def _run_digest_job() -> None:
    # [PYTHON] Private helper (leading underscore) indicates internal use inside this module.
    """Build a digest, e-mail it, then clear the notification store."""
    # [FUNCTIONALITY] Log start marker so operators can trace scheduled execution in logs.
    logger.info("Digest job started.")
    # [PYTHON] `try/except` captures runtime errors to prevent scheduler crash from one failing run.
    try:
        # [FUNCTIONALITY] Build digest text from currently stored notifications.
        digest = build_digest()
        # [FUNCTIONALITY] Send generated digest to configured recipient.
        send_digest(digest)
        # [FUNCTIONALITY] Clear datastore only after successful e-mail send to avoid data loss on failure.
        clear_notifications()
        # [FUNCTIONALITY] Log successful completion for monitoring and debugging.
        logger.info("Digest sent and notification store cleared.")
    # [PYTHON] Broad exception catches all error types; acceptable in scheduler jobs when paired with logging.
    except Exception:
        # [FUNCTIONALITY] `logger.exception` logs stack trace automatically, which is critical for diagnosing failures.
        logger.exception("Digest job failed.")


def create_scheduler() -> BackgroundScheduler:
    # [PYTHON] Public factory function returns a configured `BackgroundScheduler` instance.
    """
    Create and return a BackgroundScheduler configured from env vars.

    DIGEST_CRON_HOUR   – cron hour expression  (default: "*/1" = every hour)
    DIGEST_CRON_MINUTE – cron minute expression (default: "0")
    """
    # [FUNCTIONALITY] Create scheduler object; caller is responsible for starting it via `scheduler.start()`.
    scheduler = BackgroundScheduler()
    # [PYTHON] `os.getenv` returns env var value or fallback; here default `*/1` means "every hour" in cron syntax.
    hour = os.getenv("DIGEST_CRON_HOUR", "*/1")
    # [PYTHON] Default minute `0` means run at the top of each selected hour.
    minute = os.getenv("DIGEST_CRON_MINUTE", "0")

    # [FUNCTIONALITY] Register digest job with cron trigger so APScheduler computes recurring run times.
    scheduler.add_job(
        # [FUNCTIONALITY] Callable APScheduler executes each time trigger fires.
        _run_digest_job,
        # [PYTHON] Keyword argument names make call self-documenting and reduce positional-order mistakes.
        trigger="cron",
        # [FUNCTIONALITY] Hour cron field from environment.
        hour=hour,
        # [FUNCTIONALITY] Minute cron field from environment.
        minute=minute,
        # [FUNCTIONALITY] Stable job id allows replacement on restart or config reload.
        id="digest_job",
        # [FUNCTIONALITY] Replace existing job with same id instead of raising conflict errors.
        replace_existing=True,
    )
    # [FUNCTIONALITY] Return configured scheduler to application bootstrap code.
    return scheduler
