"""Huda — a consultora de WhatsApp que já atende em 7 idiomas (site highclass.you, Manus WebDev + Evolution API).

A Huda continua sendo a voz do primeiro contato. O cérebro NÃO responde a esses clientes; ele recebe da Huda, por webhook,
o perfil do lead e os eventos de handoff, para:
  • medir os experimentos de mídia (lead × mercado × campanha → CPL, qualidade pelo Jev, lead→cotação);
  • acionar o Operacional quando a Huda transfere para humano (pagamento, reembolso, cancelamento, emergência, "quero falar com alguém");
  • manter um único CRM (leads) para Financeiro, Auditor e CEO.

Contrato (o lado Manus faz POST em /webhooks/huda com header X-Huda-Token = HUDA_WEBHOOK_SECRET):
{
  "event": "lead_updated" | "handoff" | "message",     # message é opcional (só métrica/auditoria)
  "phone": "5511999998888",                            # sem '+', como vem do WhatsApp
  "name": "...", "email": "...", "language": "pt",      # opcionais
  "residence_country": "BR" | "Brasil" | "India" ...,  # opcional — define o mercado
  "destination": "...", "party_size": 2, "trip_purpose": "...", "preferences": "...",
  "travel_dates_text": "...", "travel_start": "2026-12-20", "travel_end": "2026-12-27",
  "stage": "discovery" | "qualification" | "ready_for_human",
  "summary": "...",                                    # resumo interno da Huda (até 1200 chars)
  "referral": {"source_id": "...", "ad_id": "...", "headline": "...", "ctwa_clid": "..."},   # Click-to-WhatsApp (se a Evolution entregar)
  "utm": {...}
}
"""
from __future__ import annotations

import secrets
from typing import Any

import structlog

from brain.core import bus, db, jev
from brain.settings import get_settings

log = structlog.get_logger(__name__)

COUNTRY_TO_MARKET = {
    "br": "BR", "brasil": "BR", "brazil": "BR", "pt": "BR",
    "in": "IN", "india": "IN", "índia": "IN", "hi": "IN",
    "ru": "RU", "russia": "RU", "rússia": "RU", "россия": "RU", "kz": "RU", "kazakhstan": "RU",
    "gb": "GB", "uk": "GB", "united kingdom": "GB", "england": "GB", "reino unido": "GB",
    "de": "DE", "germany": "DE", "deutschland": "DE", "alemanha": "DE", "at": "DE", "ch": "DE",
    "sa": "SA", "saudi arabia": "SA", "ksa": "SA", "السعودية": "SA", "ar": "SA", "kw": "SA", "qa": "SA", "ae": "SA",
    "us": "US", "usa": "US", "united states": "US", "estados unidos": "US",
}
LANG_TO_MARKET = {"pt": "BR", "pt-br": "BR", "hi": "IN", "ru": "RU", "de": "DE", "ar": "SA", "en": "GB"}


def verify(token: str | None) -> bool:
    secret = get_settings().huda_webhook_secret
    return bool(secret) and bool(token) and secrets.compare_digest(token or "", secret)


def market_for(payload: dict[str, Any]) -> str | None:
    country = (payload.get("residence_country") or "").strip().lower()
    if country in COUNTRY_TO_MARKET:
        return COUNTRY_TO_MARKET[country]
    lang = (payload.get("language") or "").strip().lower()
    return LANG_TO_MARKET.get(lang) or LANG_TO_MARKET.get(lang.split("-")[0])


def _dates(payload: dict[str, Any]) -> str | None:
    s, e = payload.get("travel_start"), payload.get("travel_end")
    if s:
        return f"[{s},{e or s}]"
    return None


async def handle(payload: dict[str, Any]) -> dict[str, Any]:
    phone = str(payload.get("phone") or "").lstrip("+").strip()
    if not phone:
        return {"ok": False, "error": "phone obrigatório"}
    event = payload.get("event") or "lead_updated"
    referral = payload.get("referral") or {}
    stage_map = {"discovery": "qualifying", "qualification": "qualifying", "ready_for_human": "qualified"}
    fields: dict[str, Any] = {
        "market_code": market_for(payload),
        "display_name": payload.get("name"),
        "phone": phone,
        "email": payload.get("email"),
        "language": payload.get("language"),
        "stage": stage_map.get(payload.get("stage") or "", None),
        "source_campaign": referral.get("ad_id") or referral.get("source_id") or payload.get("source_campaign"),
        "utm": {**(payload.get("utm") or {}), **({"ctwa": referral} if referral else {}), "attended_by": "huda"} or None,
        "pax_adults": payload.get("party_size"),
        "occasion": payload.get("trip_purpose"),
        "notes": payload.get("summary"),
        "opt_in_whatsapp": True,
    }
    lead = await db.upsert_lead("whatsapp", phone, **fields)
    if _dates(payload):
        await db.execute("UPDATE leads SET travel_dates = $2::text::daterange WHERE id = $1", lead["id"], _dates(payload))

    # qualidade do lead pelo Jev (mesma régua dos experimentos: leads.jev_fit ≥ 0,6)
    fit = None
    if payload.get("summary"):
        ans = await jev.lead_score(f"Destino: {payload.get('destination') or 'Dubai'} · pax: {payload.get('party_size')} · datas: {payload.get('travel_dates_text') or _dates(payload)} · "
                                   f"motivo: {payload.get('trip_purpose')} · preferências: {payload.get('preferences')}\nResumo da Huda: {payload['summary']}")
        if ans:
            fit = ans.score("fit")
            seg = ans.choice("segment")
            if seg:
                await db.execute("UPDATE leads SET segment = COALESCE(segment, $2) WHERE id = $1", lead["id"], seg)
        if fit is not None:
            await db.execute("UPDATE leads SET jev_fit = $2, score = GREATEST(score, $3) WHERE id = $1", lead["id"], fit, int(fit * 100))

    if event == "handoff":
        reason = payload.get("handoff_reason") or "huda_handoff"
        await db.execute("UPDATE leads SET stage = 'qualified', human_owner = COALESCE(human_owner, 'dubai_team') WHERE id = $1", lead["id"])
        # Operacional assume: pagamento/reembolso/cancelamento/emergência vão para booking_payments; o resto para o consultor humano via Chatwoot
        await bus.publish(bus.TASKS, {"agent": "booking_payments", "task": "handle_huda_handoff", "lead_id": str(lead["id"]),
                                      "text": payload.get("summary") or "", "note": reason})
        await bus.publish(bus.ALERTS, {"kind": "handoff", "severity": "medium",
                                       "text": f"Huda transferiu {payload.get('name') or phone} ({lead.get('market_code') or '?'}): {(payload.get('summary') or reason)[:280]}"})
    log.info("huda_event", event=event, lead_id=str(lead["id"]), market=lead.get("market_code"), fit=fit)
    return {"ok": True, "lead_id": str(lead["id"]), "market_code": lead.get("market_code"), "jev_fit": fit}
