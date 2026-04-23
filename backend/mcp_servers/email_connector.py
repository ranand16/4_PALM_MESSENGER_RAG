"""Connects to a personal e-mail inbox using IMAP and returns new messages."""

from __future__ import annotations

import imaplib
import os
import re
from datetime import datetime, timedelta, timezone
from email import message_from_bytes
from email.header import decode_header
from email.utils import parsedate_to_datetime
from typing import Dict, List, Optional


def _decode_text(value: Optional[bytes]) -> str:
    if not value:
        return ""
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", errors="replace")
        except Exception:
            return value.decode("latin-1", errors="replace")
    return str(value)


def _decode_header_value(value: Optional[str]) -> str:
    if not value:
        return ""
    try:
        parts = decode_header(value)
        decoded = " ".join(
            _decode_text(part[0]) if isinstance(part[0], bytes) else str(part[0])
            for part in parts
        )
        return re.sub(r"\s+", " ", decoded).strip()
    except Exception:
        return value


def _get_message_text(message) -> str:
    lines: List[str] = []
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_maintype() == "multipart":
                continue
            if part.get_content_type() != "text/plain":
                continue
            payload = part.get_payload(decode=True)
            lines.append(_decode_text(payload))
    else:
        payload = message.get_payload(decode=True)
        lines.append(_decode_text(payload))
    return "\n".join(line.strip() for line in lines if line and line.strip())


def _parse_email_timestamp(date_header: Optional[str]) -> str:
    if not date_header:
        return datetime.now(timezone.utc).isoformat()
    try:
        parsed = parsedate_to_datetime(date_header)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    except Exception:
        return datetime.now(timezone.utc).isoformat()


def _message_matches_since(message_date: str, since: datetime) -> bool:
    try:
        parsed = parsedate_to_datetime(message_date)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc) >= since
    except Exception:
        return True


def fetch_new_email_messages(service_config: Dict) -> List[Dict]:
    """Fetch new email messages since the configured window and normalize them."""
    imap_host = service_config["imap_host"]
    email_address = service_config["email_address"]
    password_env = service_config["password_env"]
    mailbox = service_config.get("mailbox", "INBOX")
    fetch_since_days = int(service_config.get("fetch_since_days", 1))

    password = os.getenv(password_env, "")
    if not password:
        raise ValueError(
            f"Email password not found in environment variable: {password_env}"
        )

    since_date = datetime.now(timezone.utc) - timedelta(days=fetch_since_days)
    search_date = since_date.strftime("%d-%b-%Y")

    messages: List[Dict] = []
    with imaplib.IMAP4_SSL(imap_host) as client:
        client.login(email_address, password)
        client.select(mailbox)
        status, data = client.search(None, "SINCE", search_date)
        if status != "OK" or not data or not data[0]:
            return []

        message_ids = data[0].split()
        for uid in message_ids[-200:]:
            status, fetch_data = client.fetch(uid, "(RFC822)")
            if status != "OK" or not fetch_data or not fetch_data[0]:
                continue

            raw_email = fetch_data[0][1]
            if not raw_email:
                continue

            email_message = message_from_bytes(raw_email)
            date_header = email_message.get("Date")
            subject = _decode_header_value(email_message.get("Subject"))
            sender = _decode_header_value(email_message.get("From")) or email_address
            timestamp = _parse_email_timestamp(date_header)
            if not _message_matches_since(date_header or "", since_date):
                continue

            body = _get_message_text(email_message)
            if not body:
                continue

            messages.append(
                {
                    "app": "Email",
                    "sender": sender,
                    "content": f"{subject}\n\n{body}",
                    "timestamp": timestamp,
                    "source_id": uid.decode("utf-8", errors="ignore") if isinstance(uid, bytes) else str(uid),
                    "metadata": {
                        "subject": subject,
                        "mailbox": mailbox,
                        "message_id": email_message.get("Message-ID", ""),
                    },
                }
            )

    return messages
"""
email_connector.py
------------------
This module acts like an MCP server adapter for personal email.

What this does in plain language:
- Connects to your email inbox over IMAP.
- Reads only emails that arrived after the last sync time.
- Converts each email into a simple message shape that the backend can store.
"""

from __future__ import annotations

import email
import imaplib
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from email.header import decode_header
from email.message import Message
from typing import Any, Dict, List, Optional


@dataclass
class EmailFetchResult:
    """Simple container for fetched email items."""

    messages: List[Dict[str, Any]]
    newest_timestamp: Optional[str]


# PURPOSE: Decode encoded email headers like "=?UTF-8?..." into plain text.
def _decode_header_value(value: str) -> str:
    decoded_fragments = decode_header(value or "")
    out: List[str] = []
    for chunk, encoding in decoded_fragments:
        if isinstance(chunk, bytes):
            out.append(chunk.decode(encoding or "utf-8", errors="replace"))
        else:
            out.append(chunk)
    return "".join(out).strip()


# PURPOSE: Pull readable text from email body and ignore complex attachments.
def _extract_body(message: Message) -> str:
    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition", ""))
            if content_type == "text/plain" and "attachment" not in disposition:
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace").strip()
        return ""

    payload = message.get_payload(decode=True) or b""
    charset = message.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace").strip()


# PURPOSE: Convert the email Date header into ISO UTC format used by our DB.
def _to_iso_utc(date_header: str) -> str:
    parsed = email.utils.parsedate_to_datetime(date_header)
    if parsed is None:
        return datetime.now(timezone.utc).isoformat()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


# PURPOSE: Fetch new emails since the supplied checkpoint timestamp.
def fetch_new_emails(service_config: Dict[str, Any], since_timestamp: Optional[str]) -> EmailFetchResult:
    """
    Connect to IMAP and return normalized message dictionaries.

    Required env vars are configured indirectly by names in service_config:
    - username_env -> points to env var that holds your email login
    - password_env -> points to env var that holds your app password
    """
    imap_host = str(service_config.get("imap_host", "imap.gmail.com"))
    imap_port = int(service_config.get("imap_port", 993))
    username_env = str(service_config.get("username_env", "PERSONAL_EMAIL_USERNAME"))
    password_env = str(service_config.get("password_env", "PERSONAL_EMAIL_APP_PASSWORD"))
    folders = service_config.get("folders", ["INBOX"])

    username = os.getenv(username_env, "")
    password = os.getenv(password_env, "")
    if not username or not password:
        raise RuntimeError(
            "Email credentials are missing. Set env vars referenced by "
            f"{username_env} and {password_env}."
        )

    messages: List[Dict[str, Any]] = []
    newest_timestamp = since_timestamp

    with imaplib.IMAP4_SSL(imap_host, imap_port) as mailbox:
        mailbox.login(username, password)

        for folder in folders:
            mailbox.select(folder)

            # IMAP SINCE is day-granular, so we use date and apply precise filtering in Python.
            if since_timestamp:
                since_dt = datetime.fromisoformat(since_timestamp.replace("Z", "+00:00"))
                since_filter = since_dt.strftime("%d-%b-%Y")
                status, data = mailbox.search(None, f'(SINCE "{since_filter}")')
            else:
                status, data = mailbox.search(None, "ALL")

            if status != "OK":
                continue

            for uid in data[0].split():
                fetch_status, raw_parts = mailbox.fetch(uid, "(RFC822)")
                if fetch_status != "OK" or not raw_parts or raw_parts[0] is None:
                    continue

                raw_email = raw_parts[0][1]
                parsed = email.message_from_bytes(raw_email)

                date_header = parsed.get("Date", "")
                timestamp = _to_iso_utc(date_header)
                if since_timestamp:
                    since_dt = datetime.fromisoformat(since_timestamp.replace("Z", "+00:00"))
                    current_dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    if current_dt <= since_dt:
                        continue

                sender = _decode_header_value(parsed.get("From", "Unknown sender"))
                subject = _decode_header_value(parsed.get("Subject", "(No subject)"))
                body = _extract_body(parsed)
                content = f"Subject: {subject}\n\n{body}".strip()

                messages.append(
                    {
                        "app": "email",
                        "sender": sender,
                        "content": content,
                        "timestamp": timestamp,
                        "source_id": uid.decode("utf-8", errors="replace"),
                        "metadata": {
                            "folder": folder,
                            "subject": subject,
                            "service": "personal_email",
                        },
                    }
                )

                if newest_timestamp is None or timestamp > newest_timestamp:
                    newest_timestamp = timestamp

    return EmailFetchResult(messages=messages, newest_timestamp=newest_timestamp)
