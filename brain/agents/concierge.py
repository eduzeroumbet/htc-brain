"""Concierge em viagem — Sonnet. D-1 até o retorno: lembretes, voos, imprevistos, upsell, avaliação."""
from __future__ import annotations

from typing import Any

from brain.core import bus, db, jev
from brain.core.agent_base import BaseAgent
from brain.tools import catalog, crm, handoff, knowledge, names, ops


class ConciergeAgent(BaseAgent):
    name = "concierge"
    department = "customer_care"
    tier = "work"
    max_turns = 10
    allowed = (
        *names("ops", "clients_in_trip", "set_booking_status"),
        *names("crm", "find_lead", "conversation_history", "lead_bookings"),
        *names("catalog", "search_catalog"),
        *names("knowledge", "search_knowledge"),
        *names("handoff", "escalate_to_human"),
    )

    def tools(self) -> dict[str, Any]:
        return {"ops": ops.server(), "crm": crm.server(), "catalog": catalog.server(),
                "knowledge": knowledge.server(), "handoff": handoff.server()}

    async def in_trip_sweep(self) -> str:
        result = await self.run(
            "Varredura de clientes em viagem (clients_in_trip). Para cada um decida se há uma mensagem útil AGORA e só então escreva-a, "
            "no idioma do cliente, curta: D-1 → checklist (documentos, transfer, clima, vestimenta, câmbio) e vouchers; dia de chegada → "
            "boas-vindas + confirmação do transfer; dias de passeio → horário e ponto de encontro do dia; D-1 do retorno → check-out e transfer; "
            "pós-retorno → agradecimento + pedido de avaliação + 1 sugestão de próxima viagem. Marque 'in_trip'/'completed' com set_booking_status. "
            "Responda em JSON: [{lead_id, channel, channel_user_id, text}] só com as mensagens a enviar (pode ser lista vazia).",
            trigger="cron",
        )
        import json, re
        m = re.search(r"\[.*\]", result.text, re.S)
        if m:
            try:
                for msg in json.loads(m.group(0)):
                    if await bus.rate_limit(f"concierge:{msg['lead_id']}", limit=3, window_s=24 * 3600):
                        await bus.publish(bus.OUTBOUND, {**msg, "author": "ai:concierge"})
            except json.JSONDecodeError:
                pass
        return result.text

    async def post_trip_feedback(self, lead_id: str, text: str) -> dict[str, Any]:
        """Avaliação/resposta pós-viagem: o Jev mede sentimento, risco de churn e janela de upsell; grava CSAT aproximado."""
        ans = await jev.sentiment(text)
        if not ans:
            return {}
        csat = round(1 + 4 * ans.score("sentiment"))  # 1–5
        await db.execute("""UPDATE conversations SET csat = $2 WHERE id = (SELECT id FROM conversations WHERE lead_id = $1 ORDER BY last_message_at DESC LIMIT 1)""", lead_id, csat)
        out = {"csat": csat, "churn_risk": ans.noul("churn_risk"), "upsell_window": ans.noul("upsell_window")}
        if out["churn_risk"] >= 0.6:
            await bus.publish(bus.ALERTS, {"kind": "churn", "severity": "medium", "text": f"Cliente {lead_id} com risco de churn após a viagem (CSAT≈{csat}). Texto: {text[:200]}"})
        return out
