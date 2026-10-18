"""Market Intel — Sonnet. Monitora fontes oficiais e atualiza a base de conhecimento (inclui a página de segurança 2026)."""
from __future__ import annotations

from typing import Any

from brain.core.agent_base import BaseAgent
from brain.tools import knowledge, names

SOURCES = [
    "https://www.dubaidet.gov.ae/en/newsroom/press-releases",
    "https://www.dubaidet.gov.ae/en/research-and-insights",
    "https://www.dubaidet.gov.ae/en/travel-advisory",
    "https://www.wam.ae/en",
    "https://www.dubaiairports.ae/",
    "https://www.emirates.com/ae/english/help/travel-updates/",
    "https://www.flydubai.com/en/plan/travel-updates",
]
ADVISORIES = {
    "BR": "https://www.gov.br/mre/pt-br/assuntos/portal-consular/alertas",
    "IN": "https://www.mea.gov.in/travel-advisory.htm",
    "GB": "https://www.gov.uk/foreign-travel-advice/united-arab-emirates",
    "US": "https://travel.state.gov/content/travel/en/traveladvisories/traveladvisories/united-arab-emirates-travel-advisory.html",
    "DE": "https://www.auswaertiges-amt.de/de/service/laender/vereinigtearabischeemirate-node/vereinigtearabischeemiratesicherheit/202274",
    "RU": "https://www.mid.ru/ru/",
    "SA": "https://www.mofa.gov.sa/",
}


class MarketIntelAgent(BaseAgent):
    name = "market_intel"
    department = "strategy"
    tier = "work"
    max_turns = 16
    allowed = (*names("knowledge", "fetch_url", "upsert_knowledge", "search_knowledge"),)

    def tools(self) -> dict[str, Any]:
        return {"knowledge": knowledge.server()}

    async def daily_refresh(self, market_code: str) -> str:
        result = await self.run(
            "Atualize a base de conhecimento para o mercado {m}. Passos: (1) leia com fetch_url as fontes oficiais de Dubai "
            "e o advisory do governo do mercado: {adv}. (2) Extraia SÓ fatos com data e fonte: status de aeroportos/espaço aéreo, "
            "companhias suspensas e datas de retomada, advisories, números de visitantes/ocupação, incentivos (taxas zeradas, "
            "A Dubai Invite), eventos do mês. (3) Grave com upsert_knowledge: topic='safety_2026' (valid_days=2), "
            "topic='airlines_status' (valid_days=3), topic='incentives' (valid_days=14), topic='events_month' (valid_days=30), "
            "market_code='{m}', language do mercado, source_url e source_date. (4) Se algo mudou de forma relevante para vendas "
            "(novo ataque, fechamento de aeroporto, retomada de companhia), termine a resposta com a linha 'ALERTA: ...'. "
            "Nunca escreva opinião; só fatos verificáveis."
            .format(m=market_code, adv=ADVISORIES.get(market_code, "")),
            market_code=market_code, trigger="cron",
            prompt_ctx={"sources": SOURCES},
        )
        if "ALERTA:" in result.text:
            from brain.core import bus
            await bus.publish(bus.ALERTS, {"kind": "intel", "severity": "high", "text": result.text.split("ALERTA:", 1)[1][:600]})
        return result.text
