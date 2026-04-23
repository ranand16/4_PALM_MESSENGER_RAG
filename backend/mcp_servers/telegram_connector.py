"""Connects to Telegram through pyrogram and returns recent messages."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from pyrogram import Client
from pyrogram.enums import ChatType


def _normalize_message_text(message) -> str:
    if message.text:
        return message.text
    if message.caption:
        return message.caption
    return ""


def _message_timestamp(message) -> str:
    ts = message.date
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).isoformat()


def _sender_name(message, chat_title: str) -> str:
    if message.from_user:
        name_parts = [message.from_user.first_name or "", message.from_user.last_name or ""]
        return " ".join(part for part in name_parts if part).strip() or chat_title
    return chat_title


def fetch_new_telegram_messages(service_config: Dict) -> List[Dict]:
    """Fetch recent Telegram messages from personal chats using pyrogram."""
    api_id = int(service_config["api_id"])
    api_hash = service_config["api_hash"]
    session_file = service_config["session_file"]
    chat_filter = service_config.get("chat_filter", "personal")
    fetch_since_seconds = int(service_config.get("fetch_since_seconds", 86400))

    since_dt = datetime.now(timezone.utc) - timedelta(seconds=fetch_since_seconds)
    messages: List[Dict] = []

    with Client(session_name=session_file, api_id=api_id, api_hash=api_hash) as client:
        for dialog in client.get_dialogs():
            chat = dialog.chat
            if chat_filter == "personal" and chat.type != ChatType.PRIVATE:
                continue

            chat_title = chat.title or "Telegram"
            for message in client.get_history(chat.id, limit=200):
                if not _normalize_message_text(message):
                    continue

                message_time = message.date
                if message_time.tzinfo is None:
                    message_time = message_time.replace(tzinfo=timezone.utc)
                if message_time.astimezone(timezone.utc) < since_dt:
                    break

                messages.append(
                    {
                        "app": "Telegram",
                        "sender": _sender_name(message, chat_title),
                        "content": _normalize_message_text(message),
                        "timestamp": _message_timestamp(message),
                        "source_id": str(message.message_id),
                        "metadata": {
                            "chat_title": chat_title,
                            "chat_type": chat.type.value,
                            "dialog_id": str(chat.id),
                        },
                    }
                )

    return messages
"""
telegram_connector.py
---------------------
This module acts like an MCP server adapter for Telegram.

Plain-language behavior:
- Uses your personal Telegram API credentials.
- Reads personal chat messages newer than the last sync.
- Returns normalized items for storage in the backend database.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from typing import Any, Dict, List, Optional


@dataclass
class TelegramFetchResult:
    """Container for Telegram fetch output."""

    messages: List[Dict[str, Any]]
    newest_timestamp: Optional[str]


# PURPOSE: Read only new Telegram personal messages after since_timestamp.
def fetch_new_telegram_messages(service_config: Dict[str, Any], since_timestamp: Optional[str]) -> TelegramFetchResult:
    """
    Use pyrogram Client to access personal Telegram history.

    NOTE:
    - The first run may require an interactive Telegram login flow.
    - We intentionally keep this function simple and focused on personal chats.
    """
    try:
        from pyrogram import Client
    except ImportError as exc:
        raise RuntimeError(
            "pyrogram is required for Telegram integration. Install dependencies first."
        ) from exc

    api_id_env = str(service_config.get("api_id_env", "TELEGRAM_API_ID"))
    api_hash_env = str(service_config.get("api_hash_env", "TELEGRAM_API_HASH"))
    session_name = str(service_config.get("session_name", "palm_telegram_session"))
    max_messages_per_chat = int(service_config.get("max_messages_per_chat", 20))

    api_id = os.getenv(api_id_env, "")
    api_hash = os.getenv(api_hash_env, "")
    if not api_id or not api_hash:
        raise RuntimeError(
            "Telegram API credentials are missing. Set env vars referenced by "
            f"{api_id_env} and {api_hash_env}."
        )

    messages: List[Dict[str, Any]] = []
    newest_timestamp = since_timestamp
    since_dt: Optional[datetime] = None
    if since_timestamp:
        since_dt = datetime.fromisoformat(since_timestamp.replace("Z", "+00:00"))

    with Client(session_name=session_name, api_id=int(api_id), api_hash=api_hash) as tg:
        for dialog in tg.get_dialogs():
            chat = dialog.chat
            # Personal chats in Telegram are private chats.
            if getattr(chat, "type", None) != "private":
                continue

            history = tg.get_chat_history(chat.id, limit=max_messages_per_chat)
            for message in history:
                if not getattr(message, "text", None):
                    continue

                timestamp = message.date.astimezone(timezone.utc).isoformat()
                msg_dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                if since_dt and msg_dt <= since_dt:
                    continue

                sender_name = "Unknown sender"
                if getattr(message, "from_user", None):
                    first = message.from_user.first_name or ""
                    last = message.from_user.last_name or ""
                    sender_name = f"{first} {last}".strip() or sender_name

                messages.append(
                    {
                        "app": "telegram",
                        "sender": sender_name,
                        "content": message.text,
                        "timestamp": timestamp,
                        "source_id": str(message.id),
                        "metadata": {
                            "chat_id": str(chat.id),
                            "chat_title": getattr(chat, "title", None) or sender_name,
                            "service": "personal_telegram",
                        },
                    }
                )

                if newest_timestamp is None or timestamp > newest_timestamp:
                    newest_timestamp = timestamp

    return TelegramFetchResult(messages=messages, newest_timestamp=newest_timestamp)
