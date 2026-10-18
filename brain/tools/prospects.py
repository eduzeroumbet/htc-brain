"""Prospecção B2B: agências de viagens no mundo todo que podem mandar turistas aos Emirados.

Busca na web (SERP_API_KEY → SerpAPI; sem chave, devolve instruções para o agente usar fetch_url em diretórios
públicos), cadastro de agências parceiras, sequência de contato e registro de respostas. O Jev pontua o fit.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

from brain.core import bus, db, jev
from brain.tools import create_sdk_mcp_server, err, ok, tool

SERVER = "prospects"
SERP_KEY = os.getenv("SERP_API_KEY", "")

DIRECTORIES = {
    "BR": ["https://www.braztoa.com.br/associados", "https://abav.com.br/associados"],
    "IN": ["https://www.taai.in/members", "https://www.otoai.org/members"],
    "GB": ["https://www.abta.com/find-a-member", "https://www.aito.com/members"],
    "US": ["https://www.virtuoso.com/advisors", "https://www.asta.org/find-a-travel-advisor"],
    "DE": ["https://www.drv.de/mitglieder"],
    "RU": ["https://www.atorus.ru/members"],
    "SA": ["https://www.saudi-tourism-agencies.sa"],
}


@tool("web_search", "Busca na web por agências de viagens (ex.: 'agência de viagens luxo São Paulo Dubai'). Retorna até 10 resultados (título, url, trecho). Sem SERP_API_KEY devolve diretórios oficiais do mercado para usar com fetch_url.", {"query": str, "market_code": str, "gl": str, "hl": str})
async def web_search(args: dict[str, Any]) -> dict[str, Any]:
    q = args["query"]
    if not SERP_KEY:
        return ok({"results": [], "fallback_directories": DIRECTORIES.get(args.get("market_code") or "", []),
                   "hint": "Defina SERP_API_KEY para busca automática; use fetch_url nos diretórios acima."})
    params = {"engine": "google", "q": q, "api_key": SERP_KEY, "num": 10, "gl": args.get("gl") or "", "hl": args.get("hl") or ""}
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get("https://serpapi.com/search.json", params={k: v for k, v in params.items() if v})
    if r.status_code >= 400:
        return err(f"serpapi {r.status_code}")
    data = r.json().get("organic_results", [])
    return ok({"results": [{"title": d.get("title"), "url": d.get("link"), "snippet": d.get("snippet")} for d in data[:10]]})


@tool("upsert_partner_agency", "Cadastra/atualiza uma agência prospectada. O Jev calcula o fit (0–1) a partir do perfil; abaixo de 0.4 marca 'dormant'.", {
    "name": str, "country": str, "market_code": str, "city": str, "website": str, "type": str, "sells_middle_east": bool,
    "contact_name": str, "contact_role": str, "contact_email": str, "contact_phone": str, "linkedin": str, "source": str, "notes": str})
async def upsert_partner_agency(args: dict[str, Any]) -> dict[str, Any]:
    profile = " | ".join(f"{k}: {v}" for k, v in args.items() if v)
    fit = None
    ans = await jev.prospect_fit(profile)
    if ans:
        fit = ans.score("fit")
        args.setdefault("type", ans.choice("type"))
        if args.get("sells_middle_east") is None:
            args["sells_middle_east"] = ans.noul("sells_middle_east") >= 0.5
    stage = "dormant" if fit is not None and fit < 0.4 else "identified"
    row = await db.fetchrow(
        """INSERT INTO partner_agencies (name, country, market_code, city, website, type, sells_middle_east, contact_name, contact_role,
                                         contact_email, contact_phone, linkedin, source, notes, jev_fit, stage)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
           ON CONFLICT (name, country) DO UPDATE SET website = COALESCE(EXCLUDED.website, partner_agencies.website),
             contact_name = COALESCE(EXCLUDED.contact_name, partner_agencies.contact_name), contact_email = COALESCE(EXCLUDED.contact_email, partner_agencies.contact_email),
             contact_role = COALESCE(EXCLUDED.contact_role, partner_agencies.contact_role), linkedin = COALESCE(EXCLUDED.linkedin, partner_agencies.linkedin),
             notes = COALESCE(EXCLUDED.notes, partner_agencies.notes), jev_fit = COALESCE(EXCLUDED.jev_fit, partner_agencies.jev_fit), updated_at = now()
           RETURNING id, stage, jev_fit""",
        args["name"], args["country"], args.get("market_code"), args.get("city"), args.get("website"), args.get("type"), args.get("sells_middle_east"),
        args.get("contact_name"), args.get("contact_role"), args.get("contact_email"), args.get("contact_phone"), args.get("linkedin"),
        args.get("source"), args.get("notes"), fit, stage)
    return ok(row)


@tool("partners_to_contact", "Agências em 'identified' com fit ≥ 0.6 e e-mail/LinkedIn, ou com follow-up vencido (next_action_at ≤ agora). Limite padrão 15.", {"market_code": str, "limit": int})
async def partners_to_contact(args: dict[str, Any]) -> dict[str, Any]:
    rows = await db.fetch(
        """SELECT p.*, (SELECT max(sequence_step) FROM outreach o WHERE o.partner_id = p.id AND o.direction = 'out') AS last_step
           FROM partner_agencies p
           WHERE ($1::text IS NULL OR p.market_code = $1)
             AND ((p.stage = 'identified' AND COALESCE(p.jev_fit, 0.6) >= 0.6 AND (p.contact_email IS NOT NULL OR p.linkedin IS NOT NULL))
                  OR (p.stage IN ('contacted', 'replied') AND p.next_action_at <= now()))
           ORDER BY p.jev_fit DESC NULLS LAST, p.next_action_at LIMIT $2""", args.get("market_code"), int(args.get("limit") or 15))
    return ok(rows)


@tool("log_outreach", "Registra um contato enviado (direction=out) e agenda o próximo passo: step 1 → D+4, 2 → D+10, 3 → D+30, 4 → dormant. Envia por e-mail quando channel='email' e há SMTP.", {"partner_id": str, "channel": str, "subject": str, "body": str, "sequence_step": int})
async def log_outreach(args: dict[str, Any]) -> dict[str, Any]:
    step = int(args.get("sequence_step") or 1)
    gap = {1: 4, 2: 10, 3: 30}.get(step)
    p = await db.fetchrow("SELECT contact_email, name FROM partner_agencies WHERE id = $1", args["partner_id"])
    if not p:
        return err("partner não encontrado")
    await db.execute("INSERT INTO outreach (partner_id, direction, channel, subject, body, sequence_step) VALUES ($1,'out',$2,$3,$4,$5)",
                     args["partner_id"], args["channel"], args.get("subject"), args["body"], step)
    if gap:
        await db.execute("UPDATE partner_agencies SET stage = CASE WHEN stage = 'identified' THEN 'contacted' ELSE stage END, next_action_at = now() + ($2 || ' days')::interval, updated_at = now() WHERE id = $1",
                         args["partner_id"], str(gap))
    else:
        await db.execute("UPDATE partner_agencies SET stage = 'dormant', next_action_at = NULL, updated_at = now() WHERE id = $1", args["partner_id"])
    sent = False
    if args["channel"] == "email" and p["contact_email"]:
        await bus.publish(bus.OUTBOUND, {"channel": "email", "channel_user_id": p["contact_email"], "subject": args.get("subject") or "", "text": args["body"], "author": "ai:prospector"})
        sent = True
    return ok({"logged": True, "sent": sent, "next_in_days": gap})


@tool("record_partner_reply", "Registra resposta recebida (direction=in). O Jev classifica: interested|later|not_interested|question|bounce e o estágio é atualizado.", {"partner_id": str, "channel": str, "body": str})
async def record_partner_reply(args: dict[str, Any]) -> dict[str, Any]:
    ans = await jev.decide(args["body"][:3000], {"reply": {"type": "choice", "instructions": "Como a agência respondeu?", "criteria": {
        "interested": "quer saber mais, pede call, proposta ou comissão", "later": "interessada mas não agora", "not_interested": "recusa", "question": "fez pergunta sem decidir", "bounce": "erro de entrega/ausência"}}})
    cls = ans.choice("reply", "question") if ans else "question"
    stage = {"interested": "call_scheduled", "later": "contacted", "not_interested": "declined", "question": "replied", "bounce": "dormant"}[cls]
    nxt = {"interested": "1 day", "later": "45 days", "question": "1 day"}.get(cls)
    await db.execute("INSERT INTO outreach (partner_id, direction, channel, body, jev_reply_class) VALUES ($1,'in',$2,$3,$4)", args["partner_id"], args["channel"], args["body"], cls)
    await db.execute("UPDATE partner_agencies SET stage = $2, next_action_at = CASE WHEN $3::text IS NULL THEN NULL ELSE now() + $3::interval END, updated_at = now() WHERE id = $1",
                     args["partner_id"], stage, nxt)
    return ok({"reply_class": cls, "stage": stage})


@tool("set_partner_stage", "Atualiza estágio e termos: proposal_sent | partner (commission_pct, agreement_url) | declined | dormant.", {"partner_id": str, "stage": str, "commission_pct": float, "agreement_url": str, "notes": str})
async def set_partner_stage(args: dict[str, Any]) -> dict[str, Any]:
    await db.execute("""UPDATE partner_agencies SET stage = $2, commission_pct = COALESCE($3, commission_pct), agreement_url = COALESCE($4, agreement_url),
                        notes = COALESCE($5, notes), updated_at = now() WHERE id = $1""",
                     args["partner_id"], args["stage"], args.get("commission_pct"), args.get("agreement_url"), args.get("notes"))
    return ok({"updated": True})


@tool("prospecting_pipeline", "Funil B2B por mercado: identificadas, contatadas, responderam, calls, propostas, parceiras — e respostas dos últimos N dias.", {"days": int})
async def prospecting_pipeline(args: dict[str, Any]) -> dict[str, Any]:
    days = int(args.get("days") or 30)
    funnel = await db.fetch("SELECT market_code, stage, count(*) n FROM partner_agencies GROUP BY 1, 2 ORDER BY 1, 2")
    replies = await db.fetch("SELECT jev_reply_class, count(*) n FROM outreach WHERE direction = 'in' AND sent_at > now() - ($1 || ' days')::interval GROUP BY 1", str(days))
    return ok({"funnel": funnel, "replies": replies})


def server():
    return create_sdk_mcp_server(SERVER, "1.0.0", [web_search, upsert_partner_agency, partners_to_contact, log_outreach, record_partner_reply, set_partner_stage, prospecting_pipeline])
