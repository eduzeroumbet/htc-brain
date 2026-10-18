"""Adaptadores de canal. Cada um normaliza o inbound para o evento padrão e sabe enviar o outbound.

Evento inbound padrão (publicado em bus.INBOUND):
{
  "channel": "whatsapp|instagram|messenger|telegram|email|webchat",
  "channel_user_id": "...", "display_name": "...", "phone": "...", "email": "...",
  "text": "...", "media_url": "...", "message_id": "...", "market_code": "BR" (opcional, ex.: webchat por idioma do site)
}

Evento outbound: "purpose": "marketing" para follow-up, campanha e template promocional (exige "lead_id");
"session_reply" para resposta de atendimento (livre só dentro da janela aberta pelo cliente); "transactional" ou sem "purpose"
= transacional (config/consent.yaml: unclassified_purpose). O gate é consent.motivo_bloqueio(event) (RG-CONSENT-001).
"""
from __future__ import annotations

from typing import Any

import structlog

from brain.channels import email as email_ch
from brain.channels import delivery_failures, meta_dm, telegram, webchat, whatsapp
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
    motivo = await consent.motivo_bloqueio(event)
    if motivo:  # registro só com ids e motivo; nada de telefone, e-mail ou texto da mensagem
        log.warning("marketing_blocked", lead_id=event.get("lead_id"), channel=event["channel"], author=event.get("author"),
                    purpose=event.get("purpose") or "unclassified", template=bool(event.get("template")), reason=motivo)
        return
    if event["channel"] == "whatsapp" and delivery_failures.br_paused(event):
        # Brasil pausado (WA_BR_DELIVERY_ENABLED=false): não chama a Graph API; registra e oferece outro canal
        await delivery_failures.handle_permanent_failure(
            category=delivery_failures.CAT_BR_PAUSED, source="guard", to=event["channel_user_id"],
            ref=delivery_failures.outbound_ref(event), lead_id=event.get("lead_id"))
        return
    await sender(event)
