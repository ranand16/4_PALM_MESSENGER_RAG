"""
models.py
---------
This module contains shared data models.

These models define the exact input/output structure used by FastAPI,
which means they are used for:
1) request validation,
2) automatic API documentation generation,
3) consistent typing across the backend.
"""

# Use postponed evaluation of annotations for cleaner forward compatibility.
from __future__ import annotations

# Optional type indicates a field can be either a value or None.
from typing import Optional

# Base class from Pydantic for declarative schema validation.
from pydantic import BaseModel


# Notification is the canonical schema for one forwarded phone notification.
class Notification(BaseModel):
    """Represents one incoming notification sent by the Android app."""

    # The source application name (for example: WhatsApp, Telegram, Signal).
    app: str
    # The contact or group that sent the message (can be absent for some apps).
    sender: Optional[str] = None
    # The text body that appeared inside the phone notification.
    content: str
    # UTC timestamp in ISO-8601 format; server can auto-fill when missing.
    timestamp: Optional[str] = None
