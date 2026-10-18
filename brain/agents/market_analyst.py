"""Analista de Marketing & Tráfego — Opus. Mercados onde sabemos pouco (Rússia/CIS, Índia, Golfo, DACH): descobre como alcançar
clientes e agências, monta o playbook com fontes, e aprende gastando pouco — experimentos dentro do budget, decididos por resultado."""
from __future__ import annotations

from typing import Any

from brain.core.agent_base import BaseAgent
from brain.settings import market
from brain.tools import growth, handoff, knowledge, marketing, names, prospects


class MarketAnalystAgent(BaseAgent):
    name = "market_analyst"
    department = "strategy"
    tier = "strategy"
    max_turns = 20
    allowed = (
        *names("growth", "get_playbook", "upsert_playbook", "experiment_budget", "propose_experiment", "start_experiment", "experiment_results", "close_experiment", "channel_benchmarks"),
        *names("marketing", "campaign_performance", "spend_today", "set_campaign_budget", "pause_campaign", "top_performing_content"),
        *names("knowledge", "search_knowledge", "fetch_url", "upsert_knowledge"),
        *names("prospects", "web_search", "prospecting_pipeline"),
        *names("handoff", "request_ceo_decision", "notify_ceo"),
    )

    def tools(self) -> dict[str, Any]:
        return {"growth": growth.server(), "marketing": marketing.server(), "knowledge": knowledge.server(), "prospects": prospects.server(), "handoff": handoff.server()}

    async def research_market(self, market_code: str, note: str = "") -> str:
        mk = market(market_code)
        result = await self.run(
            f"Pesquisa de mercado: {market_code} ({mk['name']}). {note}\n"
            f"(1) get_playbook e search_knowledge(topic='playbook_{market_code.lower()}') — comece pelo que já sabemos e pelas perguntas abertas. "
            "(2) Para cada pergunta aberta, busque e leia fontes primárias com web_search + fetch_url (páginas oficiais das plataformas de anúncios, associações de agências, "
            "reguladores, companhias aéreas, imprensa de turismo local); registre cada fonte com url e data. "
            "(3) Responda, com fonte: quais plataformas de anúncio e redes estão disponíveis/restritas/bloqueadas para anunciar a partir de Dubai para este público; "
            "custo típico (CPM/CPL) quando houver; como o público pesquisa e compra viagem (busca, redes, mensageiros, operadoras, OTAs); onde estão as agências "
            "(associações, feiras, diretórios, mídia B2B); regras legais de anúncio e dados; meios de pagamento viáveis; normas criativas (idioma, formato, tabus); sazonalidade; 3 concorrentes e como anunciam. "
            "(4) upsert_playbook com tudo (knowledge_level honesto) e upsert_knowledge(topic='playbook_" + market_code.lower() + "') com um resumo para o Consultor e o Social. "
            "(5) Proponha até 3 experimentos (propose_experiment) para as maiores incertezas — hipótese testável, budget mínimo que ensina, 14 dias, métrica e kill. "
            "Responda em português: o que sabemos agora, o que ainda não sabemos, e os experimentos.",
            market_code=market_code, trigger="task")
        return result.text

    async def weekly_experiments(self) -> str:
        result = await self.run(
            "Ciclo semanal de experimentos (todos os mercados). (1) experiment_results(30): para cada 'running' com gasto suficiente — kill_triggered → close_experiment('lost', learning); "
            "on_target e ≥ 10 dias → close_experiment('won', learning) (o Paid Media escala); fim do prazo sem conclusão → 'inconclusive' com o que mudaria no desenho. "
            "(2) Cada aprendizado vai para o playbook (upsert_playbook: canal com status/CPL real, perguntas abertas atualizadas). (3) experiment_budget por mercado ativo: "
            "com espaço, propose_experiment para a próxima maior incerteza (canal, criativo, público, oferta, landing ou abordagem B2B); 'approved' → start_experiment. "
            "(4) channel_benchmarks(60) vs targets: canal consistentemente abaixo do alvo por 2 semanas → recomende ao Paid Media mover orçamento (ou faça se for dentro do mercado); "
            "acima do teto do mercado → request_ceo_decision(kind='budget_increase') com o cálculo. "
            "Responda: experimentos encerrados (veredito, número, aprendizado) | em andamento | novos | realocações recomendadas. Sem adjetivos.",
            trigger="cron")
        return result.text

    async def market_entry_plan(self, market_code: str, note: str = "") -> str:
        """Delegado pelo CEO: plano de entrada em mercado de onda 2 com o budget informado."""
        result = await self.run(
            f"Plano de entrada: {market_code}. {note or 'budget conforme config/budgets.yaml'}\n"
            "Com get_playbook, channel_benchmarks(90), prospecting_pipeline(90) e o budget: (1) 90 dias em 3 fases (aprender → provar → escalar) com gasto por fase; "
            "(2) mix B2C (canais, criativos, landing, idioma) e B2B (agências a prospectar, feiras, parceiros), com a métrica de passagem de fase; (3) riscos legais/pagamento e mitigação; "
            "(4) os 3 primeiros experimentos já propostos (propose_experiment). Mudança de split entre mercados → request_ceo_decision(kind='market_pilot'). Tabela + 5 linhas.",
            market_code=market_code, trigger="task")
        return result.text
