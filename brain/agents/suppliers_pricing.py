"""Fornecedores & Preços — Sonnet. Mantém o catálogo, valida licenças DET, marca hotéis com ocupação baixa."""
from __future__ import annotations

from typing import Any

from brain.core.agent_base import BaseAgent
from brain.tools import catalog, knowledge, names, ops


class SuppliersPricingAgent(BaseAgent):
    name = "suppliers_pricing"
    department = "operations"
    tier = "work"
    max_turns = 14
    allowed = (
        *names("catalog", "search_catalog", "get_item"),
        *names("knowledge", "fetch_url", "upsert_knowledge"),
        *names("ops", "bookings_to_confirm", "record_supplier_confirmation", "active_rules"),
    )

    def tools(self) -> dict[str, Any]:
        return {"catalog": catalog.server(), "knowledge": knowledge.server(), "ops": ops.server()}

    async def refresh_catalog(self) -> str:
        result = await self.run(
            "Rotina diária de fornecedores. (1) Liste itens do catálogo por tipo e aponte os que estão sem availability_note ou "
            "com preço desatualizado há mais de 14 dias (updated_at). (2) Com fetch_url nas páginas públicas dos fornecedores/plataformas "
            "configuradas, verifique variações de preço acima de 10% e liste-as para atualização manual pelo operador (não altere preço sozinho; "
            "gere um CSV com sku, preço atual, preço observado, fonte). (3) Marque como 'low_occupancy' na nota de disponibilidade os hotéis "
            "cujas tarifas caíram > 15% na semana — candidatos a upgrade grátis. (4) Alerte se alguma licença DET de fornecedor vence em < 60 dias. "
            "Responda com o CSV e os alertas.",
            trigger="cron",
        )
        return result.text
