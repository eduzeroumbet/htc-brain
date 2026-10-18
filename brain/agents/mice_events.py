"""MICE & Eventos — Sonnet. Grupos corporativos, incentivos, feiras (DWTC/Expo City), casamentos e galas pela HCB1 Events Management LLC.
Qualifica o RFP, verifica capacidade, monta proposta com a HCB1 e acompanha até a entrega. Grupos ≥ limite passam pela CEO."""
from __future__ import annotations

from typing import Any

from brain.core.agent_base import BaseAgent
from brain.tools import catalog, crm, handoff, knowledge, mice, names, quotes


class MiceEventsAgent(BaseAgent):
    name = "mice_events"
    department = "customer_care"
    tier = "work"
    max_turns = 16
    allowed = (
        *names("mice", "open_rfp", "rfps_open", "update_rfp", "fairs_calendar", "group_capacity_check"),
        *names("crm", "find_lead", "update_lead", "conversation_history", "schedule_followup"),
        *names("catalog", "search_catalog", "seasonal_price", "low_occupancy_hotels"),
        *names("quotes", "build_quote", "render_quote_pdf"),
        *names("knowledge", "search_knowledge"),
        *names("handoff", "request_ceo_decision", "notify_ceo", "escalate_to_human"),
    )

    def tools(self) -> dict[str, Any]:
        return {"mice": mice.server(), "crm": crm.server(), "catalog": catalog.server(), "quotes": quotes.server(), "knowledge": knowledge.server(), "handoff": handoff.server()}

    async def handle_rfp(self, lead_id: str, note: str = "") -> str:
        result = await self.run(
            f"Novo pedido de grupo/evento do lead {lead_id}: {note}\n(1) conversation_history + find_lead; (2) open_rfp com o que já se sabe (pax, datas, feira, orçamento pp, requisitos); (3) group_capacity_check na data; "
            "(4) proposta preliminar em 24 h: hotel perto do venue (3 opções por faixa), transfers em grupo (fornecedor RTA), jantar/evento (HCB1), intérprete, credenciamento, apoio no local, relatório pós-evento — build_quote com itens do catálogo "
            "e 'sob consulta' para o que não existe no catálogo; (5) update_rfp(status='proposal_sent', quote_id) e a mensagem ao cliente no idioma dele (sai pelo Atendimento). "
            "Pax ≥ limite → aguarde a decisão da CEO antes de enviar preço. Responda com o resumo do RFP e a proposta.",
            trigger="event")
        return result.text

    async def weekly_pipeline(self) -> str:
        result = await self.run(
            "Pipeline MICE semanal. rfps_open: para cada RFP, próxima ação (follow-up, revisão de proposta, bloqueio de hotel, decisão pendente); evento em ≤ 21 dias sem 'won' → fechar ou perder. fairs_calendar(120): feiras em 60–120 dias "
            "→ liste 3 setores/empresas-alvo por feira para a Prospecção/Marketing (pacote 'feira' com hotel perto do venue + transfers + intérprete). Responda com a tabela RFP | pax | evento | status | próxima ação + feiras.",
            trigger="cron")
        return result.text
