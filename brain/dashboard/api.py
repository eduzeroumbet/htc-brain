"""API lida pelo dashboard do CEO. Todas as rotas exigem o login básico definido em main.py."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from brain.core import bus, db, registry
from brain.settings import agency_config, budgets_config, markets_config

router = APIRouter()


@router.get("/kpis")
async def kpis(days: int = 30) -> dict[str, Any]:
    await db.rollup_kpis()
    since = date.today() - timedelta(days=days)
    daily = await db.fetch("SELECT * FROM kpis_daily WHERE market_code = 'ALL' AND day >= $1 ORDER BY day", since)
    by_market = await db.fetch(
        """SELECT market_code, sum(leads_new) leads, sum(leads_qualified) qualified, sum(quotes_sent) quotes, sum(bookings) bookings,
                  sum(revenue_usd) revenue_usd, sum(margin_usd) margin_usd, sum(ad_spend_usd) ad_spend_usd, sum(token_cost_usd) token_cost_usd,
                  sum(conversations) conversations, sum(escalations) escalations, avg(first_response_p50_s) first_response_p50_s, avg(csat_avg) csat
           FROM kpis_daily WHERE market_code <> 'ALL' AND day >= $1 GROUP BY market_code ORDER BY revenue_usd DESC""", since)
    prev = await db.fetchrow(
        """SELECT sum(leads_new) leads, sum(bookings) bookings, sum(revenue_usd) revenue_usd, sum(ad_spend_usd) ad_spend_usd
           FROM kpis_daily WHERE market_code = 'ALL' AND day >= $1 AND day < $2""", since - timedelta(days=days), since)
    targets = agency_config()["kpis"]
    names = {c: m["name"] for c, m in markets_config().items()}
    for r in by_market:
        r["market_name"] = names.get(r["market_code"], r["market_code"])
        b = int(r["bookings"] or 0)
        r["cac_usd"] = round(float(r["ad_spend_usd"] or 0) / b, 2) if b else None
        r["cac_target"] = budgets_config()["media"]["targets_usd"]["cac"].get(r["market_code"])
    return {"days": days, "daily": daily, "by_market": by_market, "previous": prev, "targets": targets}


@router.get("/decisions")
async def decisions() -> list[dict[str, Any]]:
    return await db.fetch("SELECT * FROM decisions WHERE status = 'pending' ORDER BY created_at")


class Decide(BaseModel):
    approve: bool
    note: str | None = None
    becomes_rule: bool = False
    rule_scope: str | None = None


@router.post("/decisions/{decision_id}")
async def decide(decision_id: str, body: Decide) -> dict[str, Any]:
    d = await db.fetchrow("SELECT * FROM decisions WHERE id = $1 AND status = 'pending'", decision_id)
    if not d:
        raise HTTPException(404)
    status = "approved" if body.approve else "rejected"
    await db.execute("UPDATE decisions SET status = $2, decided_by = 'ceo', decided_at = now(), becomes_rule = $3 WHERE id = $1",
                     decision_id, status, body.becomes_rule)
    if body.becomes_rule and body.note:
        await db.execute("INSERT INTO rules (scope, rule, origin_decision_id) VALUES ($1,$2,$3)", body.rule_scope or d["kind"], body.note, decision_id)
    # efeitos colaterais
    if d["kind"] == "discount" and body.approve:
        # o contexto da decisão começa com "Cotação <uuid> ..." (ver tools/quotes.py)
        await db.execute("""UPDATE quotes SET status = 'sent', approved_by = 'ceo'
                            WHERE status = 'draft' AND id::text = split_part(split_part($1, 'Cotação ', 2), ' ', 1)""", d["context"])
    await bus.publish(bus.TASKS, {"agent": "ceo", "task": "approve_within_rules"})
    return {"id": decision_id, "status": status}


@router.get("/escalations")
async def escalations() -> list[dict[str, Any]]:
    return await db.fetch(
        """SELECT e.*, l.display_name, l.market_code, l.channel FROM escalations e JOIN leads l ON l.id = e.lead_id
           WHERE e.status <> 'resolved' ORDER BY e.opened_at""")


@router.post("/escalations/{escalation_id}/resolve")
async def resolve_escalation(escalation_id: str, outcome: str = "") -> dict[str, Any]:
    await db.execute("UPDATE escalations SET status = 'resolved', resolved_by = 'ceo', resolved_at = now(), outcome = $2 WHERE id = $1", escalation_id, outcome)
    await db.execute("""UPDATE conversations SET status = 'ai' WHERE id = (SELECT conversation_id FROM escalations WHERE id = $1)""", escalation_id)
    return {"id": escalation_id, "status": "resolved"}


@router.get("/agents")
async def agents() -> list[dict[str, Any]]:
    rows = await db.fetch(
        """SELECT agent, count(*) runs, sum(cost_usd) cost_usd, avg(duration_ms) avg_ms,
                  count(*) FILTER (WHERE status = 'error') errors, count(*) FILTER (WHERE status = 'budget_exceeded') budget_hits,
                  max(started_at) last_run
           FROM agent_runs WHERE started_at::date = current_date GROUP BY agent ORDER BY cost_usd DESC NULLS LAST""")
    caps = budgets_config()["tokens"]["per_agent_daily_cap_usd"]
    for r in rows:
        r["cap_usd"] = caps.get(r["agent"])
    return rows


@router.get("/content")
async def content(days: int = 7) -> dict[str, Any]:
    rows = await db.fetch(
        """SELECT market_code, status, count(*) n FROM content_items WHERE created_at > now() - ($1::int || ' days')::interval
           GROUP BY market_code, status ORDER BY market_code""", days)
    recent = await db.fetch("SELECT id, market_code, format, channel, title, status, scheduled_for, published_at, metrics FROM content_items ORDER BY created_at DESC LIMIT 30")
    return {"summary": rows, "recent": recent}


@router.get("/campaigns")
async def campaigns(days: int = 7) -> list[dict[str, Any]]:
    from brain.tools.marketing import campaign_performance
    import json
    res = await campaign_performance({"days": days})
    return json.loads(res["content"][0]["text"])


@router.get("/feed")
async def feed(limit: int = 40) -> list[dict[str, Any]]:
    """Últimas ações da máquina para o painel de saúde."""
    return await db.fetch("SELECT agent, market_code, trigger, status, output_summary, cost_usd, duration_ms, started_at FROM agent_runs ORDER BY started_at DESC LIMIT $1", limit)


@router.get("/field")
async def field(day: str | None = None) -> dict[str, Any]:
    """Campo: serviços de hoje (ou de uma data), motoristas, guias e veículos — o antigo quadro branco."""
    d = day or str(date.today())
    services = await db.fetch(
        """SELECT f.id, f.service_date, f.start_time, f.end_time, f.kind, f.client_name, f.pax, f.bags, f.pickup, f.dropoff, f.status, f.vip,
                  v.name AS vehicle, d.name AS driver, g.name AS guide
           FROM field_assignments f LEFT JOIN vehicles v ON v.id = f.vehicle_id LEFT JOIN drivers d ON d.id = f.driver_id LEFT JOIN guides g ON g.id = f.guide_id
           WHERE f.service_date = $1::text::date ORDER BY f.start_time""", d)
    vehicles = await db.fetch("SELECT id, name, plate, odometer_km, last_service_km, service_interval_km, registration_expiry FROM vehicles WHERE active ORDER BY id")
    for v in vehicles:
        v["km_to_service"] = int(v["last_service_km"] or 0) + int(v["service_interval_km"] or 10000) - int(v["odometer_km"] or 0)
    hours = await db.fetch(
        """SELECT d.name, coalesce(sum(h.hours_regular),0) AS regular, coalesce(sum(h.hours_extra),0) AS extra
           FROM drivers d LEFT JOIN driver_hours h ON h.driver_id = d.id AND h.day >= date_trunc('month', current_date)::date
           WHERE d.active GROUP BY d.name""")
    return {"day": d, "services": services, "vehicles": vehicles, "driver_hours_month": hours}


@router.get("/renewals")
async def renewals(days: int = 120) -> list[dict[str, Any]]:
    return await db.fetch(
        """SELECT id, name, due, owner, status, action, (due - current_date) AS days_left
           FROM renewals WHERE status <> 'cancelled' AND due IS NOT NULL AND due <= current_date + $1::int ORDER BY due""", days)


@router.post("/tasks/{agent}/{task}")
async def trigger_task(agent: str, task: str, market_code: str | None = None) -> dict[str, Any]:
    """Disparo manual pelo dashboard (ex.: rodar o briefing agora)."""
    await bus.publish(bus.TASKS, {"agent": agent, "task": task, "market_code": market_code})
    return {"queued": True}


# ───────────────────────── departamentos, CEO chat, operacional, financeiro, prospecção, auditoria ─────────────────────────
import yaml as _yaml
from pathlib import Path as _Path

_DEPTS = _yaml.safe_load((_Path(__file__).resolve().parents[2] / "config" / "departments.yaml").read_text(encoding="utf-8"))


@router.get("/departments")
async def departments() -> list[dict[str, Any]]:
    """Os 8 departamentos com execuções/custo/erros de hoje por agente e se está pausado."""
    runs = await db.fetch("""SELECT agent, count(*) runs, coalesce(sum(cost_usd),0) cost_usd, count(*) FILTER (WHERE status <> 'ok') errors, max(created_at) last_run
                             FROM agent_runs WHERE created_at >= current_date GROUP BY agent""")
    by_agent = {r["agent"]: r for r in runs}
    paused = {k.split(":", 1)[1] for k in await bus.client().keys("agent_paused:*")}
    out = []
    for key, d in _DEPTS["departments"].items():
        agents = [{"name": a, "paused": a in paused, **{k: v for k, v in (by_agent.get(a) or {}).items() if k != "agent"}} for a in d["agents"]]
        out.append({"id": key, "label": d["label"], "mission": d["mission"], "head": d["head"], "agents": agents,
                    "runs": sum(int(a.get("runs") or 0) for a in agents), "cost_usd": float(sum(float(a.get("cost_usd") or 0) for a in agents)),
                    "errors": sum(int(a.get("errors") or 0) for a in agents)})
    return out


class CeoMessage(BaseModel):
    message: str


@router.get("/ceo/chat")
async def ceo_chat_history(limit: int = 40) -> list[dict[str, Any]]:
    rows = await db.fetch("SELECT role, body, delegations, cost_usd, created_at FROM ceo_chat ORDER BY created_at DESC LIMIT $1", limit)
    return list(reversed(rows))


@router.post("/ceo/chat")
async def ceo_chat(body: CeoMessage) -> dict[str, Any]:
    """A CEO humana fala com o CEO-agente: ele responde com dados reais e delega às áreas."""
    if not body.message.strip():
        raise HTTPException(400, "mensagem vazia")
    return await registry.get("ceo").chat(body.message.strip())  # type: ignore[attr-defined]


@router.get("/issues")
async def issues(status: str | None = None) -> list[dict[str, Any]]:
    return await db.fetch("""SELECT i.id, i.kind, i.severity, i.title, i.status, i.owner_agent, i.assigned_human, i.due_at, i.opened_at, b.ref AS booking_ref, l.display_name
                             FROM issues i LEFT JOIN bookings b ON b.id = i.booking_id LEFT JOIN leads l ON l.id = i.lead_id
                             WHERE ($1::text IS NULL AND i.status NOT IN ('resolved','cancelled')) OR i.status = $1
                             ORDER BY array_position(ARRAY['critical','high','medium','low'], i.severity), i.due_at LIMIT 50""", status)


@router.get("/finance")
async def finance() -> dict[str, Any]:
    ar = await db.fetch("SELECT invoice_no, display_name, amount_usd - paid_usd AS open_usd, due_at, days_overdue, reminders_sent, jev_risk FROM v_receivables_open ORDER BY days_overdue DESC, due_at LIMIT 30")
    ap = await db.fetch("SELECT category, description, amount_usd, due_at, status FROM payables WHERE status IN ('open','scheduled','overdue') AND due_at <= current_date + 30 ORDER BY due_at LIMIT 30")
    cash = await db.fetch("SELECT day, inflow_usd, outflow_usd, closing_usd, forecast_30d_usd FROM cashflow_daily WHERE day > current_date - 30 ORDER BY day")
    totals = await db.fetchrow("""SELECT coalesce(sum(amount_usd - paid_usd),0) ar_open, coalesce(sum(amount_usd - paid_usd) FILTER (WHERE days_overdue > 0),0) ar_overdue FROM v_receivables_open""")
    ap_tot = await db.fetchrow("SELECT coalesce(sum(amount_usd),0) ap_30d FROM payables WHERE status IN ('open','scheduled','overdue') AND due_at <= current_date + 30")
    return {"receivables": ar, "payables": ap, "cashflow": cash, "totals": {**(totals or {}), **(ap_tot or {})}}


@router.get("/prospecting")
async def prospecting() -> dict[str, Any]:
    funnel = await db.fetch("SELECT market_code, stage, count(*) n FROM partner_agencies GROUP BY 1, 2 ORDER BY 1, 2")
    recent = await db.fetch("""SELECT p.name, p.country, p.stage, p.jev_fit, o.direction, o.jev_reply_class, o.sent_at FROM outreach o JOIN partner_agencies p ON p.id = o.partner_id
                               ORDER BY o.sent_at DESC LIMIT 20""")
    partners = await db.fetch("SELECT name, country, market_code, commission_pct, updated_at FROM partner_agencies WHERE stage = 'partner' ORDER BY updated_at DESC")
    return {"funnel": funnel, "recent": recent, "partners": partners}


@router.get("/audit")
async def audit_view() -> dict[str, Any]:
    findings = await db.fetch("SELECT id, day, area, severity, title, recommendation, status FROM audit_findings WHERE status IN ('open','accepted') ORDER BY day DESC, array_position(ARRAY['critical','high','medium','low'], severity) LIMIT 30")
    sla = await db.fetch("SELECT DISTINCT ON (metric) metric, value, target, breached, checked_at FROM sla_checks ORDER BY metric, checked_at DESC")
    qa = await db.fetchrow("SELECT avg(score) avg_score, count(*) n FROM qa_scores WHERE created_at > now() - interval '7 days'")
    return {"findings": findings, "sla": sla, "qa_7d": qa}


@router.post("/audit/findings/{finding_id}")
async def finding_status(finding_id: str, status: str) -> dict[str, Any]:
    if status not in ("accepted", "rejected", "implemented"):
        raise HTTPException(400)
    await db.execute("UPDATE audit_findings SET status = $2 WHERE id = $1", finding_id, status)
    return {"id": finding_id, "status": status}


@router.get("/experiments")
async def experiments(days: int = 60) -> list[dict[str, Any]]:
    """Experimentos do Analista de Mercado: em andamento e encerrados recentemente, com números reais."""
    return await db.fetch("""SELECT id, market_code, name, channel, kind, status, budget_usd, spend_actual_usd, leads, cpl_usd, bookings, cac_usd, success_metric, success_target, jev_promise, learning, started_at, ended_at
                             FROM v_experiment_results WHERE status = 'running' OR coalesce(ended_at, created_at) > now() - ($1 || ' days')::interval
                             ORDER BY status, started_at DESC NULLS LAST LIMIT 40""", str(days))
