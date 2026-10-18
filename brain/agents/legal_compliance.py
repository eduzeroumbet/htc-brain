"""Jurídico, Proteção de Dados & Regulatório — Opus. Contratos, pedidos de titulares, sanções, incidentes, DET, crise pública.
Prepara e recomenda; a CEO assina e decide. Não substitui o advogado externo nos casos em andamento."""
from __future__ import annotations

from typing import Any

from brain.core.agent_base import BaseAgent
from brain.tools import handoff, knowledge, legal, names, prospects


class LegalComplianceAgent(BaseAgent):
    name = "legal_compliance"
    department = "audit"
    tier = "strategy"
    max_turns = 16
    allowed = (
        *names("legal", "contracts_list", "draft_contract", "set_contract_status", "open_data_request", "fulfil_data_request", "open_data_requests",
               "sanctions_screen", "open_legal_incident", "legal_incidents_open", "review_text_for_legal_risk"),
        *names("knowledge", "search_knowledge", "fetch_url", "upsert_knowledge"),
        *names("prospects", "prospecting_pipeline"),
        *names("handoff", "request_ceo_decision", "notify_ceo", "escalate_to_human"),
    )

    def tools(self) -> dict[str, Any]:
        return {"legal": legal.server(), "knowledge": knowledge.server(), "prospects": prospects.server(), "handoff": handoff.server()}

    async def weekly_review(self) -> str:
        result = await self.run(
            "Revisão jurídica semanal. (1) open_data_requests: nenhum pode vencer — execute os prontos com fulfil_data_request (verifique identidade pelo canal de origem antes de 'access'/'erasure'). "
            "(2) contracts_list(days=60): vencendo → proposta de renovação ou encerramento (draft_contract quando renovar; termos iguais ou melhores); parceiras em stage='partner' sem contrato assinado → draft_contract(kind='partner_agency'). "
            "(3) legal_incidents_open: prazos (data breach 72 h), próximos passos, o que a CEO precisa decidir. (4) Screening: leads e parceiras RU/CIS que fecharam reserva na semana sem sanctions_screen → rode. "
            "(5) Obrigações DET/licença/seguro (search_knowledge('renewals')): algo vencendo em ≤ 45 dias sem dono → notify_ceo. Responda com: pedidos de dados | contratos | incidentes | screenings | pendências da CEO.",
            trigger="cron")
        return result.text

    async def review_document(self, text: str, note: str = "") -> str:
        result = await self.run(
            f"Revise este documento ({note or 'sem contexto'}):\n\n{text[:12000]}\n\nUse review_text_for_legal_risk primeiro. Depois: cláusulas problemáticas (cite o trecho), o que pedir para mudar, "
            "o que é aceitável, e a recomendação final (assinar / negociar / recusar) em 1 linha. Lei aplicável preferida: EAU/Dubai; foro Dubai; dados conforme PDPL + lei do cliente. Nunca aprove exclusividade, "
            "responsabilidade ilimitada ou pagamento sem prazo sem decisão da CEO.",
            trigger="task")
        return result.text

    async def handle_crisis(self, note: str = "") -> str:
        result = await self.run(
            f"Crise pública ou incidente grave: {note}\nSiga o protocolo: (1) open_legal_incident com severidade; (2) fatos confirmados com fonte (search_knowledge/fetch_url) — nada de especulação; "
            "(3) rascunho de posicionamento em 3 versões (cliente afetado, público/redes, imprensa) em português e inglês, sem admitir culpa, sem culpar terceiros, com o que estamos fazendo e canal de contato; "
            "(4) request_ceo_decision(kind='public_statement') com os rascunhos — NADA é publicado sem a CEO; (5) notify_ceo(severity='critical'). Responda com o pacote.",
            trigger="task")
        return result.text
