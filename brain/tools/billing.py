"""Financeiro: contas a receber (faturas e cobrança), contas a pagar, caixa e previsão. O Jev prioriza a cobrança."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from brain.core import bus, db, jev
from brain.tools import create_sdk_mcp_server, err, ok, tool

SERVER = "billing"


async def _next_invoice_no() -> str:
    row = await db.fetchrow("SELECT count(*) AS n FROM receivables WHERE created_at >= date_trunc('year', now())")
    return f"HC-{date.today().year}-{int(row['n']) + 1:06d}"  # type: ignore[index]


@tool("create_receivable", "Cria fatura/cobrança para reserva (ou parceiro B2B). due_days padrão: 0 (à vista) para depósito, 14 dias antes da viagem para saldo. Devolve invoice_no.", {"booking_id": str, "partner_id": str, "lead_id": str, "description": str, "amount_usd": float, "currency": str, "amount_local": float, "due_at": str, "payment_link": str})
async def create_receivable(args: dict[str, Any]) -> dict[str, Any]:
    inv = await _next_invoice_no()
    row = await db.fetchrow(
        """INSERT INTO receivables (booking_id, partner_id, lead_id, invoice_no, description, amount_usd, currency, amount_local, due_at, payment_link)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) RETURNING id, invoice_no, due_at""",
        args.get("booking_id"), args.get("partner_id"), args.get("lead_id"), inv, args.get("description"), float(args["amount_usd"]),
        args.get("currency") or "USD", args.get("amount_local"), date.fromisoformat(args["due_at"]) if args.get("due_at") else date.today(), args.get("payment_link"))
    return ok(row)


@tool("open_receivables", "Contas a receber abertas/vencidas com dias de atraso, cliente, mercado e lembretes já enviados. overdue_only filtra só vencidas.", {"overdue_only": bool})
async def open_receivables(args: dict[str, Any]) -> dict[str, Any]:
    rows = await db.fetch("SELECT * FROM v_receivables_open WHERE ($1::bool IS NOT TRUE OR days_overdue > 0) ORDER BY days_overdue DESC, due_at", bool(args.get("overdue_only")))
    # Jev: risco de inadimplência por fatura (uma chamada, estado compacto)
    for r in rows[:25]:
        ans = await jev.decide(
            {"days_overdue": r["days_overdue"], "amount_usd": float(r["amount_usd"]), "paid_usd": float(r["paid_usd"]), "reminders_sent": r["reminders_sent"],
             "travel_in_days": None, "market": r.get("lead_market")},
            {"risk": {"type": "score", "instructions": "Risco de não receber", "criteria": ["baixo", "médio", "alto", "muito alto"]}})
        if ans:
            r["jev_risk"] = round(ans.score("risk"), 3)
            await db.execute("UPDATE receivables SET jev_risk = $2 WHERE id = $1", r["id"], r["jev_risk"])
    return ok(rows)


@tool("record_payment_received", "Baixa (parcial ou total) de uma fatura. Atualiza status e caixa do dia.", {"receivable_id": str, "amount_usd": float, "reference": str})
async def record_payment_received(args: dict[str, Any]) -> dict[str, Any]:
    amt = float(args["amount_usd"])
    row = await db.fetchrow("UPDATE receivables SET paid_usd = paid_usd + $2 WHERE id = $1 RETURNING amount_usd, paid_usd", args["receivable_id"], amt)
    if not row:
        return err("fatura não encontrada")
    status = "paid" if float(row["paid_usd"]) >= float(row["amount_usd"]) - 0.01 else "partially_paid"
    await db.execute("UPDATE receivables SET status = $2 WHERE id = $1", args["receivable_id"], status)
    await db.execute("""INSERT INTO cashflow_daily (day, inflow_usd) VALUES (current_date, $1)
                        ON CONFLICT (day) DO UPDATE SET inflow_usd = cashflow_daily.inflow_usd + EXCLUDED.inflow_usd""", amt)
    return ok({"status": status, "paid_usd": float(row["paid_usd"])})


@tool("send_billing_reminder", "Envia lembrete de cobrança ao cliente no canal dele (texto no idioma do mercado, com link de pagamento). Máx. 1 por 48h por fatura; registra reminders_sent.", {"receivable_id": str, "text": str})
async def send_billing_reminder(args: dict[str, Any]) -> dict[str, Any]:
    r = await db.fetchrow("""SELECT r.id, r.payment_link, l.channel, l.channel_user_id FROM receivables r JOIN leads l ON l.id = r.lead_id WHERE r.id = $1""", args["receivable_id"])
    if not r:
        return err("fatura sem lead associado")
    if not await bus.rate_limit(f"billing:{r['id']}", limit=1, window_s=48 * 3600):
        return ok({"sent": False, "reason": "lembrete enviado há menos de 48h"})
    await bus.publish(bus.OUTBOUND, {"channel": r["channel"], "channel_user_id": r["channel_user_id"], "text": args["text"], "author": "ai:finance", "template_required": True})
    await db.execute("UPDATE receivables SET reminders_sent = reminders_sent + 1, last_reminder_at = now(), status = CASE WHEN due_at < current_date AND status = 'open' THEN 'overdue' ELSE status END WHERE id = $1", r["id"])
    return ok({"sent": True})


@tool("record_payable", "Registra conta a pagar (fornecedor, folha, aluguel, licença, seguro, mídia, tokens, combustível).", {"supplier_id": str, "booking_id": str, "category": str, "description": str, "amount_usd": float, "currency": str, "amount_local": float, "due_at": str, "reference": str})
async def record_payable(args: dict[str, Any]) -> dict[str, Any]:
    row = await db.fetchrow(
        """INSERT INTO payables (supplier_id, booking_id, category, description, amount_usd, currency, amount_local, due_at, reference)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING id""",
        args.get("supplier_id"), args.get("booking_id"), args["category"], args.get("description"), float(args["amount_usd"]),
        args.get("currency") or "AED", args.get("amount_local"), date.fromisoformat(args["due_at"]), args.get("reference"))
    return ok(row)


@tool("open_payables", "Contas a pagar abertas nos próximos N dias (padrão 30) e vencidas, por categoria.", {"days": int})
async def open_payables(args: dict[str, Any]) -> dict[str, Any]:
    rows = await db.fetch("SELECT *, (due_at - current_date) AS days_to_due FROM payables WHERE status IN ('open','scheduled','overdue') AND due_at <= current_date + $1::int ORDER BY due_at", int(args.get("days") or 30))
    return ok(rows)


@tool("mark_payable_paid", "Marca conta a pagar como paga (ou scheduled/disputed) e lança no caixa.", {"payable_id": str, "status": str, "reference": str})
async def mark_payable_paid(args: dict[str, Any]) -> dict[str, Any]:
    status = args.get("status") or "paid"
    row = await db.fetchrow("UPDATE payables SET status = $2, paid_at = CASE WHEN $2 = 'paid' THEN now() ELSE paid_at END, reference = COALESCE($3, reference) WHERE id = $1 RETURNING amount_usd", args["payable_id"], status, args.get("reference"))
    if row and status == "paid":
        await db.execute("""INSERT INTO cashflow_daily (day, outflow_usd) VALUES (current_date, $1)
                            ON CONFLICT (day) DO UPDATE SET outflow_usd = cashflow_daily.outflow_usd + EXCLUDED.outflow_usd""", float(row["amount_usd"]))
    return ok({"status": status})


@tool("cashflow_forecast", "Caixa: entradas/saídas dos últimos N dias, a receber e a pagar por semana nas próximas 8 semanas, saldo projetado. Inclui custo fixo estimado (config/agency.yaml → finance.fixed_cost_usd_month).", {"days_back": int})
async def cashflow_forecast(args: dict[str, Any]) -> dict[str, Any]:
    days = int(args.get("days_back") or 30)
    hist = await db.fetch("SELECT day, inflow_usd, outflow_usd, closing_usd FROM cashflow_daily WHERE day > current_date - $1::int ORDER BY day", days)
    ar = await db.fetch("""SELECT date_trunc('week', due_at)::date AS week, sum(amount_usd - paid_usd) AS usd FROM receivables
                           WHERE status IN ('open','partially_paid','overdue') AND due_at <= current_date + 56 GROUP BY 1 ORDER BY 1""")
    ap = await db.fetch("""SELECT date_trunc('week', due_at)::date AS week, sum(amount_usd) AS usd FROM payables
                           WHERE status IN ('open','scheduled','overdue') AND due_at <= current_date + 56 GROUP BY 1 ORDER BY 1""")
    last = await db.fetchrow("SELECT closing_usd FROM cashflow_daily WHERE closing_usd IS NOT NULL ORDER BY day DESC LIMIT 1")
    return ok({"history": hist, "receivables_by_week": ar, "payables_by_week": ap, "last_closing_usd": (last or {}).get("closing_usd")})


@tool("set_cash_closing", "Registra o saldo de fechamento do dia (e a previsão 30d) — chamado no daily_close.", {"day": str, "closing_usd": float, "forecast_30d_usd": float, "notes": str})
async def set_cash_closing(args: dict[str, Any]) -> dict[str, Any]:
    d = date.fromisoformat(args["day"]) if args.get("day") else date.today()
    await db.execute("""INSERT INTO cashflow_daily (day, closing_usd, forecast_30d_usd, notes) VALUES ($1,$2,$3,$4)
                        ON CONFLICT (day) DO UPDATE SET closing_usd = EXCLUDED.closing_usd, forecast_30d_usd = EXCLUDED.forecast_30d_usd, notes = EXCLUDED.notes""",
                     d, args.get("closing_usd"), args.get("forecast_30d_usd"), args.get("notes"))
    return ok({"day": str(d)})


@tool("costs_breakdown", "Custos dos últimos N dias por categoria: mídia (ad_spend_daily), tokens (agent_runs), fornecedores/folha/outros (payables pagos).", {"days": int})
async def costs_breakdown(args: dict[str, Any]) -> dict[str, Any]:
    days = int(args.get("days") or 30)
    media = await db.fetchrow("SELECT coalesce(sum(spend_usd),0) usd FROM ad_spend_daily WHERE day > current_date - $1::int", days)
    tokens = await db.fetchrow("SELECT coalesce(sum(cost_usd),0) usd FROM agent_runs WHERE created_at > now() - ($1 || ' days')::interval", str(days))
    other = await db.fetch("SELECT category, sum(amount_usd) usd FROM payables WHERE status = 'paid' AND paid_at > now() - ($1 || ' days')::interval GROUP BY 1 ORDER BY 2 DESC", str(days))
    return ok({"days": days, "media_usd": media["usd"], "tokens_usd": tokens["usd"], "payables_paid": other})  # type: ignore[index]


def server():
    return create_sdk_mcp_server(SERVER, "1.0.0", [create_receivable, open_receivables, record_payment_received, send_billing_reminder, record_payable,
                                                   open_payables, mark_payable_paid, cashflow_forecast, set_cash_closing, costs_breakdown])
