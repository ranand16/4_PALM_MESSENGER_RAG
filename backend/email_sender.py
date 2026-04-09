"""
email_sender.py
---------------
Sends the RAG-generated notification digest to the configured e-mail address
using Python's built-in smtplib (works with Gmail App Passwords, Outlook, etc.)
"""

# [PYTHON] This future import postpones evaluation of type annotations, which can reduce import-time issues in some projects.
from __future__ import annotations

# [PYTHON] `os` lets us read environment variables, which are common for secrets and runtime config.
import os
# [PYTHON] `smtplib` is Python's standard library module for SMTP e-mail sending.
import smtplib
# [PYTHON] `datetime` provides date/time objects; `timezone.utc` gives an explicit UTC timezone marker.
from datetime import datetime, timezone
# [PYTHON] `MIMEMultipart` builds a multi-part MIME e-mail (for example plain text + HTML in one message).
from email.mime.multipart import MIMEMultipart
# [PYTHON] `MIMEText` creates text MIME parts with content type and character encoding.
from email.mime.text import MIMEText


def send_digest(digest_text: str) -> None:
  # [PYTHON] Function type hints: input is a string and return type is `None` (procedure-style function).
    """
    Build and dispatch an e-mail containing the notification digest.

    Reads connection details from environment variables:
        SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD,
        EMAIL_FROM, EMAIL_TO
    """
  # [FUNCTIONALITY] Required SMTP server hostname (for example smtp.gmail.com); raises KeyError if missing.
    smtp_host = os.environ["SMTP_HOST"]
  # [PYTHON] `os.getenv` returns a string or default; `int(...)` converts port text (like "587") into numeric port.
  # [FUNCTIONALITY] SMTP port defaults to 587, the common STARTTLS submission port.
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
  # [FUNCTIONALITY] SMTP username used for authentication; expected to be set in environment.
    smtp_user = os.environ["SMTP_USER"]
  # [FUNCTIONALITY] SMTP password or app password used for login.
    smtp_password = os.environ["SMTP_PASSWORD"]
  # [PYTHON] `os.getenv(key, default)` uses fallback value when key is absent.
  # [FUNCTIONALITY] Sender address defaults to SMTP user if EMAIL_FROM is not explicitly configured.
    email_from = os.getenv("EMAIL_FROM", smtp_user)
  # [FUNCTIONALITY] Destination address where digest is delivered.
    email_to = os.environ["EMAIL_TO"]

  # [PYTHON] `datetime.now(timezone.utc)` creates timezone-aware current time; `strftime` formats it into human-readable text.
  # [FUNCTIONALITY] Timestamp is included in subject/body so recipient knows when digest was generated.
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
  # [PYTHON] f-string injects the `now` value into subject text.
  # [FUNCTIONALITY] Subject line makes the e-mail easily identifiable in inbox search.
    subject = f"📱 Notification Digest — {now}"

  # [PYTHON] `alternative` means recipients can choose best-supported part (typically HTML, fallback to plain text).
    msg = MIMEMultipart("alternative")
  # [PYTHON] MIME headers are set using dictionary-like syntax.
    msg["Subject"] = subject
  # [FUNCTIONALITY] RFC e-mail From header shown to recipients.
    msg["From"] = email_from
  # [FUNCTIONALITY] RFC e-mail To header shown to recipients.
    msg["To"] = email_to

  # [FUNCTIONALITY] Create plain-text MIME part so even text-only mail clients can read the digest.
  # [PYTHON] Third parameter `utf-8` ensures Unicode text (including emoji) is encoded safely.
    text_part = MIMEText(digest_text, "plain", "utf-8")

  # [FUNCTIONALITY] Convert plain digest to minimal HTML for richer formatting in modern e-mail clients.
    html_body = _to_html(digest_text, now)
  # [PYTHON] Second MIME part is typed as HTML so mail clients render tags instead of showing raw markup.
    html_part = MIMEText(html_body, "html", "utf-8")

  # [PYTHON] Attach order in multipart/alternative is typically plain first, HTML second.
    msg.attach(text_part)
  # [FUNCTIONALITY] HTML version is attached after plain text as the richer representation.
    msg.attach(html_part)

  # [PYTHON] Context manager (`with ... as ...`) guarantees socket cleanup even if an exception occurs.
    with smtplib.SMTP(smtp_host, smtp_port) as server:
    # [FUNCTIONALITY] `ehlo` introduces this client and requests server capabilities.
        server.ehlo()
    # [FUNCTIONALITY] Upgrade connection to TLS encryption to protect credentials in transit.
        server.starttls()
    # [FUNCTIONALITY] Authenticate to SMTP server before attempting to send.
        server.login(smtp_user, smtp_password)
    # [PYTHON] `msg.as_string()` serializes MIME object to raw RFC 5322 message text.
    # [FUNCTIONALITY] Send one e-mail from sender to a recipient list containing one address.
        server.sendmail(email_from, [email_to], msg.as_string())


def _to_html(digest_text: str, timestamp: str) -> str:
  # [PYTHON] Helper function converts plain text to HTML string; returns `str`.
    """Convert plain-text digest to a simple HTML e-mail body."""
  # [FUNCTIONALITY] Escape `&`, `<`, and `>` so user text is shown literally and cannot break HTML structure.
    lines = digest_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
  # [PYTHON] Generator expression iterates over each input line and produces either `<p>...</p>` or `<br/>`.
  # [FUNCTIONALITY] Preserve paragraph-like readability and blank lines from the original digest text.
    paragraphs = "".join(
        f"<p>{line}</p>" if line.strip() else "<br/>"
        for line in lines.splitlines()
    )
  # [PYTHON] Triple-quoted f-string embeds both `timestamp` and prebuilt `paragraphs` into one HTML document string.
  # [FUNCTIONALITY] Return complete HTML email body with simple inline styling for broad client compatibility.
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
