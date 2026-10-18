"""MICE & Eventos (HCB1 Events Management LLC): RFPs de grupos e eventos corporativos, feiras, venues, proposta e entrega."""
from __future__ import annotations

from datetime import date
from typing import Any

from brain.core import bus, db, jev
from brain.settings import agency_config
from brain.tools import create_sdk_mcp_server, err, ok, tool

SERVER = "mice"

FAIRS_2026_27 = [  # DWTC/Expo City — confirmar na página oficial antes de cada proposta (fonte: site-highclass/05_feiras)
    ("Beautyworld Dubai", "2026-10-06", "2026-10-08", "DWTC"), ("WETEX", "2026-10-20", "2026-10-22", "DWTC"), ("Automechanika Dubai", "2026-11-10", "2026-11-12", "DEC Expo City"),
    ("Big 5 Global", "2026-11-23", "2026-11-26", "DWTC"), ("GITEX Global", "2026-12-08", "2026-12-11", "DEC Expo City"), ("Intersec Global", "2027-01-12", "2027-01-14", "DWTC"),
    ("World of Coffee Dubai", "2027-01-24", "2027-01-26", "DWTC"), ("WHX Global (Arab Health)", "2027-01-26", "2027-01-29", "DWTC"), ("Gulfood", "2027-03-15", "2027-03-19", "DWTC + DEC"),
    ("IFX Exhibition", "2027-03-24", "2027-03-25", "DWTC"), ("AIM Congress", "2027-04-12", "2027-04-14", "DWTC"), ("Arabian Travel Market", "2027-05-03", "2027-05-06", "DWTC"), ("Seamless Middle East", "2027-05-24", "2027-05-26", "DWTC"),
]


@tool("open_rfp", "Abre um RFP de grupo/evento (incentive|conference|exhibition_visit|corporate_retreat|product_launch|wedding|gala). Pax ≥ limite de autonomia (config) cria decisão da CEO automaticamente (kind='mice'). O Jev estima probabilidade de fechar.", {"lead_id": str, "partner_id": str, "company": str, "event_kind": str, "fair_name": str, "pax": int, "date_start": str, "date_end": str, "budget_pp_usd": float, "requirements": dict})
async def open_rfp(args: dict[str, Any]) -> dict[str, Any]:
    limit = int(agency_config()["autonomy"].get("mice_pax_requires_ceo", 20))
    rng = f"[{args['date_start']},{args.get('date_end') or args['date_start']}]" if args.get("date_start") else None
    row = await db.fetchrow(
        """INSERT INTO mice_rfps (lead_id, partner_id, company, event_kind, fair_name, pax, dates, budget_pp_usd, requirements) VALUES ($1,$2,$3,$4,$5,$6,$7::text::daterange,$8,coalesce($9,'{}'::jsonb)) RETURNING id""",
        args.get("lead_id"), args.get("partner_id"), args.get("company"), args["event_kind"], args.get("fair_name"), int(args["pax"]), rng, args.get("budget_pp_usd"), args.get("requirements"))
    ans = await jev.decide({k: args.get(k) for k in ("company", "event_kind", "fair_name", "pax", "date_start", "budget_pp_usd", "requirements")}, {
        "win_probability": {"type": "score", "instructions": "Probabilidade de fechar (orçamento realista, datas definidas, empresa identificada, prazo suficiente)", "criteria": ["baixa", "média", "boa", "alta"]},
        "feasible_dates": {"type": "noul", "instructions": "As datas são viáveis (≥ 3 semanas de antecedência para grupos; hotéis perto do venue costumam lotar em feiras grandes)?"}})
    out = {"rfp_id": str(row["id"]), "needs_ceo": int(args["pax"]) >= limit, "win_probability": round(ans.score("win_probability"), 3) if ans else None}  # type: ignore[index]
    if out["needs_ceo"]:
        d = await db.fetchrow("INSERT INTO decisions (kind, context, recommendation, requested_by, amount_usd) VALUES ('mice', $1, $2, 'ai:mice_events', $3) RETURNING id",
                              f"RFP {args.get('company') or 'grupo'}: {args['event_kind']} {args.get('fair_name') or ''} · {args['pax']} pax · {args.get('date_start')} · USD {args.get('budget_pp_usd')} pp",
                              "Aprovar montagem da proposta pela HCB1 e eventuais bloqueios de hotel", (args.get("budget_pp_usd") or 0) * int(args["pax"]))
        await db.execute("UPDATE mice_rfps SET decision_id = $2 WHERE id = $1", row["id"], d["id"])  # type: ignore[index]
        await bus.publish(bus.ALERTS, {"kind": "mice", "severity": "medium", "text": f"RFP MICE: {args.get('company')} · {args['pax']} pax · {args.get('fair_name') or args['event_kind']} — aguardando sua decisão"})
    return ok(out)


@tool("rfps_open", "RFPs abertos por estágio com prazo (dias até o evento), pax, orçamento e probabilidade.", {})
async def rfps_open(args: dict[str, Any]) -> dict[str, Any]:
    return ok(await db.fetch("""SELECT id, company, event_kind, fair_name, pax, lower(dates) AS starts, upper(dates) AS ends, (lower(dates) - current_date) AS days_to_event, budget_pp_usd, status, quote_id, decision_id, created_at
                                FROM mice_rfps WHERE status NOT IN ('won','lost','delivered') ORDER BY lower(dates) NULLS LAST"""))


@tool("update_rfp", "Atualiza estágio (qualifying|proposal_sent|negotiating|won|lost|delivered), requisitos e cotação vinculada.", {"rfp_id": str, "status": str, "quote_id": str, "requirements": dict})
async def update_rfp(args: dict[str, Any]) -> dict[str, Any]:
    await db.execute("""UPDATE mice_rfps SET status = coalesce($2,status), quote_id = coalesce($3,quote_id), requirements = coalesce($4,requirements), updated_at = now() WHERE id = $1""",
                     args["rfp_id"], args.get("status"), args.get("quote_id"), args.get("requirements"))
    return ok({"updated": True})


@tool("fairs_calendar", "Feiras em Dubai nos próximos N dias (DWTC/Expo City) com datas e venue — para prospectar expositores e montar pacotes 'feira'. Confirmar na página oficial.", {"days": int})
async def fairs_calendar(args: dict[str, Any]) -> dict[str, Any]:
    horizon = date.today().toordinal() + int(args.get("days") or 180)
    rows = [{"name": n, "start": s, "end": e, "venue": v, "days_to": date.fromisoformat(s).toordinal() - date.today().toordinal()} for n, s, e, v in FAIRS_2026_27 if date.fromisoformat(e).toordinal() >= date.today().toordinal() and date.fromisoformat(s).toordinal() <= horizon]
    return ok(rows)


@tool("group_capacity_check", "Verifica capacidade para um grupo numa data: carros próprios + terceirizados necessários (pax/malas), guias por idioma disponíveis, conflitos com serviços já planejados, hotéis do catálogo com 'group_friendly'.", {"date": str, "pax": int, "languages": list})
async def group_capacity_check(args: dict[str, Any]) -> dict[str, Any]:
    d = date.fromisoformat(args["date"])
    own = await db.fetch("SELECT id, name, pax_capacity AS seats FROM vehicles WHERE active")
    seats = sum(int(v.get("seats") or 0) for v in own)
    pax = int(args["pax"])
    busy = await db.fetchrow("SELECT count(*) n FROM field_assignments WHERE service_date = $1 AND status NOT IN ('cancelled')", d)
    guides = await db.fetch("SELECT name, languages, vip_cleared FROM guides WHERE active AND ($1::text[] IS NULL OR languages && $1)", args.get("languages"))
    hotels = await db.fetch("SELECT id, name, location, star_rating, sell_price_usd FROM catalog_items WHERE kind = 'hotel' AND active AND ('groups' = ANY(suitable_for) OR 'mice' = ANY(suitable_for)) ORDER BY star_rating DESC LIMIT 10")
    coaches = max(0, -(-max(0, pax - seats) // 45))
    return ok({"date": str(d), "pax": pax, "own_seats": seats, "coaches_needed_45pax": coaches, "services_already_planned": int(busy["n"]), "guides": guides, "hotel_candidates": hotels,  # type: ignore[index]
               "note": "ônibus/vans sempre de fornecedor licenciado RTA; acima de 8 pax o transfer é terceirizado"})


def server():
    return create_sdk_mcp_server(SERVER, "1.0.0", [open_rfp, rfps_open, update_rfp, fairs_calendar, group_capacity_check])
