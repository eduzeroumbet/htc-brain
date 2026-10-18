"""SEO & Site — Sonnet. Semanal: palavras-chave por idioma, páginas de destino, schema, links internos."""
from __future__ import annotations

from typing import Any

from brain.core.agent_base import BaseAgent
from brain.tools import knowledge, marketing, names


class SeoSiteAgent(BaseAgent):
    name = "seo_site"
    department = "marketing"
    tier = "work"
    max_turns = 12
    allowed = (*names("knowledge", "search_knowledge", "fetch_url"), *names("marketing", "save_content"))

    def tools(self) -> dict[str, Any]:
        return {"knowledge": knowledge.server(), "marketing": marketing.server()}

    async def weekly_review(self, market_code: str) -> str:
        result = await self.run(
            f"Revisão semanal de SEO para o mercado {market_code}. (1) Liste 15 palavras-chave de intenção comercial no idioma do mercado "
            "(ex.: 'pacote Dubai 5 dias', 'Dubai honeymoon package from India', 'Dubai family holiday half term') agrupadas por intenção. "
            "(2) Proponha 2 páginas de destino novas (título, H1, meta description, estrutura H2, FAQ com schema FAQPage, CTA) e salve como "
            "save_content(format='landing'). (3) Aponte 3 melhorias técnicas (velocidade, hreflang, schema TouristTrip/Product) em lista curta.",
            market_code=market_code, trigger="cron",
        )
        return result.text
