"""Gabinete do CEO: visão completa da empresa, delegação para os departamentos e controle dos agentes.

Só o agente `ceo` usa este servidor. Ele enxerga tudo (KPIs, funil, caixa, problemas, prospecção, auditoria, agentes)
e delega tarefas pelo stream de tasks — nunca executa o trabalho dos outros departamentos.
"""
from __future__ import annotations

import os
from typing import Any

import yaml

from brain.core import bus, db, jev
from brain.tools import create_sdk_mcp_server, err, ok, tool

SERVER = "company"
_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
DEPARTMENTS = yaml.safe_load(open(os.path.join(_ROOT, "config", "departments.yaml"), encoding="utf-8"))

# tarefas que cada agente aceita por delegação (método → descrição). Mantido em sincronia com brain/agents/*.py
DELEGABLE: dict[str, dict[str, str]] = {
    "content_studio": {"daily_batch": "lote de conteúdo do mercado", "campaign_brief": "brief de campanha a partir de um objetivo"},
    "paid_media": {"optimize": "ler resultados, realocar, pausar", "scenario": "cenário de investimento (texto no payload)"},
    "seo_site": {"weekly_review": "revisão SEO/site do mercado"},
    "social_manager": {"weekly_calendar": "calendário social da semana do mercado", "campaign_social": "pacote social de uma campanha (payload.note)", "daily_metrics": "ler métricas e ajustar", "reviews_and_comments": "responder avaliações e comentários públicos"},
    "market_analyst": {"research_market": "pesquisar como alcançar clientes/agências do mercado (payload.note)", "weekly_experiments": "rodar o ciclo de experimentos", "market_entry_plan": "plano de entrada 90 dias com o budget (payload.note)"},
    "strategist": {"weekly_strategy": "estratégia da semana", "monthly_product_review": "revisar/propor pacotes", "scenario": "cenário sob demanda (payload.note)"},
    "market_intel": {"daily_refresh": "atualizar conhecimento e segurança do mercado"},
    "prospector": {"daily_outreach": "prospectar e contatar agências do mercado", "followups_due": "follow-ups vencidos"},
    "consultant": {"followup": "follow-up a um lead (payload.lead_id, note)"},
    "concierge": {"in_trip_sweep": "varredura de clientes em viagem"},
    "booking_payments": {"confirm_pending": "confirmar reservas e emitir", "resolve_issues": "atacar problemas abertos"},
    "suppliers_pricing": {"refresh_catalog": "atualizar catálogo e preços"},
    "fleet_dispatcher": {"plan_tomorrow": "agenda de campo de amanhã (motoristas, guias, resolução)", "weekly_fleet_admin": "multas, horas, revisões"},
    "admin_renewals": {"weekly_review": "renovações e compras", "gifts_for_arrivals": "presentes para chegadas"},
    "finance": {"daily_close": "fechamento do dia", "receivables_alerts": "cobrança e alertas de A/R", "weekly_cashflow": "fluxo de caixa semanal"},
    "sysops": {"health_cycle": "checar a saúde da máquina agora", "diagnose": "diagnosticar incidentes abertos", "weekly_report": "relatório de infra"},
    "partner_manager": {"weekly_care": "cuidar das parceiras", "monthly_statements": "extratos de comissão", "partner_quote": "cotação B2B (payload.partner_id, note)"},
    "mice_events": {"weekly_pipeline": "pipeline MICE e feiras", "handle_rfp": "tratar RFP de grupo (payload.lead_id, note)"},
    "people_ops": {"weekly_people": "rotina de pessoas (documentos, folgas, pool de guias)", "monthly_payroll": "pacote de folha"},
    "legal_compliance": {"weekly_review": "revisão jurídica semanal", "review_document": "revisar contrato/texto (payload.text, note=contexto)", "handle_crisis": "protocolo de crise (payload.note)"},
}


@tool("company_snapshot", "Fotografia completa da empresa (últimos N dias): KPIs por mercado, funil, decisões pendentes, escalonamentos, problemas abertos, A/R vencido, caixa, prospecção, achados do auditor, agentes hoje.", {"days": int})
async def company_snapshot(args: dict[str, Any]) -> dict[str, Any]:
    days = int(args.get("days") or 7)
    await db.rollup_kpis()
    kpis = await db.fetch("""SELECT market_code, sum(leads_new) leads, sum(leads_qualified) qualified, sum(quotes_sent) quotes, sum(bookings) bookings,
                                    sum(revenue_usd) revenue_usd, sum(margin_usd) margin_usd, sum(ad_spend_usd) ad_spend_usd, sum(token_cost_usd) token_cost_usd,
                                    sum(conversations) conversations, sum(escalations) escalations, avg(first_response_p50_s) first_response_p50_s, avg(csat_avg) csat
                             FROM kpis_daily WHERE day > current_date - $1::int GROUP BY market_code ORDER BY market_code""", days)
    decisions = await db.fetch("SELECT id, kind, context, recommendation, amount_usd, market_code, requested_by, created_at FROM decisions WHERE status = 'pending' ORDER BY created_at")
    escalations = await db.fetch("SELECT id, trigger_id, severity, summary, status, opened_at FROM escalations WHERE status <> 'resolved' ORDER BY opened_at")
    issues = await db.fetch("SELECT id, kind, severity, title, status, due_at FROM issues WHERE status NOT IN ('resolved','cancelled') ORDER BY array_position(ARRAY['critical','high','medium','low'], severity), due_at LIMIT 20")
    ar = await db.fetch("SELECT invoice_no, amount_usd - paid_usd AS open_usd, days_overdue, display_name FROM v_receivables_open WHERE days_overdue > 0 ORDER BY days_overdue DESC LIMIT 15")
    cash = await db.fetchrow("SELECT day, closing_usd, forecast_30d_usd FROM cashflow_daily WHERE closing_usd IS NOT NULL ORDER BY day DESC LIMIT 1")
    pipeline = await db.fetch("SELECT stage, count(*) n FROM partner_agencies GROUP BY 1 ORDER BY 1")
    findings = await db.fetch("SELECT area, severity, title, recommendation, status FROM audit_findings WHERE status = 'open' ORDER BY day DESC, array_position(ARRAY['critical','high','medium','low'], severity) LIMIT 10")
    agents = await db.fetch("""SELECT agent, count(*) runs, coalesce(sum(cost_usd),0) cost_usd, count(*) FILTER (WHERE status <> 'ok') errors, max(created_at) last_run
                               FROM agent_runs WHERE created_at >= current_date GROUP BY agent ORDER BY agent""")
    paused = [k.split(":", 1)[1] for k in await bus.client().keys("agent_paused:*")]
    return ok({"days": days, "kpis": kpis, "pending_decisions": decisions, "open_escalations": escalations, "open_issues": issues,
               "overdue_receivables": ar, "cash": cash, "prospecting_pipeline": pipeline, "audit_findings_open": findings, "agents_today": agents, "agents_paused": paused})


@tool("department_status", "Estado de um departamento (config/departments.yaml): missão, agentes, execuções e custo de hoje, erros, última execução, tarefas que aceitam.", {"department": str})
async def department_status(args: dict[str, Any]) -> dict[str, Any]:
    dep = DEPARTMENTS["departments"].get(args["department"])
    if not dep:
        return err(f"departamento desconhecido; válidos: {', '.join(DEPARTMENTS['departments'])}")
    runs = await db.fetch("""SELECT agent, count(*) runs, coalesce(sum(cost_usd),0) cost_usd, count(*) FILTER (WHERE status <> 'ok') errors, max(created_at) last_run
                             FROM agent_runs WHERE created_at >= current_date AND agent = ANY($1::text[]) GROUP BY agent""", dep["agents"])
    return ok({**dep, "today": runs, "delegable": {a: DELEGABLE.get(a, {}) for a in dep["agents"]}})


@tool("delegate_task", "Delega uma tarefa a um agente de departamento (fila de tasks). agent/task conforme department_status → delegable. note = instrução em texto para o agente; text = documento a revisar (Jurídico). O Jev escolhe o modelo (fast|work|strategy) pela complexidade. O Auditor NÃO é delegável.", {"agent": str, "task": str, "market_code": str, "note": str, "lead_id": str, "partner_id": str, "text": str})
async def delegate_task(args: dict[str, Any]) -> dict[str, Any]:
    agent, task = args["agent"], args["task"]
    if agent not in DEPARTMENTS["delegation"]["ceo"]:
        return err(f"'{agent}' não é delegável pelo gabinete (independência do Auditor ou agente inexistente)")
    if task not in DELEGABLE.get(agent, {}):
        return err(f"tarefa '{task}' não existe em {agent}; opções: {', '.join(DELEGABLE.get(agent, {}))}")
    tier = await jev.route_model(f"{agent}.{task}: {args.get('note', '')}")
    payload = {"agent": agent, "task": task, "market_code": args.get("market_code"), "note": args.get("note", ""), "delegated_by": "ceo", "tier_hint": tier}
    for key in ("lead_id", "partner_id", "text"):
        if args.get(key):
            payload[key] = args[key]
    msg_id = await bus.publish(bus.TASKS, payload)
    return ok({"queued": True, "id": msg_id, "tier_hint": tier})


@tool("recent_runs", "Últimas execuções de um agente (ou de todos) com resumo de entrada/saída, custo e erro — para o CEO perguntar 'o que o marketing fez hoje?'.", {"agent": str, "limit": int})
async def recent_runs(args: dict[str, Any]) -> dict[str, Any]:
    rows = await db.fetch("""SELECT agent, trigger, market_code, status, cost_usd, duration_ms, left(input_summary, 200) input, left(output_summary, 400) output, error, created_at
                             FROM agent_runs WHERE ($1::text IS NULL OR agent = $1) ORDER BY created_at DESC LIMIT $2""", args.get("agent"), int(args.get("limit") or 20))
    return ok(rows)


@tool("pause_agent", "Pausa (ou retoma) um agente: a máquina não executa tarefas dele até retomar. Nunca pause consultant ou escalation_router (o cliente não espera).", {"agent": str, "paused": bool, "reason": str})
async def pause_agent(args: dict[str, Any]) -> dict[str, Any]:
    if args["agent"] in ("consultant", "escalation_router") and args.get("paused", True):
        return err("atendimento não pode ser pausado")
    key = f"agent_paused:{args['agent']}"
    if args.get("paused", True):
        await bus.client().set(key, args.get("reason") or "pausado pelo CEO", ex=7 * 24 * 3600)
    else:
        await bus.client().delete(key)
    return ok({"agent": args["agent"], "paused": bool(args.get("paused", True))})


@tool("decide", "Aprova ou recusa uma decisão pendente em nome do CEO humano (só quando ele mandou no chat). make_rule transforma em regra permanente.", {"decision_id": str, "approve": bool, "note": str, "make_rule": bool, "rule_scope": str})
async def decide(args: dict[str, Any]) -> dict[str, Any]:
    status = "approved" if args["approve"] else "rejected"
    row = await db.fetchrow("UPDATE decisions SET status = $2, decided_by = 'ceo:chat', decided_at = now(), becomes_rule = $3 WHERE id = $1 AND status = 'pending' RETURNING kind, context",
                            args["decision_id"], status, bool(args.get("make_rule")))
    if not row:
        return err("decisão não encontrada ou já decidida")
    if args.get("make_rule"):
        await db.execute("INSERT INTO rules (scope, rule, origin_decision_id) VALUES ($1,$2,$3)", args.get("rule_scope") or "pricing",
                         f"{row['kind']}: {status} — {args.get('note') or row['context'][:200]}", args["decision_id"])
    return ok({"decision_id": args["decision_id"], "status": status})


@tool("search_everything", "Busca livre em leads, reservas, problemas, parceiros e achados por texto (nome, ref, título).", {"q": str})
async def search_everything(args: dict[str, Any]) -> dict[str, Any]:
    q = f"%{args['q']}%"
    leads = await db.fetch("SELECT id, display_name, market_code, stage, channel FROM leads WHERE display_name ILIKE $1 OR email ILIKE $1 OR phone ILIKE $1 LIMIT 10", q)
    bookings = await db.fetch("SELECT id, ref, status, total_usd, travel_start FROM bookings WHERE ref ILIKE $1 LIMIT 10", q)
    issues = await db.fetch("SELECT id, title, severity, status FROM issues WHERE title ILIKE $1 OR detail ILIKE $1 LIMIT 10", q)
    partners = await db.fetch("SELECT id, name, country, stage FROM partner_agencies WHERE name ILIKE $1 LIMIT 10", q)
    return ok({"leads": leads, "bookings": bookings, "issues": issues, "partners": partners})


def server():
    return create_sdk_mcp_server(SERVER, "1.0.0", [company_snapshot, department_status, delegate_task, recent_runs, pause_agent, decide, search_everything])
