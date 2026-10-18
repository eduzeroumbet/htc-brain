"""Frota & Motoristas — Sonnet. Planeja e despacha o campo: carros, motoristas, guias; horas, multas, manutenção."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from brain.core.agent_base import BaseAgent
from brain.tools import crm, fleet, handoff, names, ops, people, resolution


class FleetDispatcherAgent(BaseAgent):
    name = "fleet_dispatcher"
    department = "operations"
    tier = "work"
    max_turns = 16
    allowed = (
        *names("fleet", "fleet_status", "services_for_date", "bookings_needing_field_services", "choose_vehicle", "create_assignment",
               "send_daily_agenda", "update_assignment_status", "log_driver_hours", "monthly_driver_payroll_input", "record_vehicle_event", "check_rta_fines"),
        *names("ops", "clients_in_trip", "active_rules"),
        *names("crm", "find_lead"),
        *names("resolution", "open_issues", "staff_schedule_for_date", "assign_issue_to_staff"),
        *names("people", "leave_calendar"),
        *names("handoff", "escalate_to_human", "request_ceo_decision", "notify_ceo"),
    )

    def tools(self) -> dict[str, Any]:
        return {"fleet": fleet.server(), "ops": ops.server(), "crm": crm.server(), "resolution": resolution.server(), "people": people.server(), "handoff": handoff.server()}

    async def plan_tomorrow(self) -> str:
        tomorrow = str(date.today() + timedelta(days=1))
        result = await self.run(
            f"Planeje o campo de {tomorrow}. (1) fleet_status, leave_calendar(7) (folgas aprovadas — motorista de folga não entra na agenda) e services_for_date('{tomorrow}'). (2) bookings_needing_field_services(days_ahead=2): "
            "para cada reserva com transfer, tour, meet & greet ou visita à mesquita, crie os serviços com create_assignment — escolha o carro com "
            "choose_vehicle (pax, malas, vip), respeite 12 h/dia e as folgas dos motoristas, atribua guia licenciado quando o item pedir guia, "
            "e escreva um briefing curto (perfil, idioma, restrições, pedidos especiais, abaya se mesquita). VIP → Escalade e, se acima do limiar, "
            "meet & greet presencial. (3) Se faltar carro ou motorista, use frota terceirizada e registre. (4) send_daily_agenda('{tomorrow}'). "
            "(5) Se alguma Mulkiya, seguro, visto ou TGD vence em ≤ 30 dias ou km_to_service ≤ 500, notify_ceo(severity='medium'). "
            f"(6) Programação do pessoal de resolução: open_issues() com status 'assigned_human' ou que exigem presença em {tomorrow} → garanta que cada um tem "
            f"assign_issue_to_staff com hora e local; staff_schedule_for_date('{tomorrow}') para conferir e evitar choque de horários com os serviços de campo. "
            "Responda com a agenda em tabela: hora | serviço | cliente | pax/malas | carro | motorista | guia | pessoal de resolução.",
            trigger="cron",
        )
        return result.text

    async def weekly_fleet_admin(self) -> str:
        result = await self.run(
            "Rotina semanal de frota. (1) check_rta_fines para cada placa e record_vehicle_event(kind='fine', deduct_from_driver=true) quando houver "
            "motorista identificado pelo horário do serviço. (2) Para cada motorista, log_driver_hours dos últimos 7 dias a partir dos serviços "
            "(started_at/finished_at) quando não houver GPS. (3) Veículo com km_to_service ≤ 500 → agendar revisão (registrar 'service' quando feita) e avisar. "
            "(4) Salik/ENOC/DARB: registrar recargas informadas. Responda com um resumo de 6 linhas.",
            trigger="cron",
        )
        return result.text

    async def monthly_payroll_input(self) -> str:
        month = date.today().strftime("%Y-%m")
        result = await self.run(
            f"Prepare o insumo da folha dos motoristas de {month} com monthly_driver_payroll_input e explique em 5 linhas para o Financeiro: horas regulares, "
            "extras (AED 35/h fora do horário), multas a descontar respeitando o teto de 20% do salário em WPS e o saldo que fica para o mês seguinte.",
            trigger="cron",
        )
        return result.text
