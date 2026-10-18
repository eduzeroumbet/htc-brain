"""Paid Media — Sonnet. A cada 6h: lê CAC/CPL, realoca dentro do teto, pausa o que não converte, propõe criativos."""
from __future__ import annotations

from typing import Any

from brain.core.agent_base import BaseAgent
from brain.tools import handoff, marketing, names, ops


class PaidMediaAgent(BaseAgent):
    name = "paid_media"
    department = "marketing"
    tier = "work"
    max_turns = 14
    allowed = (
        *names("marketing", "campaign_performance", "spend_today", "set_campaign_budget", "pause_campaign", "top_performing_content", "save_content"),
        *names("ops", "active_rules"),
        *names("handoff", "request_ceo_decision"),
    )

    def tools(self) -> dict[str, Any]:
        return {"marketing": marketing.server(), "ops": ops.server(), "handoff": handoff.server()}

    async def optimize(self) -> str:
        result = await self.run(
            "Ciclo de otimização. (1) active_rules(scope='media'). (2) campaign_performance(days=7) e spend_today. "
            "(3) Regras: pausar campanha com CPL > 2x a meta por 48h e gasto mínimo de USD 40; mover até 20% do orçamento do dia "
            "do pior CAC para o melhor CAC do mesmo ou de outro mercado ativo, respeitando mínimo de 8% por mercado ativo e o teto diário. "
            "(4) Para cada mercado, pegue top_performing_content(days=14) e salve 2 novas variações de anúncio com save_content(format='ad_creative') "
            "(vão para compliance). (5) Se o teto diário estiver limitando um mercado com CAC 30% abaixo da meta há 7 dias, "
            "abra request_ceo_decision(kind='budget_increase') com o cálculo. Responda com um resumo de 5 linhas do que fez.",
            trigger="cron",
        )
        return result.text

    async def scenario(self, market_code: str | None = None, note: str = "") -> str:
        """Delegado pelo CEO/Estratégia: dimensionar investimento para um objetivo (sem executar)."""
        result = await self.run(
            f"Cenário de mídia{(' para ' + market_code) if market_code else ''}: {note or 'dimensionar teto para o próximo pico'}. "
            "Com campaign_performance(60) e spend_today: CPL e CAC atuais, orçamento diário necessário para a meta, leads e reservas esperados, "
            "risco de saturação por canal. Se exigir teto acima do atual, abra request_ceo_decision(kind='budget_increase') com o cálculo. "
            "Não altere orçamentos neste ciclo. Tabela compacta + 3 linhas.",
            market_code=market_code, trigger="task")
        return result.text
