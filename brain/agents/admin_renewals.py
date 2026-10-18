"""Admin & Renovações — Haiku. Calendário de licenças, seguros, contratos e vistos; inventário de presentes e abayas; compras."""
from __future__ import annotations

from typing import Any

from brain.core.agent_base import BaseAgent
from brain.tools import admin, handoff, names, ops


class AdminRenewalsAgent(BaseAgent):
    name = "admin_renewals"
    department = "operations"
    tier = "fast"
    max_turns = 10
    allowed = (
        *names("admin", "sync_renewals_from_config", "upcoming_renewals", "set_renewal_status", "inventory_levels", "inventory_move", "gift_plan_for_booking", "request_quotes_by_email"),
        *names("ops", "clients_in_trip"),
        *names("handoff", "notify_ceo", "request_ceo_decision"),
    )

    def tools(self) -> dict[str, Any]:
        return {"admin": admin.server(), "ops": ops.server(), "handoff": handoff.server()}

    async def weekly_review(self) -> str:
        result = await self.run(
            "Rotina semanal. (1) sync_renewals_from_config. (2) upcoming_renewals(90): para cada item, classifique em 90/60/30/7 dias. "
            "Com 90 dias: seguros e contratos → request_quotes_by_email a até 3 fornecedores (texto formal em inglês, com dados da empresa, sem credenciais). "
            "Com 60 dias: licenças e Mulkiya → notify_ceo com a lista de documentos necessários. Com 30 dias ou vencido: notify_ceo(severity='high'). "
            "Decisões de negócio (renovar a sala 1701, cancelar contrato) → request_ceo_decision. (3) inventory_levels: itens abaixo do mínimo viram lista "
            "de compras por loja (Day-to-Day/Gift Village, Dragon Mart, Amazon, Carrefour) para o motorista em dia de baixa. "
            "Responda com duas tabelas: renovações (item | vence | dias | ação tomada) e compras.",
            trigger="cron",
        )
        return result.text

    async def gifts_for_arrivals(self) -> str:
        result = await self.run(
            "Para cada cliente em clients_in_trip que chega em ≤ 2 dias, monte o plano de presentes com gift_plan_for_booking, faça a saída no estoque "
            "com inventory_move (reason 'gift_booking:<ref>' ou 'abaya_out:<guia>') e devolva a lista por reserva para o Concierge incluir na agenda do motorista.",
            trigger="cron",
        )
        return result.text
