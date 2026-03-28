"""
email_sender.py
---------------
Sends the RAG-generated notification digest to the configured e-mail address
using Python's built-in smtplib (works with Gmail App Passwords, Outlook, etc.)
"""

from __future__ import annotations

import os
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def send_digest(digest_text: str) -> None:
    """
    Build and dispatch an e-mail containing the notification digest.

    Reads connection details from environment variables:
        SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD,
        EMAIL_FROM, EMAIL_TO
    """
    smtp_host = os.environ["SMTP_HOST"]
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.environ["SMTP_USER"]
    smtp_password = os.environ["SMTP_PASSWORD"]
    email_from = os.getenv("EMAIL_FROM", smtp_user)
    email_to = os.environ["EMAIL_TO"]

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    subject = f"📱 Notification Digest — {now}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = email_from
    msg["To"] = email_to

    # Plain-text part
    text_part = MIMEText(digest_text, "plain", "utf-8")

    # HTML part — simple formatting for readability
    html_body = _to_html(digest_text, now)
    html_part = MIMEText(html_body, "html", "utf-8")

    msg.attach(text_part)
    msg.attach(html_part)

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(email_from, [email_to], msg.as_string())


def _to_html(digest_text: str, timestamp: str) -> str:
    """Convert plain-text digest to a simple HTML e-mail body."""
    lines = digest_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    paragraphs = "".join(
        f"<p>{line}</p>" if line.strip() else "<br/>"
        for line in lines.splitlines()
    )
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8"/>
  <style>
    body {{ font-family: Arial, sans-serif; font-size: 14px; color: #333; max-width: 700px; margin: auto; }}
    h2   {{ color: #2c7be5; }}
    p    {{ line-height: 1.6; }}
  </style>
</head>
<body>
  <h2>📱 Notification Digest</h2>
  <p style="color:#888;font-size:12px;">Generated at {timestamp}</p>
  <hr/>
  {paragraphs}
  <hr/>
  <p style="color:#aaa;font-size:11px;">Sent by PALM Messenger RAG</p>
</body>
</html>"""
