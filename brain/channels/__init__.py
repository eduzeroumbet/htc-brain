"""Adaptadores de canal. Cada um normaliza o inbound para o evento padrão e sabe enviar o outbound.

Evento inbound padrão (publicado em bus.INBOUND):
{
  "channel": "whatsapp|instagram|messenger|telegram|email|webchat",
  "channel_user_id": "...", "display_name": "...", "phone": "...", "email": "...",
  "text": "...", "media_url": "...", "message_id": "...", "market_code": "BR" (opcional, ex.: webchat por idioma do site)
}
"""
from __future__ import annotations

from typing import Any

from brain.channels import email as email_ch
from brain.channels import meta_dm, telegram, webchat, whatsapp

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
    await sender(event)
