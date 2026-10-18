"""E-mail: polling IMAP a cada 60s (scheduler) + envio SMTP. Usado para propostas, vouchers e mercados que preferem e-mail (GB, DE, US)."""
from __future__ import annotations

import email as email_lib
from email.header import decode_header
from email.message import EmailMessage
from typing import Any

import structlog

from brain.core import bus
from brain.settings import get_settings

log = structlog.get_logger(__name__)


def _decode(v: str | None) -> str:
    if not v:
        return ""
    parts = decode_header(v)
    return "".join(p.decode(enc or "utf-8", errors="ignore") if isinstance(p, bytes) else p for p, enc in parts)


async def poll() -> int:
    s = get_settings()
    if not (s.imap_host and s.imap_user and s.imap_password):
        return 0
    from aioimaplib import aioimaplib  # type: ignore

    client = aioimaplib.IMAP4_SSL(host=s.imap_host)
    await client.wait_hello_from_server()
    await client.login(s.imap_user, s.imap_password)
    await client.select("INBOX")
    _, data = await client.search("UNSEEN")
    n = 0
    for uid in (data[0].split() if data and data[0] else []):
        _, fetched = await client.fetch(uid.decode(), "(RFC822)")
        raw = next((p for p in fetched if isinstance(p, (bytes, bytearray)) and len(p) > 100), None)
        if not raw:
            continue
        msg = email_lib.message_from_bytes(raw)
        sender = email_lib.utils.parseaddr(msg.get("From", ""))
        body = ""
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                body += part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="ignore")
        await bus.publish(bus.INBOUND, {
            "channel": "email", "channel_user_id": sender[1].lower(), "display_name": _decode(sender[0]), "email": sender[1].lower(),
            "text": f"Assunto: {_decode(msg.get('Subject'))}\n\n{body.strip()[:6000]}", "message_id": msg.get("Message-ID"),
        })
        await client.store(uid.decode(), "+FLAGS", "\\Seen")
        n += 1
    await client.logout()
    return n


async def send(event: dict[str, Any]) -> None:
    s = get_settings()
    import aiosmtplib

    msg = EmailMessage()
    msg["From"] = s.smtp_from or s.smtp_user
    msg["To"] = event["channel_user_id"]
    msg["Subject"] = event.get("subject") or "Sua viagem a Dubai"
    if event.get("reply_to"):
        msg["In-Reply-To"] = event["reply_to"]
        msg["References"] = event["reply_to"]
    text = event["text"]
    if event.get("document_url"):
        text += f"\n\nCotação em PDF: {event['document_url']}"
    msg.set_content(text)
    await aiosmtplib.send(msg, hostname=s.smtp_host, port=s.smtp_port, username=s.smtp_user, password=s.smtp_password, start_tls=True)
