"""Auditor — Opus, independente. Verifica se os fluxos foram seguidos, mede SLAs, pontua conversas/peças, aponta melhorias.
Não recebe tarefas do CEO-agente (ver config/departments.yaml → delegation). Só recomenda; nunca altera prompt, preço ou regra."""
from __future__ import annotations

from typing import Any

from brain.core import bus
from brain.core.agent_base import BaseAgent
from brain.tools import audit, handoff, marketing, names, ops

RUBRIC = """
Rubrica (0-10 cada; o Jev devolve 0–1 por dimensão — use como âncora e justifique desvios > 2 pontos):
1. Exatidão: nenhum preço, disponibilidade ou regra fora do catálogo/base de conhecimento; fontes citadas em segurança.
2. Persona e idioma do mercado; disclosure de IA + licença DET + IATA na primeira mensagem.
3. Condução comercial: qualificou em ≤ 4 perguntas, ofereceu cotação concreta, follow-up marcado, próximo passo claro.
4. Empatia e clareza: frases curtas, uma pergunta por vez, respondeu o que foi perguntado.
5. Compliance: consentimento, sem promessa de visto, preço total, cancelamento antes do pagamento, sem dado de cartão.
6. Escalonamento: escalou quando devia (gatilhos de config/escalation.yaml) e não escalou quando não devia.
"""


class AuditorAgent(BaseAgent):
    name = "auditor"
    department = "audit"
    tier = "strategy"
    max_turns = 18
    allowed = (
        *names("audit", "sla_metrics", "flow_conformance", "jev_score_conversation", "record_finding", "open_findings", "department_activity"),
        *names("ops", "sample_conversations", "record_qa_score", "active_rules", "open_escalations"),
        *names("marketing", "pending_compliance"),
        *names("handoff", "notify_ceo", "request_ceo_decision"),
    )

    def tools(self) -> dict[str, Any]:
        return {"audit": audit.server(), "ops": ops.server(), "marketing": marketing.server(), "handoff": handoff.server()}

    async def daily_audit(self) -> str:
        result = await self.run(
            "Auditoria diária independente.\n"
            "(1) sample_conversations(limit=12): para cada uma, jev_score_conversation(transcript) e depois sua nota pela rubrica; registre com record_qa_score. "
            "Alucinação de preço/disponibilidade = achado 'critical'.\n"
            "(2) flow_conformance(7): cada reserva com etapa faltante vira achado em 'operations' com a evidência (ref + etapa).\n"
            "(3) sla_metrics(): cada violação vira achado com a métrica, valor e alvo.\n"
            "(4) department_activity(24): agentes esperados que não rodaram = achado 'ceo_office'.\n"
            "(5) open_findings() antes de registrar — não duplique; se um achado antigo persiste, cite-o e aumente a severidade.\n"
            "(6) Para cada achado, a recomendação é a mudança EXATA (trecho de prompt antes/depois, regra, horário de cron, limiar) — NÃO aplique; mudanças de persona, preço "
            "ou escalonamento viram request_ceo_decision(kind='prompt_change').\n"
            "(7) Média do dia < 7, qualquer 'critical', ou ≥ 3 violações de SLA → notify_ceo(severity='high') com 3 linhas.\n"
            "Responda com: nota média | conformidade de fluxo % | SLAs violados | achados (área, severidade, título) | 3 melhorias prioritárias.\n" + RUBRIC,
            trigger="cron")
        return result.text

    async def sla_check(self) -> str:
        """Hora em hora: só os contadores duros. Sem LLM quando está tudo dentro do alvo."""
        from brain.tools.audit import sla_metrics  # chamada direta, sem agente
        import json
        data = json.loads((await sla_metrics({}))["content"][0]["text"])
        hard = data["hard_counts"]
        if not any(hard.values()) and not data["breaches"]:
            return "ok"
        text = (f"SLA: escalonamentos sem humano >60min: {hard['unacked_escalations']} · reservas presas >120min: {hard['stuck_bookings']} · "
                f"problemas vencidos: {hard['overdue_issues']} · violações: {', '.join(b['metric'] for b in data['breaches']) or 'nenhuma'}")
        if hard["unacked_escalations"] or hard["overdue_issues"]:
            await bus.publish(bus.ALERTS, {"kind": "sla", "severity": "high", "text": text})
            await bus.publish(bus.TASKS, {"agent": "booking_payments", "task": "resolve_issues"})
        return text

    async def weekly_improvements(self) -> str:
        result = await self.run(
            "Relatório semanal de melhorias operacionais. Com open_findings(), flow_conformance(7), sla_metrics() e department_activity(168): agrupe os achados por causa raiz, "
            "mostre tendência vs. semana anterior (achados abertos, implementados, repetidos) e proponha as 5 mudanças de maior impacto com esforço (baixo/médio/alto) e dono "
            "(departamento). Termine com o que o CEO humano precisa decidir. Envie o resumo (≤ 900 caracteres) com notify_ceo(severity='low').",
            trigger="cron")
        return result.text
