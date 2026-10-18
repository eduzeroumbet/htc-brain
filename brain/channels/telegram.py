"""Telegram Bot API — canal principal para Rússia/CIS."""
from __future__ import annotations

from typing import Any

import httpx
import structlog

from brain.core import bus
from brain.core.retry import http_failure
from brain.settings import get_settings

log = structlog.get_logger(__name__)


def api(method: str) -> str:
    return f"https://api.telegram.org/bot{get_settings().telegram_bot_token}/{method}"


async def handle_webhook(payload: dict[str, Any]) -> int:
    msg = payload.get("message") or payload.get("edited_message")
    if not msg:
        return 0
    chat = msg["chat"]
    frm = msg.get("from", {})
    text = msg.get("text") or msg.get("caption") or ""
    media = None
    for key in ("photo", "document", "voice", "video"):
        if msg.get(key):
            media = msg[key][-1]["file_id"] if isinstance(msg[key], list) else msg[key]["file_id"]
            text = text or f"[{key}]"
    name = " ".join(x for x in [frm.get("first_name"), frm.get("last_name")] if x) or frm.get("username")
    await bus.publish(bus.INBOUND, {
        "channel": "telegram", "channel_user_id": str(chat["id"]), "display_name": name, "text": text,
        "media_url": media, "message_id": str(msg.get("message_id")), "market_code": "RU" if (frm.get("language_code") or "").startswith(("ru", "kk")) else None,
    })
    return 1


async def send(event: dict[str, Any]) -> None:
    async with httpx.AsyncClient(timeout=20) as c:
        if event.get("document_url"):
            r = await c.post(api("sendDocument"), json={"chat_id": event["channel_user_id"], "document": event["document_url"], "caption": event.get("text", "")[:1000]})
        else:
            r = await c.post(api("sendMessage"), json={"chat_id": event["channel_user_id"], "text": event["text"][:4096], "disable_web_page_preview": False})
        if r.status_code >= 400:
            log.error("tg_send_failed", status=r.status_code, body=r.text[:400])
            raise http_failure("telegram", r.status_code, r.headers.get("Retry-After"))  # 5xx/429 → retry; 4xx → DLQ
