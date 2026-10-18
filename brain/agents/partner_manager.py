"""Gestor de Parceiras B2B — Sonnet. Onboarding, cotações com net rate para agências, reservas de parceiras, extrato de comissão, saúde da relação."""
from __future__ import annotations

from datetime import date
from typing import Any

from brain.core.agent_base import BaseAgent
from brain.tools import catalog, handoff, knowledge, names, partners, quotes


class PartnerManagerAgent(BaseAgent):
    name = "partner_manager"
    department = "prospecting"
    tier = "work"
    max_turns = 16
    allowed = (
        *names("partners", "active_partners", "onboard_partner", "partner_quote_context", "tag_quote_partner", "sync_partner_bookings", "commission_statement", "partner_health", "message_partner"),
        *names("quotes", "build_quote", "render_quote_pdf"),
        *names("catalog", "search_catalog", "seasonal_price", "low_occupancy_hotels"),
        *names("knowledge", "search_knowledge"),
        *names("handoff", "request_ceo_decision", "notify_ceo"),
    )

    def tools(self) -> dict[str, Any]:
        return {"partners": partners.server(), "quotes": quotes.server(), "catalog": catalog.server(), "knowledge": knowledge.server(), "handoff": handoff.server()}

    async def partner_quote(self, partner_id: str, note: str = "") -> str:
        result = await self.run(
            f"Cotação B2B para a parceira {partner_id}: {note}\npartner_quote_context → monte com search_catalog/seasonal_price (hotéis com ocupação baixa primeiro) → build_quote → tag_quote_partner(pricing_mode) → render_quote_pdf. "
            "Mostre à agência: preço por passageiro conforme o modo (net ou comissionável), o que inclui/exclui, política de cancelamento, validade 7 dias, e o texto pronto no idioma dela (message_partner). SLA: 15 min.",
            trigger="task")
        return result.text

    async def weekly_care(self) -> str:
        result = await self.run(
            "Cuidado semanal das parceiras. sync_partner_bookings; partner_health → para cada uma em 'attention': mensagem curta e útil no idioma dela (novidade de produto, 'Dubai agora' com fonte, oferta de hotel com ocupação baixa, ou simplesmente "
            "perguntar o que travou) via message_partner. Parceira nova sem onboarding completo → onboard_partner e checklist. Responda com a tabela parceira | saúde | ação.",
            trigger="cron")
        return result.text

    async def monthly_statements(self) -> str:
        period = (date.today().replace(day=1)).strftime("%Y-%m") if date.today().day > 3 else None
        prev = date.today().replace(day=1)
        prev = (prev.replace(month=prev.month - 1) if prev.month > 1 else prev.replace(year=prev.year - 1, month=12)).strftime("%Y-%m")
        result = await self.run(
            f"Extratos de comissão do período {prev}. Para cada parceira em active_partners: commission_statement(partner_id, '{prev}'); se houver valor, envie o texto com message_partner(channel='email') e informe que o Financeiro paga no prazo acordado. "
            "Divergência apontada pela parceira → request_ceo_decision(kind='commission_dispute'). Responda com a tabela parceira | reservas | comissão | enviado.",
            trigger="cron")
        return result.text
