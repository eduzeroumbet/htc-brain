"""Estrategista — Opus. Novas estratégias de venda, criação de produtos/pacotes, análise de investimento em tráfego, cenários."""
from __future__ import annotations

import json
import re
from typing import Any

from brain.core import db, jev
from brain.core.agent_base import BaseAgent
from brain.tools import catalog, handoff, knowledge, marketing, names, ops, prospects


class StrategistAgent(BaseAgent):
    name = "strategist"
    department = "strategy"
    tier = "strategy"
    max_turns = 16
    allowed = (
        *names("ops", "kpi_snapshot", "active_rules"),
        *names("marketing", "campaign_performance", "spend_today", "top_performing_content"),
        *names("catalog", "search_catalog", "seasonal_price", "low_occupancy_hotels"),
        *names("knowledge", "search_knowledge"),
        *names("prospects", "prospecting_pipeline"),
        *names("handoff", "request_ceo_decision", "notify_ceo"),
    )

    def tools(self) -> dict[str, Any]:
        return {"ops": ops.server(), "marketing": marketing.server(), "catalog": catalog.server(), "knowledge": knowledge.server(),
                "prospects": prospects.server(), "handoff": handoff.server()}

    async def _save_proposals(self, text: str) -> int:
        m = re.search(r"PROPOSTAS:\s*(\[.*\])", text, re.S)
        if not m:
            return 0
        try:
            items = json.loads(m.group(1))
        except json.JSONDecodeError:
            return 0
        n = 0
        for p in items:
            ans = await jev.decide(json.dumps(p, ensure_ascii=False)[:3000], {"attractiveness": {"type": "score", "instructions": "Atratividade comercial do pacote para o mercado-alvo (demanda, diferenciação, margem, facilidade de operar)", "criteria": ["fraca", "média", "boa", "excelente"]}})
            await db.execute(
                """INSERT INTO product_proposals (name, market_codes, segment, nights, price_from_usd, est_margin_pct, rationale, items, jev_attractiveness)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
                p.get("name"), p.get("market_codes") or [], p.get("segment"), p.get("nights"), p.get("price_from_usd"), p.get("est_margin_pct"),
                p.get("rationale"), p.get("items") or [], ans.score("attractiveness") if ans else None)
            n += 1
        return n

    async def weekly_strategy(self) -> str:
        result = await self.run(
            "Estratégia da semana. Leia kpi_snapshot(7) e kpi_snapshot(28), campaign_performance(28), top_performing_content(28), prospecting_pipeline(28), "
            "search_knowledge('dubai_now') e active_rules. Entregue: (1) diagnóstico em 5 linhas (o que vende, o que não vende, por mercado); (2) 3 apostas da semana "
            "com dono (departamento), métrica e prazo; (3) realocação de tráfego recomendada em % por mercado com o porquê (o Paid Media executa dentro do teto; acima "
            "do teto → request_ceo_decision(kind='budget_increase')); (4) 1 risco e 1 oportunidade de curto prazo. Mudanças de preço, persona ou mercado → "
            "request_ceo_decision. Responda em português, sem adjetivos.",
            trigger="cron")
        return result.text

    async def monthly_product_review(self) -> str:
        result = await self.run(
            "Revisão mensal de produto. Com search_catalog, seasonal_price, low_occupancy_hotels, kpi_snapshot(30) e search_knowledge('seasonality'): "
            "(1) quais pacotes/experiências venderam e com que margem; (2) 3 novos pacotes para os próximos 90 dias (um por segmento mais forte), cada um com "
            "name, market_codes, segment, nights, price_from_usd, est_margin_pct, rationale e items [{sku, qty}] — só itens existentes no catálogo; (3) o que tirar do "
            "catálogo. Termine com PROPOSTAS: [...] em JSON com as propostas. Abra request_ceo_decision(kind='new_product') para cada proposta com margem ≥ 15%.",
            trigger="cron")
        await self._save_proposals(result.text)
        return result.text

    async def scenario(self, note: str = "") -> str:
        result = await self.run(
            f"Cenário solicitado pelo CEO: {note or 'investimento em tráfego +50% nos 2 melhores mercados por 30 dias'}.\n"
            "Monte 3 cenários (conservador, base, agressivo) com premissas explícitas a partir de campaign_performance(60) e kpi_snapshot(60): CPL, taxa lead→reserva, "
            "ticket médio, margem. Para cada cenário: investimento, leads, reservas, receita, margem, CAC, ponto de equilíbrio e risco. Tabela compacta + recomendação em 3 linhas.",
            trigger="task")
        return result.text
