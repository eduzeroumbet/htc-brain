"""Falhas permanentes de entrega do WhatsApp (erro 130497 da Meta) e rota alternativa por outro canal.

130497 = "Business account is restricted from messaging users in this country". A Meta não diz se é permanente;
aqui é tratado como permanente por decisão do projeto: nunca retentar, registrar em delivery_failure_events
(código + mercado, sem telefone, texto ou payload) e oferecer ao contato outro canal, uma única vez.
O Brasil fica pausado no WhatsApp enquanto WA_BR_DELIVERY_ENABLED=false (padrão). Só humano liga a flag.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any

import structlog

from brain.core import bus, db
from brain.settings import alt_route_config, get_settings

log = structlog.get_logger(__name__)

COUNTRY_RESTRICTED = 130497
CAT_COUNTRY_RESTRICTED = "wa_country_restricted"
CAT_BR_PAUSED = "wa_br_paused_by_flag"

# código de discagem → mercado, pelo prefixo mais longo; +1 e +7 são compartilhados entre países (não adivinhar)
DIAL_CODES = {"55": "BR", "971": "AE", "91": "IN", "44": "GB", "966": "SA", "49": "DE", "1": "ambiguous", "7": "ambiguous"}

# termos de descadastro (contingência fail-closed enquanto não existe consent_log)
OPT_OUT_TERMS = ("PARAR", "STOP", "SAIR", "UNSUBSCRIBE", "ألغِ", "रोकें")

ALT_CHANNELS = ("messenger", "instagram", "email", "webchat")   # ordem de preferência; nunca whatsapp


# ───────────────────────── classificação ─────────────────────────

def _codes(errors: Any) -> list[Any]:
    return [e.get("code") for e in errors or [] if isinstance(e, dict)]


def extract_error_codes(payload: Any) -> list[int]:
    """Códigos de erro da Meta em error.code (resposta síncrona), value.errors[], statuses[].errors[] e messages[].errors[]."""
    if not isinstance(payload, dict):
        return []
    found = _codes([payload["error"]] if isinstance(payload.get("error"), dict) else [])
    values = [payload, *(c.get("value") or {} for e in payload.get("entry") or [] for c in e.get("changes") or [])]
    for v in values:
        found += _codes(v.get("errors"))
        for item in [*(v.get("statuses") or []), *(v.get("messages") or [])]:
            found += _codes(item.get("errors"))
    out = []
    for c in found:
        try:
            out.append(int(c))
        except (TypeError, ValueError):
            continue
    return out


def market_from_phone(phone: str | None) -> tuple[str, str | None]:
    """(mercado, prefixo) pelo prefixo mais longo do número em E.164 (o wa_id da Meta vem sem '+')."""
    digits = re.sub(r"\D", "", phone or "")
    if not digits or digits.startswith("0"):
        return "unknown", None
    for n in (3, 2, 1):
        if digits[:n] in DIAL_CODES:
            return DIAL_CODES[digits[:n]], f"+{digits[:n]}"
    return "unknown", None


def br_paused(event: dict[str, Any]) -> bool:
    """Guarda do Brasil: True = não chamar a Graph API para este envio WhatsApp."""
    s = get_settings()
    if s.wa_br_delivery_enabled or market_from_phone(event.get("channel_user_id"))[0] != "BR":
        return False
    if s.wa_br_block_scope == "proactive_only":
        return bool(event.get("template") or event.get("template_required"))
    return True  # "all" ou valor desconhecido: bloqueia tudo


def outbound_ref(event: dict[str, Any]) -> str:
    """Chave de idempotência do envio (sem guardar o número em claro)."""
    if event.get("outbound_id"):
        return str(event["outbound_id"])
    raw = "|".join(str(event.get(k) or "") for k in ("channel_user_id", "text", "template", "document_url"))
    return "out:" + hashlib.sha256(raw.encode()).hexdigest()[:32]


def webhook_ref(value: dict[str, Any]) -> str:
    return "value:" + hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:32]


def _norm(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFD", text.casefold()) if unicodedata.category(ch) != "Mn")


_TERMS = {_norm(t) for t in OPT_OUT_TERMS}


def is_opt_out(text: str | None) -> bool:
    """Mensagem curta (até 4 palavras) com um termo de descadastro como palavra inteira: "PARAR", "stop pls"."""
    words = [w.strip(".,;:!?¡¿\"'()[]") for w in _norm(text or "").split()]
    return 0 < len(words) <= 4 and any(w in _TERMS for w in words)


# ───────────────────────── registro e rota alternativa ─────────────────────────

async def _lead_id_for(wa_id: str) -> str | None:
    row = await db.fetchrow("SELECT id FROM leads WHERE channel = 'whatsapp' AND channel_user_id = $1", wa_id)
    return str(row["id"]) if row else None


async def handle_permanent_failure(*, category: str, source: str, to: str | None, ref: str, lead_id: str | None = None,
                                   error_code: int | None = None, wamid: str | None = None, fbtrace_id: str | None = None,
                                   offer_alt_route: bool = True) -> str | None:
    """Registra a falha (idempotente por ref+categoria) e oferece a rota alternativa uma vez. Nunca retenta.

    Retorna o alt_route_status, ou None se o evento já estava registrado (webhook repetido) ou não há rota a oferecer.
    """
    lead_id = lead_id or (await _lead_id_for(to) if to else None)
    market_code, prefix = market_from_phone(to)
    row = await db.fetchrow(
        """INSERT INTO delivery_failure_events (error_code, category, market_code, country_prefix, source, outbound_ref, lead_id, wamid, fbtrace_id)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) ON CONFLICT (outbound_ref, category) DO NOTHING RETURNING id""",
        error_code, category, market_code, prefix, source, ref, lead_id, wamid, fbtrace_id)
    if row is None:
        log.info("wa_permanent_failure_duplicate", category=category, source=source)
        return None
    log.warning("wa_permanent_failure", category=category, code=error_code, market=market_code, source=source, lead_id=lead_id)
    if not offer_alt_route:
        return None
    status, channel = await offer_alt_route_for(lead_id=lead_id, market_code=market_code)
    await db.execute("UPDATE delivery_failure_events SET alt_route_status = $2, alt_route_channel = $3 WHERE id = $1",
                     row["id"], status, channel)
    if status not in ("dispatched", "skipped_recent") and await bus.rate_limit(f"alt_route_alert:{lead_id or market_code}", 1, 24 * 3600):
        what = f"erro {error_code} da Meta" if error_code else "Brasil pausado (WA_BR_DELIVERY_ENABLED=false)"
        await bus.publish(bus.ALERTS, {"kind": "channel", "severity": "medium",
                                       "text": f"WhatsApp não entregou ({what}), mercado {market_code}, lead {lead_id or '?'}: rota alternativa {status}."})
    return status


def render_alt_route_text(cfg: dict[str, Any]) -> str | None:
    """Texto da Huda com uma linha por canal configurado em ALT_ROUTE_*. None se não houver canal ou sobrar placeholder."""
    s = get_settings()
    values = {"webchat": s.alt_route_webchat_url, "email": s.alt_route_email,
              "messenger": s.alt_route_messenger_url, "instagram": s.alt_route_instagram_handle}
    lines = [tpl.format(value=values[ch].strip()) for ch, tpl in (cfg.get("channel_lines") or {}).items()
             if (values.get(ch) or "").strip()]
    if not lines or not cfg.get("text_pt_br"):
        return None
    text = cfg["text_pt_br"].replace("{channels}", "\n".join(lines))
    return None if "{" in text or "}" in text else text


def _channel_ready(channel: str) -> bool:
    s = get_settings()
    return {"messenger": bool(s.meta_page_id and s.meta_page_access_token),
            "instagram": bool(s.meta_ig_account_id and s.meta_page_access_token),
            "email": bool(s.smtp_host),
            "webchat": True}.get(channel, False)


async def offer_alt_route_for(*, lead_id: str | None, market_code: str) -> tuple[str, str | None]:
    """Publica no outbound, por outro canal do mesmo contato, a mensagem de rota alternativa. Devolve (status, canal)."""
    cfg = alt_route_config()
    if market_code not in (cfg.get("markets") or []):
        return "not_applicable_market", None
    if not lead_id:
        return "unreachable", None
    if not cfg.get("approved"):
        return "skipped_text_not_approved", None
    text = render_alt_route_text(cfg)
    if not text:
        return "skipped_no_channels", None
    # o mesmo contato em outros canais (mesmo telefone ou e-mail)
    people = await db.fetch(
        """WITH me AS (SELECT phone, lower(email) AS email FROM leads WHERE id = $1)
           SELECT l.id, l.channel, l.channel_user_id FROM leads l, me
           WHERE l.id = $1 OR (me.phone IS NOT NULL AND l.phone = me.phone)
              OR (me.email IS NOT NULL AND (lower(l.email) = me.email OR (l.channel = 'email' AND lower(l.channel_user_id) = me.email)))""",
        lead_id)
    ids = [str(p["id"]) for p in people] or [lead_id]
    if await db.fetchrow("SELECT 1 FROM data_requests WHERE lead_id = ANY($1::uuid[]) AND status NOT IN ('completed','refused') LIMIT 1", ids):
        return "skipped_dsar", None
    if await db.fetchrow("SELECT 1 FROM data_requests WHERE lead_id = ANY($1::uuid[]) AND kind IN ('consent_withdrawal','objection','erasure') LIMIT 1", ids):
        return "skipped_opted_out", None
    inbound = await db.fetch(
        """SELECT c.lead_id, m.body FROM messages m JOIN conversations c ON c.id = m.conversation_id
           WHERE c.lead_id = ANY($1::uuid[]) AND m.direction = 'in'""", ids)
    if any(is_opt_out(r["body"]) for r in inbound):
        return "skipped_opted_out", None
    wrote = {str(r["lead_id"]) for r in inbound}   # só canal pelo qual o contato já escreveu
    target = next((p for ch in ALT_CHANNELS if _channel_ready(ch)
                   for p in people if p["channel"] == ch and str(p["id"]) in wrote), None)
    if not target:
        return "unreachable", None
    if not await bus.rate_limit(f"alt_route:{lead_id}", 1, int(cfg.get("lead_window_hours", 24)) * 3600):
        return "skipped_recent", target["channel"]
    await bus.publish(bus.OUTBOUND, {"channel": target["channel"], "channel_user_id": target["channel_user_id"], "text": text,
                                     "lead_id": str(target["id"]), "kind": "alt_route_notice", "author": "ai:consultant"})
    return "dispatched", target["channel"]


async def dashboard_counts(days: int = 30) -> dict[str, Any]:
    """Falhas permanentes por dia (UTC), mercado e categoria; cada categoria é um contador próprio."""
    rows = await db.fetch(
        """SELECT (occurred_at AT TIME ZONE 'UTC')::date AS day, market_code, category, count(*) AS n
           FROM delivery_failure_events WHERE occurred_at > now() - make_interval(days => $1)
           GROUP BY 1, 2, 3 ORDER BY 1, 2, 3""", days)
    totals = {CAT_COUNTRY_RESTRICTED: 0, CAT_BR_PAUSED: 0}
    for r in rows:
        totals[r["category"]] = totals.get(r["category"], 0) + int(r["n"])
    return {"days": days, "tz": "UTC", "display_tz": "Asia/Dubai", "totals": totals, "daily": rows}
