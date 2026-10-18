"""Financeiro — Sonnet. Custos, receitas, cobrança de clientes, alertas de pagamentos em aberto, fluxo de caixa, A/P e A/R."""
from __future__ import annotations

from typing import Any

from brain.core import db
from brain.core.agent_base import BaseAgent
from brain.tools import billing, handoff, marketing, names, ops


class FinanceAgent(BaseAgent):
    name = "finance"
    department = "finance"
    tier = "work"
    max_turns = 14
    allowed = (
        *names("ops", "kpi_snapshot", "active_rules"),
        *names("marketing", "campaign_performance", "spend_today"),
        *names("billing", "create_receivable", "open_receivables", "record_payment_received", "send_billing_reminder", "record_payable",
               "open_payables", "mark_payable_paid", "cashflow_forecast", "set_cash_closing", "costs_breakdown"),
        *names("handoff", "notify_ceo", "request_ceo_decision"),
    )

    def tools(self) -> dict[str, Any]:
        return {"ops": ops.server(), "marketing": marketing.server(), "billing": billing.server(), "handoff": handoff.server()}

    async def daily_close(self) -> str:
        await db.rollup_kpis()
        result = await self.run(
            "Fechamento do dia. Use kpi_snapshot(1), kpi_snapshot(30), costs_breakdown(30), open_receivables(), open_payables(30) e cashflow_forecast(30). "
            "Calcule: receita e margem do dia e do mês; CAC por mercado (mídia ÷ reservas); custo de tokens por reserva; ponto de equilíbrio do mês "
            "(custo fixo de config/agency.yaml → finance.fixed_cost_usd_month + mídia); projeção de reservas pelo ritmo dos últimos 7 dias; saldo projetado 30 dias "
            "(caixa + A/R a vencer − A/P a vencer). Registre com set_cash_closing(closing_usd, forecast_30d_usd, notes). "
            "Alerte com notify_ceo(severity='medium') se: margem do mês < 12%, CAC de algum mercado > 1,5x a meta por 7 dias, tokens > USD 60/dia, "
            "ou saldo projetado 30d < 1 mês de custo fixo. Responda com uma tabela compacta.",
            trigger="cron")
        return result.text

    async def receivables_alerts(self) -> str:
        result = await self.run(
            "Cobrança e contas a receber (09:00). open_receivables(): (1) para cada fatura vencida ou que vence em ≤ 3 dias sem pagamento, escreva o lembrete no idioma "
            "do mercado do cliente — curto, cordial, com valor, vencimento e link de pagamento; tom por jev_risk (baixo: lembrete leve; alto: prazo final e consequência "
            "da política: liberação de reserva/cancelamento) — e envie com send_billing_reminder. (2) Saldo de pacote (70%) não pago a 14 dias da viagem: lembrete + "
            "open_issue não é seu — avise o Operacional via request_ceo_decision só se a viagem está em ≤ 5 dias e não há pagamento. (3) Fatura > 7 dias vencida e "
            "> USD 1.000 → notify_ceo(severity='medium'). (4) Reservas confirmadas sem fatura: create_receivable (depósito 30% à vista, saldo D-14). "
            "Responda com a tabela fatura | cliente | dias | ação.",
            trigger="cron")
        return result.text

    async def weekly_cashflow(self) -> str:
        result = await self.run(
            "Fluxo de caixa semanal (segunda). cashflow_forecast(90), open_payables(60), costs_breakdown(90). Mostre: entradas/saídas das últimas 4 semanas, A/R e A/P por "
            "semana nas próximas 8, semanas com saldo negativo e o que fazer (antecipar cobrança, renegociar fornecedor, pausar mídia). Contas a pagar fixas do mês "
            "(aluguel, licença DET, seguro, folha WPS, Mulkiya, renovações de config/renewals_hcte.yaml) que ainda não estão em payables: record_payable com a data. "
            "Resumo ≤ 12 linhas + notify_ceo(severity='low') com 3 linhas.",
            trigger="cron")
        return result.text

    async def on_payment_event(self, booking_id: str, amount_usd: float, kind: str) -> None:
        """Webhook de pagamento → baixa a fatura correspondente sem LLM."""
        r = await db.fetchrow("SELECT id FROM receivables WHERE booking_id = $1 AND status IN ('open','partially_paid','overdue') ORDER BY due_at LIMIT 1", booking_id)
        if r and kind == "charge":
            from brain.tools.billing import record_payment_received
            await record_payment_received({"receivable_id": str(r["id"]), "amount_usd": amount_usd})
