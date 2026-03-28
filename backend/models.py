"""
models.py
---------
Pydantic models shared across the backend.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class Notification(BaseModel):
    """A single notification received from the Android app."""

    app: str  # e.g. "WhatsApp", "Telegram"
    sender: Optional[str] = None  # contact name / group name
    content: str  # notification body text
    timestamp: Optional[str] = None  # ISO-8601; auto-filled if omitted
