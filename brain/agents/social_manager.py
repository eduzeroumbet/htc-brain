"""Gestor de Conteúdo Social — Sonnet. Calendário editorial por mercado e plataforma, publicação, métricas, repurposing.
Diferença para o Content Studio: o Studio escreve as peças de fundo (blog, e-mail, roteiros); o Gestor Social decide o que
sai em cada rede, quando, com que gancho, publica e aprende com os números — sempre pelo Compliance antes."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from brain.core.agent_base import BaseAgent
from brain.settings import market
from brain.tools import handoff, knowledge, marketing, names, social


class SocialManagerAgent(BaseAgent):
    name = "social_manager"
    department = "marketing"
    tier = "work"
    max_turns = 18
    allowed = (
        *names("social", "social_accounts", "editorial_calendar", "plan_post", "publish_due", "record_post_metrics", "content_performance", "repurpose_candidates"),
        *names("marketing", "top_performing_content", "pending_compliance", "campaign_performance"),
        *names("knowledge", "search_knowledge", "fetch_url"),
        *names("handoff", "request_ceo_decision", "notify_ceo"),
    )

    def tools(self) -> dict[str, Any]:
        return {"social": social.server(), "marketing": marketing.server(), "knowledge": knowledge.server(), "handoff": handoff.server()}

    async def weekly_calendar(self, market_code: str) -> str:
        mk = market(market_code)
        start = date.today() + timedelta(days=1)
        result = await self.run(
            f"Calendário editorial de {start} a {start + timedelta(days=6)} para {market_code} ({mk['name']}), idioma {mk['language']}. "
            "(1) social_accounts e editorial_calendar(days=7): plataformas disponíveis, buracos, pilares já cobertos. (2) content_performance(14): o que funcionou "
            "(formato, pilar, horário). (3) search_knowledge('dubai_now') e search_knowledge(topic='playbook_" + market_code.lower() + "') para normas da plataforma e do mercado. "
            f"(4) Planeje 1 post/dia no canal primário ({mk['channels']['primary'][0]}) e 3 na semana nos secundários, horários {', '.join(mk['channels'].get('posting_hours_local', []))} "
            f"no fuso {mk['timezone']}, alternando pilares (content_pillars do mercado), com 1 peça de prova social (sem nome/foto de cliente sem consentimento), 1 de 'Dubai agora' com fonte, "
            "1 de produto com 'a partir de'. Cada peça: gancho na 1ª linha, detalhe concreto, CTA para WhatsApp/Telegram com a persona, hashtags do mercado (≤ 8), media_brief claro. "
            "Salve cada uma com plan_post. (5) repurpose_candidates: adapte 2 campeãs para outra plataforma/mercado. Responda com a tabela dia | plataforma | pilar | título | status.",
            market_code=market_code, trigger="cron")
        return result.text

    async def publish_cycle(self) -> str:
        """A cada 30 min, sem LLM: publica o que venceu; o pacote manual vai para o dashboard/feed."""
        import json
        from brain.tools.social import publish_due
        data = json.loads((await publish_due({"limit": 20}))["content"][0]["text"])
        if data["manual_pack"]:
            from brain.core import bus
            await bus.publish(bus.ALERTS, {"kind": "social_manual", "severity": "low", "text": f"{len(data['manual_pack'])} post(s) prontos para publicação manual (sem token/mídia). Veja Conteúdo no dashboard."})
        return f"publicados={len(data['published'])} manuais={len(data['manual_pack'])}"

    async def daily_metrics(self) -> str:
        result = await self.run(
            "Leitura diária das redes. Para cada conta em social_accounts com token, leia as métricas dos posts publicados nos últimos 7 dias pela API da plataforma "
            "(se não houver integração, use os números já registrados) e registre com record_post_metrics. Depois content_performance(7) por mercado: 3 linhas por mercado — "
            "o que subiu, o que caiu, 1 ajuste para o calendário de amanhã (horário, formato ou pilar). Se um post gerou ≥ 5 leads, notify_ceo(severity='low') em 1 linha.",
            trigger="cron")
        return result.text

    async def reviews_and_comments(self) -> str:
        """Reputação: avaliações públicas (Google, Tripadvisor, Trustpilot, Reclame Aqui) e comentários — resposta em 24 h, no idioma, sem discutir."""
        result = await self.run(
            "Reputação diária. Leia as avaliações e comentários públicos novos (pela API quando houver token; senão, os já registrados em public_reviews via fetch_url das páginas públicas da agência) e para cada um: "
            "positivo → agradeça em 2 linhas, no idioma, citando um detalhe da viagem sem dados pessoais; neutro/negativo → agradeça, reconheça o ponto específico, diga o que mudou ou está sendo feito, convide para o canal privado "
            "(WhatsApp/e-mail) — nunca discuta, nunca exponha dados da reserva, nunca prometa reembolso em público; ameaça legal, acusação de fraude, imprensa ou crise → NÃO responda; abra request_ceo_decision(kind='public_statement') "
            "e avise que o Jurídico assume. Responda com a tabela plataforma | nota | resumo | ação.",
            trigger="cron")
        return result.text

    async def campaign_social(self, market_code: str, note: str = "") -> str:
        """Delegado pelo CEO/Marketing: pacote social de uma campanha (teasers, lançamento, prova, urgência)."""
        result = await self.run(
            f"Pacote social para a campanha ({market_code}): {note}. Sequência de 8 peças em 2 semanas: 2 teasers, 1 lançamento com oferta 'a partir de', 2 de conteúdo útil ligado à oferta, "
            "1 prova social, 1 bastidor (frota/equipe/cidade), 1 último chamado — nas plataformas do mercado, com plan_post. Nada publica sem Compliance. Responda com a tabela.",
            market_code=market_code, trigger="task")
        return result.text
