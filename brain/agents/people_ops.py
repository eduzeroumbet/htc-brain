"""Pessoas — Sonnet. Gere os humanos que ficam: escala de folgas, documentos (visto, labour card, TGD), ocorrências e avaliações,
pool de guias freelancers, pacote mensal para folha/WPS e PRO. Nunca decide contratação, dispensa ou salário — prepara para a CEO."""
from __future__ import annotations

from datetime import date
from typing import Any

from brain.core.agent_base import BaseAgent
from brain.tools import handoff, knowledge, names, people, prospects


class PeopleOpsAgent(BaseAgent):
    name = "people_ops"
    department = "operations"
    tier = "work"
    max_turns = 14
    allowed = (
        *names("people", "staff_overview", "update_staff", "plan_leave", "leave_calendar", "record_staff_event", "guide_pool", "upsert_guide_candidate", "payroll_pack"),
        *names("knowledge", "search_knowledge"),
        *names("prospects", "web_search"),
        *names("handoff", "request_ceo_decision", "notify_ceo"),
    )

    def tools(self) -> dict[str, Any]:
        return {"people": people.server(), "knowledge": knowledge.server(), "prospects": prospects.server(), "handoff": handoff.server()}

    async def weekly_people(self) -> str:
        result = await self.run(
            "Rotina semanal de pessoas. (1) staff_overview(60): documento vencendo ≤ 60 dias → preparar pedido ao PRO (texto pronto) e notify_ceo se ≤ 30; (2) leave_calendar(30) + plan_leave: garanta 4 folgas/mês por motorista "
            "sem os dois no mesmo dia em alta temporada; proponha as datas do mês seguinte até o dia 20; (3) ocorrências dos últimos 7 dias (elogios do concierge, reclamações, multas) → record_staff_event; 2 reclamações no mês → "
            "request_ceo_decision(kind='people'); (4) guide_pool: idiomas com < 2 guias ativos (pt, ru, de, hi, zh) → buscar candidatos licenciados (web_search 'licensed tour guide Dubai <idioma>') e cadastrar como 'candidate'. "
            "Responda: documentos | folgas | ocorrências | pool de guias | o que a CEO decide.",
            trigger="cron")
        return result.text

    async def monthly_payroll(self) -> str:
        month = date.today().strftime("%Y-%m")
        result = await self.run(
            f"Pacote de folha de {month}: payroll_pack → para cada funcionário: salário base, extras (AED 35/h), multas a descontar (≤ 20% do salário), folgas não gozadas; guias freelancers por diária. "
            "Escreva o resumo para a CEO aprovar e o texto para o contador/WPS. Qualquer desconto acima de 20% ou extra acima de 40 h → request_ceo_decision(kind='payroll').",
            trigger="cron")
        return result.text
