"""Adaptadores de canal. Cada um normaliza o inbound para o evento padrão e sabe enviar o outbound.

Evento inbound padrão (publicado em bus.INBOUND):
{
  "channel": "whatsapp|instagram|messenger|telegram|email|webchat",
  "channel_user_id": "...", "display_name": "...", "phone": "...", "email": "...",
  "text": "...", "media_url": "...", "message_id": "...", "market_code": "BR" (opcional, ex.: webchat por idioma do site)
}

Evento outbound: "purpose": "marketing" para follow-up, campanha e template promocional (exige "lead_id");
sem "purpose" = transacional. Marketing só sai se consent.pode_enviar_marketing(lead, canal).
"""
from __future__ import annotations

from typing import Any

import structlog

from brain.channels import email as email_ch
from brain.channels import meta_dm, telegram, webchat, whatsapp
from brain.core import consent

log = structlog.get_logger(__name__)

SENDERS = {
    "whatsapp": whatsapp.send,
    "instagram": meta_dm.send_instagram,
    "messenger": meta_dm.send_messenger,
    "telegram": telegram.send,
    "email": email_ch.send,
    "webchat": webchat.send,
}


async def dispatch(event: dict[str, Any]) -> None:
    sender = SENDERS.get(event["channel"])
    if not sender:
        raise ValueError(f"canal sem sender: {event['channel']}")
    if event.get("purpose") == "marketing" and not await consent.pode_enviar_marketing(event.get("lead_id"), event["channel"]):
        log.warning("marketing_blocked", lead_id=event.get("lead_id"), channel=event["channel"], author=event.get("author"),
                    template=bool(event.get("template")), reason="sem consentimento de marketing ativo")
        return
    await sender(event)
