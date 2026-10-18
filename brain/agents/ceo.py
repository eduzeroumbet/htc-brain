"""CEO (gabinete) — Opus. A voz da empresa para o CEO humano: responde no chat do dashboard com todos os dados,
delega tarefas aos departamentos, apresenta números, gere os outros agentes. Briefing 07:00 e aprovações dentro das regras."""
from __future__ import annotations

import json
import re
from typing import Any

from brain.core import db
from brain.core.agent_base import BaseAgent
from brain.tools import company, handoff, names, ops


class CEOAgent(BaseAgent):
    name = "ceo"
    department = "ceo_office"
    tier = "strategy"
    max_turns = 14
    allowed = (
        *names("company", "company_snapshot", "department_status", "delegate_task", "recent_runs", "pause_agent", "decide", "search_everything"),
        *names("ops", "kpi_snapshot", "pending_decisions", "open_escalations", "active_rules", "record_rule"),
        *names("handoff", "notify_ceo", "request_ceo_decision"),
    )

    def tools(self) -> dict[str, Any]:
        return {"company": company.server(), "ops": ops.server(), "handoff": handoff.server()}

    async def chat(self, message: str) -> dict[str, Any]:
        """Uma mensagem do CEO humano no dashboard → resposta + delegações disparadas. Mantém a sessão do SDK entre mensagens."""
        last = await db.fetchrow("SELECT session_id FROM ceo_chat WHERE session_id IS NOT NULL ORDER BY created_at DESC LIMIT 1")
        await db.execute("INSERT INTO ceo_chat (role, body) VALUES ('user', $1)", message)
        result = await self.run(
            f"[chat do dashboard — mensagem da CEO humana]\n{message}\n\n"
            "Responda em português, direto, com números quando houver. Se a mensagem pede uma ação de um departamento, use delegate_task e diga o que foi "
            "disparado e quando haverá resultado. Se pede decisão sobre algo pendente, use decide. Termine com DELEGAÇÕES: [...] em JSON (lista vazia se nenhuma).",
            trigger="chat", resume_session=(last or {}).get("session_id"))
        text = result.text or "Não consegui responder agora. Tente de novo em instantes."
        delegations: list[dict[str, Any]] = []
        m = re.search(r"DELEGAÇÕES:\s*(\[.*\])", text, re.S)
        if m:
            try:
                delegations = json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
            text = text[: m.start()].rstrip()
        await db.execute("INSERT INTO ceo_chat (role, body, session_id, cost_usd, delegations) VALUES ('assistant', $1, $2, $3, $4)",
                         text, result.session_id, result.cost_usd, delegations)
        return {"reply": text, "delegations": delegations, "cost_usd": result.cost_usd}

    async def ceo_briefing(self) -> str:
        result = await self.run(
            "Prepare o briefing diário do CEO (WhatsApp, máximo 900 caracteres, português) a partir de company_snapshot(7): "
            "3 números que importam hoje (com variação vs. 7 dias), 3 decisões pendentes com sua recomendação em 1 linha cada, 1 risco "
            "(problema crítico, A/R vencido, caixa, SLA). Termine com o link do dashboard. Depois envie com notify_ceo(severity='low').",
            trigger="cron")
        return result.text

    async def approve_within_rules(self) -> str:
        result = await self.run(
            "Revise pending_decisions. Para cada uma: se uma regra em active_rules ou a autonomia de config/agency.yaml permite decidir, use decide() e explique "
            "em 1 linha; se não, deixe pendente e resuma. Nunca aprove novo fornecedor, novo mercado, aumento de teto de mídia, reembolso acima do limite, "
            "mudança de persona/preço/escalonamento. Responda com a lista de decisões e o que fez em cada uma.",
            trigger="cron")
        return result.text

    async def manage_agents(self) -> str:
        """A cada 6h: agentes com erro repetido, custo fora do orçamento ou tarefas paradas → pausa/realoca/avisa."""
        result = await self.run(
            "Gestão da equipe de IA. Use company_snapshot(1) → agents_today e recent_runs por agente com erros. (1) Agente com ≥ 3 erros seguidos: pause_agent "
            "e notify_ceo(severity='medium') com o erro literal. (2) Departamento sem execução nas últimas 24h que deveria ter rodado (cadence em departments.yaml): "
            "delegue a tarefa padrão. (3) Custo de tokens acima do orçamento do agente: registre em 1 linha. Responda em ≤ 10 linhas.",
            trigger="cron")
        return result.text
