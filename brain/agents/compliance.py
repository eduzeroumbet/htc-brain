"""Compliance — Sonnet. Revisa conteúdo e anúncios antes de publicar, por mercado, com checklist codificado."""
from __future__ import annotations

from typing import Any

from brain.core import db, jev
from brain.core.agent_base import BaseAgent
from brain.settings import market
from brain.tools import marketing, names

CHECKLIST_GLOBAL = [
    "Licença DET visível ou implícita no perfil/rodapé; nunca se apresentar como companhia aérea ou governo.",
    "Preço sempre 'a partir de' com condições, moeda e o que inclui/exclui; sem 'melhor preço' sem fonte.",
    "Nenhuma promessa de visto garantido, upgrade garantido ou reembolso fora da política.",
    "Fatos de segurança/aeroportos/companhias só com fonte oficial e data; sem alarmismo nem minimização.",
    "Sem imagens ou linguagem sexualizada, álcool em destaque, jogos de azar, drogas, política ou religião (exceto informação prática).",
    "Sem uso de marcas de terceiros como se fossem parceiras (Emirates, Burj Khalifa, Atlantis) além da menção descritiva.",
    "CTA leva a canal da agência com opt-in claro; e-mail com link de descadastro.",
    "Conteúdo pago/afiliado identificado quando houver.",
]


class ComplianceAgent(BaseAgent):
    name = "compliance"
    department = "audit"
    tier = "work"
    max_turns = 12
    allowed = (*names("marketing", "pending_compliance", "review_content"),)

    def tools(self) -> dict[str, Any]:
        return {"marketing": marketing.server()}

    async def _prescreen(self, market_code: str | None) -> str:
        """Jev lê cada peça pendente antes do LLM: allow/review/block + flags. Peças 'allow' sem flags são aprovadas direto (sem tokens)."""
        if not jev.enabled():
            return ""
        rows = await db.fetch("SELECT id, title, body, format FROM content_items WHERE status = 'compliance_review' AND ($1::text IS NULL OR market_code = $1) ORDER BY created_at LIMIT 40", market_code)
        lines, auto = [], 0
        for r in rows:
            ans = await jev.moderate(f"{r.get('title') or ''}\n{r.get('body') or ''}", market_code)
            if not ans:
                continue
            flags = [k for k in ("has_unsourced_fact", "has_price_without_from", "has_superlative_or_guarantee", "names_client", "culturally_inappropriate") if ans.noul(k) >= 0.5]
            action = ans.choice("action", "review")
            if action == "allow" and not flags and ans.confidence("action") >= 0.8:
                await db.execute("UPDATE content_items SET status = 'scheduled', compliance_notes = 'jev:auto-approved' WHERE id = $1", r["id"])
                auto += 1
                continue
            lines.append(f"- {r['id']} → jev={action} ({ans.confidence('action'):.2f}) flags={','.join(flags) or 'nenhuma'}")
        return (f"\n\nPré-triagem Jev: {auto} peça(s) aprovadas automaticamente. Pendentes com sinalização:\n" + "\n".join(lines)) if lines or auto else ""

    async def review_pending(self, market_code: str | None = None) -> str:
        notes = "\n".join(f"- {n}" for n in (market(market_code).get("compliance_notes", []) if market_code else []))
        pre = await self._prescreen(market_code)
        result = await self.run(
            "Revise pending_compliance(). Para cada peça, aplique o checklist global e as notas do mercado. "
            "Se passar: review_content(decision='approve'). Se falhar por algo pequeno (frase, disclaimer, preço sem 'a partir de'): "
            "corrija você mesmo e aprove com revised_body + notes descrevendo a correção. Se falhar por algo estrutural (fato sem fonte, "
            "promessa proibida, imagem inadequada): review_content(decision='reject', notes='motivo e como refazer'). "
            "Responda com a tabela id | decisão | motivo.\n\nChecklist global:\n" + "\n".join(f"- {c}" for c in CHECKLIST_GLOBAL)
            + (f"\n\nNotas do mercado {market_code}:\n{notes}" if notes else "") + pre,
            market_code=market_code, trigger="cron",
        )
        return result.text
