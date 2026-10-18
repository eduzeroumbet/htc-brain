"""Operações: KPIs para o CEO-agente/Financeiro, reservas e fornecedores, clientes em viagem, QA."""
from __future__ import annotations

from typing import Any

from brain.core import db
from brain.tools import create_sdk_mcp_server, err, ok, tool

SERVER = "ops"


@tool("kpi_snapshot", "KPIs dos últimos N dias (total e por mercado): leads, qualificados, cotações, reservas, receita, margem, mídia, tokens, escalonamentos, resposta.", {"days": int})
async def kpi_snapshot(args: dict[str, Any]) -> dict[str, Any]:
    days = int(args.get("days") or 7)
    await db.rollup_kpis()
    rows = await db.fetch(
        """SELECT market_code, sum(leads_new) leads, sum(leads_qualified) qualified, sum(quotes_sent) quotes, sum(bookings) bookings,
                  sum(revenue_usd) revenue_usd, sum(margin_usd) margin_usd, sum(ad_spend_usd) ad_spend_usd, sum(token_cost_usd) token_cost_usd,
                  sum(conversations) conversations, sum(escalations) escalations, avg(first_response_p50_s) first_response_p50_s, avg(csat_avg) csat
           FROM kpis_daily WHERE day > current_date - $1::int GROUP BY market_code ORDER BY market_code""",
        days,
    )
    return ok({"days": days, "rows": rows})


@tool("pending_decisions", "Decisões aguardando o CEO.", {})
async def pending_decisions(args: dict[str, Any]) -> dict[str, Any]:
    rows = await db.fetch("SELECT id, kind, context, recommendation, requested_by, amount_usd, market_code, created_at FROM decisions WHERE status = 'pending' ORDER BY created_at")
    return ok(rows)


@tool("open_escalations", "Escalonamentos abertos e há quanto tempo.", {})
async def open_escalations(args: dict[str, Any]) -> dict[str, Any]:
    rows = await db.fetch(
        """SELECT e.id, e.trigger_id, e.severity, e.summary, e.status, e.opened_at, extract(epoch from now()-e.opened_at)/60 AS minutes_open,
                  l.display_name, l.market_code
           FROM escalations e JOIN leads l ON l.id = e.lead_id WHERE e.status <> 'resolved' ORDER BY e.opened_at""")
    return ok(rows)


@tool("bookings_to_confirm", "Reservas em 'confirming' com itens e fornecedor para confirmar.", {})
async def bookings_to_confirm(args: dict[str, Any]) -> dict[str, Any]:
    rows = await db.fetch(
        """SELECT b.id, b.ref, b.market_code, b.travel_start, b.items, b.supplier_confirmations, b.created_at,
                  extract(epoch from now()-b.created_at)/60 AS minutes_waiting
           FROM bookings b WHERE b.status = 'confirming' ORDER BY b.created_at""")
    return ok(rows)


@tool("record_supplier_confirmation", "Registra confirmação de um item pelo fornecedor (ou falha). Quando todos os itens confirmam, a reserva vira 'confirmed'.", {"booking_id": str, "catalog_item_id": str, "confirmed": bool, "supplier_ref": str, "note": str})
async def record_supplier_confirmation(args: dict[str, Any]) -> dict[str, Any]:
    b = await db.fetchrow("SELECT items, supplier_confirmations FROM bookings WHERE id = $1", args["booking_id"])
    if not b:
        return err("reserva não encontrada")
    confs = [c for c in (b["supplier_confirmations"] or []) if c.get("catalog_item_id") != args["catalog_item_id"]]
    confs.append({"catalog_item_id": args["catalog_item_id"], "confirmed": bool(args.get("confirmed")),
                  "supplier_ref": args.get("supplier_ref"), "note": args.get("note")})
    all_ok = all(any(c["catalog_item_id"] == i["catalog_item_id"] and c["confirmed"] for c in confs) for i in b["items"])
    status = "confirmed" if all_ok else "confirming"
    await db.execute("UPDATE bookings SET supplier_confirmations = $2, status = $3, confirmed_at = CASE WHEN $3 = 'confirmed' THEN coalesce(confirmed_at, now()) ELSE confirmed_at END, updated_at = now() WHERE id = $1", args["booking_id"], confs, status)
    return ok({"booking_id": args["booking_id"], "status": status, "confirmations": confs})


@tool("attach_voucher", "Anexa voucher (URL) a uma reserva.", {"booking_id": str, "catalog_item_id": str, "url": str})
async def attach_voucher(args: dict[str, Any]) -> dict[str, Any]:
    await db.execute("UPDATE bookings SET vouchers = vouchers || $2::jsonb WHERE id = $1", args["booking_id"],
                     [{"catalog_item_id": args.get("catalog_item_id"), "url": args["url"]}])
    return ok({"attached": True})


@tool("clients_in_trip", "Clientes com viagem entre D-1 e D+1 do fim (para o Concierge): reserva, itens, contatos.", {})
async def clients_in_trip(args: dict[str, Any]) -> dict[str, Any]:
    rows = await db.fetch(
        """SELECT b.id AS booking_id, b.ref, b.market_code, b.travel_start, b.travel_end, b.items, b.vouchers, b.status,
                  l.id AS lead_id, l.display_name, l.channel, l.channel_user_id, l.language
           FROM bookings b JOIN leads l ON l.id = b.lead_id
           WHERE b.status IN ('confirmed','in_trip') AND b.travel_start <= current_date + 1 AND b.travel_end >= current_date - 1
           ORDER BY b.travel_start""")
    return ok(rows)


@tool("set_booking_status", "Atualiza status da reserva: confirmed|in_trip|completed|cancelled.", {"booking_id": str, "status": str})
async def set_booking_status(args: dict[str, Any]) -> dict[str, Any]:
    if args["status"] not in ("confirmed", "in_trip", "completed", "cancelled"):
        return err("status inválido")
    await db.execute("UPDATE bookings SET status = $2 WHERE id = $1", args["booking_id"], args["status"])
    return ok({"booking_id": args["booking_id"], "status": args["status"]})


@tool("sample_conversations", "Amostra aleatória de conversas fechadas/ativas das últimas 24h para QA (com mensagens).", {"limit": int, "market_code": str})
async def sample_conversations(args: dict[str, Any]) -> dict[str, Any]:
    convs = await db.fetch(
        """SELECT c.id, c.status, c.first_response_ms, c.csat, l.market_code, l.display_name
           FROM conversations c JOIN leads l ON l.id = c.lead_id
           WHERE c.last_message_at > now() - interval '24 hours' AND ($2::text IS NULL OR l.market_code = $2)
           ORDER BY random() LIMIT $1""",
        int(args.get("limit") or 10), args.get("market_code"),
    )
    for c in convs:
        c["messages"] = await db.fetch("SELECT direction, author, body, created_at FROM messages WHERE conversation_id = $1 ORDER BY created_at LIMIT 40", c["id"])
    return ok(convs)


@tool("record_qa_score", "Registra a nota de QA de uma conversa ou peça (0-10) com observações; alimenta o dashboard e o roteador de melhorias.", {"target_kind": str, "target_id": str, "score": float, "issues": str})
async def record_qa_score(args: dict[str, Any]) -> dict[str, Any]:
    await db.execute("INSERT INTO qa_scores (target_kind, target_id, score, issues) VALUES ($1,$2,$3,$4)",
                     args["target_kind"], args["target_id"], float(args["score"]), args.get("issues"))
    return ok({"recorded": True})


@tool("record_rule", "Transforma uma decisão do CEO em regra permanente (scope: pricing|media|content|escalation|supplier).", {"scope": str, "rule": str, "origin_decision_id": str})
async def record_rule(args: dict[str, Any]) -> dict[str, Any]:
    await db.execute("INSERT INTO rules (scope, rule, origin_decision_id) VALUES ($1,$2,$3)", args["scope"], args["rule"], args.get("origin_decision_id"))
    return ok({"recorded": True})


@tool("active_rules", "Regras ativas por escopo — leia antes de decidir preço, mídia ou conteúdo.", {"scope": str})
async def active_rules(args: dict[str, Any]) -> dict[str, Any]:
    rows = await db.fetch("SELECT scope, rule, created_at FROM rules WHERE active AND ($1::text IS NULL OR scope = $1) ORDER BY created_at", args.get("scope"))
    return ok(rows)


def server():
    return create_sdk_mcp_server(SERVER, "1.0.0", [
        kpi_snapshot, pending_decisions, open_escalations, bookings_to_confirm, record_supplier_confirmation, attach_voucher,
        clients_in_trip, set_booking_status, sample_conversations, record_qa_score, record_rule, active_rules,
    ])
