"""Content Studio — Sonnet (Opus para peças-pilar). Lote diário por mercado; tudo vai para compliance antes de publicar."""
from __future__ import annotations

from typing import Any

from brain.core.agent_base import BaseAgent
from brain.settings import market
from brain.tools import knowledge, marketing, names


class ContentStudioAgent(BaseAgent):
    name = "content_studio"
    department = "marketing"
    tier = "work"
    max_turns = 14
    allowed = (
        *names("knowledge", "search_knowledge"),
        *names("marketing", "save_content", "top_performing_content"),
    )

    def tools(self) -> dict[str, Any]:
        return {"knowledge": knowledge.server(), "marketing": marketing.server()}

    async def daily_batch(self, market_code: str) -> str:
        mk = market(market_code)
        hours = ", ".join(mk["channels"].get("posting_hours_local", ["09:00", "13:00", "20:00"]))
        result = await self.run(
            f"Produza o lote de hoje para o mercado {market_code} ({mk['name']}), no idioma {mk['language']}: "
            f"3 posts (Instagram/Facebook ou canal primário), 1 roteiro de reel de 30-45s com legenda, 1 e-mail curto para a base. "
            f"Antes, consulte search_knowledge(topic='safety_2026') e search_knowledge(topic='incentives') e use SÓ fatos com fonte. "
            f"Distribua entre os pilares do mercado, alternando com os últimos dias. Cada peça: gancho na 1ª linha, um detalhe "
            f"concreto que só um local sabe, CTA para WhatsApp/webchat com a persona ({mk['persona']['name']}). "
            f"Salve cada peça com save_content (format, channel, language, title, body, scheduled_for hoje nos horários {hours} "
            f"no fuso {mk['timezone']}). Termine listando os ids salvos.",
            market_code=market_code, trigger="cron",
        )
        return result.text

    async def campaign_brief(self, market_code: str, note: str = "") -> str:
        """Delegado pelo CEO-agente ('marketing, crie uma campanha…'): brief completo + primeiras peças em compliance."""
        mk = market(market_code)
        result = await self.run(
            f"Pedido da CEO para o mercado {market_code} ({mk['name']}): {note or 'campanha sazonal do próximo pico'}.\n"
            "Monte o brief em português: objetivo e KPI, público e segmento (de market.segments), promessa em 1 frase, 3 ângulos criativos, "
            "canais (channels_by_market), calendário de 2 semanas, oferta/pacote do catálogo com 'a partir de', CTA e persona. Depois produza as 3 primeiras peças "
            f"no idioma {mk['language']} e salve com save_content (vão ao Compliance). Termine com o brief + ids salvos.",
            market_code=market_code, trigger="task")
        return result.text

    async def weekly_pillar(self, market_code: str) -> str:
        """Peças longas (blog/landing) com Opus, 2x por semana por mercado."""
        self.tier = "strategy"
        try:
            result = await self.run(
                f"Escreva 1 artigo de blog (900-1300 palavras, SEO, H2/H3, FAQ no fim) para o mercado {market_code} no idioma do mercado, "
                "sobre o pilar mais buscado agora, com dados oficiais de search_knowledge e CTA para cotação. Salve com save_content(format='blog').",
                market_code=market_code, trigger="cron",
            )
        finally:
            self.tier = "work"
        return result.text
