"""SysOps — Haiku para diagnóstico, zero LLM para checagem. Saúde da máquina a cada 5 min; incidentes; post-mortem."""
from __future__ import annotations

import json
from typing import Any

from brain.core import bus
from brain.core.agent_base import BaseAgent
from brain.tools import handoff, names, sysops


class SysOpsAgent(BaseAgent):
    name = "sysops"
    department = "ceo_office"
    tier = "fast"
    max_turns = 8
    allowed = (
        *names("sysops", "health_check", "open_incident", "resolve_incident", "open_incidents", "health_history", "secrets_rotation_status"),
        *names("handoff", "notify_ceo"),
    )

    def tools(self) -> dict[str, Any]:
        return {"sysops": sysops.server(), "handoff": handoff.server()}

    async def health_cycle(self) -> str:
        """A cada 5 min, sem LLM: checa, abre/fecha incidentes pelos status. sev1 = algo que deixa cliente sem resposta."""
        from brain.tools.sysops import health_check, open_incident, open_incidents, resolve_incident
        data = json.loads((await health_check({}))["content"][0]["text"])
        problems = {p["component"]: p for p in data["problems"]}
        sev1 = {"db", "redis", "queue_inbound", "queue_outbound", "webhook_whatsapp", "anthropic"}
        for comp, p in problems.items():
            sev = "sev1" if comp in sev1 and p["status"] == "down" else "sev2" if p["status"] == "down" or comp in sev1 else "sev3"
            await open_incident({"component": comp, "severity": sev, "title": f"{comp} {p['status']}", "detail": f"{p.get('value')} {p.get('detail') or ''}"})
        opened = json.loads((await open_incidents({}))["content"][0]["text"])
        for inc in opened:
            if inc["component"] not in problems:
                await resolve_incident({"incident_id": str(inc["id"]), "postmortem": "auto: componente voltou ao normal no ciclo seguinte"})
        if any(p["status"] == "down" and c in sev1 for c, p in problems.items()):
            await bus.publish(bus.TASKS, {"agent": "sysops", "task": "diagnose"})
        return f"problemas={list(problems)}"

    async def diagnose(self) -> str:
        result = await self.run(
            "Diagnóstico de incidente. open_incidents + health_history(component, 6) dos componentes com problema. Em ≤ 8 linhas: o que está fora, desde quando, impacto no cliente (mensagens sem resposta?), "
            "causa provável, ação imediata (do RUNBOOK: make restart, verificar token/webhook, espaço em disco, orçamento de tokens), e se precisa da CEO/Edu agora. notify_ceo(severity='critical') se houver cliente sem resposta.",
            trigger="event")
        return result.text

    async def weekly_report(self) -> str:
        result = await self.run(
            "Relatório semanal de infra: uptime por componente (health_history 168 h), incidentes e post-mortems, idade dos backups, secrets_rotation_status (≥ 90 dias → pedir rotação), custo de tokens/Jev da semana vs orçamento. "
            "≤ 10 linhas, para o Edu e a CEO. notify_ceo(severity='low').",
            trigger="cron")
        return result.text
