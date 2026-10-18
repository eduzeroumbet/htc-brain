"""Messenger e Instagram DM (Meta Graph API) — mesmo webhook, dois canais."""
from __future__ import annotations

import hashlib
import hmac
from typing import Any

import httpx
import structlog

from brain.core import bus
from brain.core.retry import http_failure
from brain.settings import get_settings

log = structlog.get_logger(__name__)
GRAPH = "https://graph.facebook.com/v21.0"


def verify_signature(body: bytes, signature_header: str | None) -> bool:
    secret = get_settings().meta_app_secret
    if not secret:
        return True
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, signature_header.split("=", 1)[1])


async def handle_webhook(payload: dict[str, Any]) -> int:
    n = 0
    obj = payload.get("object")  # "page" (Messenger) ou "instagram"
    channel = "instagram" if obj == "instagram" else "messenger"
    for entry in payload.get("entry", []):
        # "standby": a página tem outro app como receptor primário (ex.: Caixa de Entrada do Business Suite) — tratamos igual.
        for ev in [*entry.get("messaging", []), *entry.get("standby", [])]:
            msg = ev.get("message")
            if not msg or msg.get("is_echo"):
                if ev.get("referral"):
                    log.info("meta_referral", sender=ev.get("sender", {}).get("id"), referral=ev["referral"])
                continue
            text = msg.get("text", "")
            media = None
            for att in msg.get("attachments", []) or []:
                media = (att.get("payload") or {}).get("url")
                text = text or f"[{att.get('type')}]"
            await bus.publish(bus.INBOUND, {
                "channel": channel, "channel_user_id": ev["sender"]["id"], "text": text, "media_url": media,
                "message_id": msg.get("mid"),
            })
            n += 1
    if n == 0:
        import json as _json
        log.warning("meta_webhook_unhandled", payload=_json.dumps(payload)[:1500])
    return n


async def _send(recipient_id: str, text: str, platform: str) -> None:
    s = get_settings()
    url = f"{GRAPH}/{s.meta_page_id}/messages" if platform == "messenger" else f"{GRAPH}/{s.meta_ig_account_id}/messages"
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(url, params={"access_token": s.meta_page_access_token},
                         json={"recipient": {"id": recipient_id}, "message": {"text": text[:2000]}, "messaging_type": "RESPONSE"})
        if r.status_code >= 400:
            log.error("meta_send_failed", platform=platform, status=r.status_code, body=r.text[:400])
            raise http_failure(platform, r.status_code, r.headers.get("Retry-After"))  # 5xx/429 → retry; 4xx → DLQ


async def send_messenger(event: dict[str, Any]) -> None:
    await _send(event["channel_user_id"], event["text"], "messenger")


async def send_instagram(event: dict[str, Any]) -> None:
    await _send(event["channel_user_id"], event["text"], "instagram")
