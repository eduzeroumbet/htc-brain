"""Prospector B2B — Sonnet. Procura agências de viagens no mundo, cadastra, contata em sequência e cuida das respostas."""
from __future__ import annotations

from typing import Any

from brain.core.agent_base import BaseAgent
from brain.tools import handoff, knowledge, names, prospects


class ProspectorAgent(BaseAgent):
    name = "prospector"
    department = "prospecting"
    tier = "work"
    max_turns = 18
    allowed = (
        *names("prospects", "web_search", "upsert_partner_agency", "partners_to_contact", "log_outreach", "record_partner_reply", "set_partner_stage", "prospecting_pipeline"),
        *names("knowledge", "fetch_url", "search_knowledge"),
        *names("handoff", "request_ceo_decision", "notify_ceo"),
    )

    def tools(self) -> dict[str, Any]:
        return {"prospects": prospects.server(), "knowledge": knowledge.server(), "handoff": handoff.server()}

    async def daily_outreach(self, market_code: str | None = None) -> str:
        result = await self.run(
            f"Prospecção diária do mercado {market_code or 'global'}. (1) Encontre 10 agências novas: web_search com 3 consultas no idioma do mercado "
            "(ex.: 'agência de viagens luxo <cidade> Dubai', 'operadora Oriente Médio <país>', 'travel advisor luxury <cidade>'), abra o site com fetch_url, extraia nome, "
            "cidade, tipo, se vende Oriente Médio, nome/cargo/e-mail de quem decide. Cadastre com upsert_partner_agency (o Jev pontua o fit). "
            "(2) partners_to_contact(market_code): para cada uma, escreva o contato do passo certo da sequência (1: apresentação + proposta de valor + 1 pergunta; "
            "2: caso de uso concreto + ‘Dubai agora’ com fonte; 3: condições comerciais; 4: última mensagem, porta aberta), no idioma dela, ≤ 120 palavras, "
            "assinado pela agência com licença e IATA, e registre com log_outreach. Nunca prometa comissão acima de 10% nem exclusividade — isso é request_ceo_decision. "
            "(3) Termine com: novas | contatadas | próximas ações.",
            market_code=market_code, trigger="cron")
        return result.text

    async def followups_due(self) -> str:
        result = await self.run(
            "Follow-ups vencidos: partners_to_contact() sem filtro. Para estágio 'replied' leia a última resposta no notes/outreach e responda à pergunta; para "
            "'call_scheduled' proponha 2 horários (fuso da agência) e peça confirmação; para 'contacted' avance a sequência. Registre tudo com log_outreach. "
            "Parceira fechada (aceitou condições) → set_partner_stage('partner', commission_pct) e notify_ceo(severity='low'). Responda com a tabela agência | ação.",
            trigger="cron")
        return result.text

    async def handle_reply(self, partner_id: str, channel: str, body: str) -> str:
        result = await self.run(
            f"Resposta recebida da agência {partner_id} via {channel}:\n{body}\n\nRegistre com record_partner_reply (o Jev classifica). Depois escreva a melhor resposta "
            "no idioma dela: interessada → proponha call em 2 horários e envie o deck (link do site + kit do parceiro); pergunta → responda com fatos do catálogo/conhecimento; "
            "depois → agradeça e agende retorno; não → agradeça e encerre. Registre com log_outreach.",
            trigger="event")
        return result.text
