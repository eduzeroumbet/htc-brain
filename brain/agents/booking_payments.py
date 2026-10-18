"""Reservas, Emissão & Resolução — Sonnet. Confirma com fornecedores, emite ingressos/vouchers, resolve problemas com ingressos e atrações,
mantém o cliente informado e aciona o pessoal de resolução quando precisa de alguém presencial."""
from __future__ import annotations

from typing import Any

from brain.core.agent_base import BaseAgent
from brain.tools import crm, handoff, names, ops, payments, resolution


class BookingPaymentsAgent(BaseAgent):
    name = "booking_payments"
    department = "operations"
    tier = "work"
    max_turns = 16
    allowed = (
        *names("ops", "bookings_to_confirm", "record_supplier_confirmation", "attach_voucher", "set_booking_status", "active_rules", "clients_in_trip"),
        *names("payments", "create_payment_link", "payment_status", "request_refund"),
        *names("resolution", "open_issue", "open_issues", "update_issue", "assign_issue_to_staff", "request_issuance", "record_issuance", "pending_issuances", "classify_supplier_email"),
        *names("crm", "find_lead", "conversation_history"),
        *names("handoff", "request_ceo_decision", "escalate_to_human"),
    )

    def tools(self) -> dict[str, Any]:
        return {"ops": ops.server(), "payments": payments.server(), "resolution": resolution.server(), "crm": crm.server(), "handoff": handoff.server()}

    async def confirm_pending(self) -> str:
        result = await self.run(
            "Processe bookings_to_confirm e pending_issuances(7). Para cada reserva: (1) por item, solicite/registre com o fornecedor na ordem de prioridade HCTE "
            "(ingressos: portal Emaar → Turning Point/Connect World → Elevate/Passage to Arabia; hotéis: contrato direto → Elevate → Travolgo → Desert Gate/Turning Point) — "
            "sem integração, gere o e-mail no formato do fornecedor e registre 'requested' em record_supplier_confirmation(confirmed=false, note='requested <hora>'); "
            "(2) item confirmado → request_issuance(kind, provider) e, quando o documento existir, record_issuance('issued', provider_ref, document_url) + attach_voucher; "
            "(3) reserva em 'confirming' há > 120 min sem resposta → open_issue(kind='hotel'|'ticket', ...) e escalate_to_human(trigger_id='low_confidence') se a viagem é em ≤ 48h; "
            "(4) emissão 'failed' → tente o próximo provedor da prioridade e registre. Responda com a tabela reserva | itens | status | próxima ação.",
            trigger="cron")
        return result.text

    async def resolve_issues(self) -> str:
        result = await self.run(
            "Resolução de problemas (a cada 15 min). open_issues(): por severidade. Para cada problema: (1) decida o caminho — reemitir no portal, trocar horário/atração "
            "equivalente do catálogo, acionar fornecedor, reembolsar dentro da política (request_refund), ou presença física (assign_issue_to_staff com local, hora e briefing "
            "de 3 linhas); (2) o cliente NUNCA fica sem resposta: escreva a mensagem no idioma dele explicando o que está sendo feito e quando terá retorno — devolva no JSON final; "
            "(3) update_issue com status e resolução; resolvido → client_informed=true. Critical → escalate_to_human(trigger_id='travel_emergency') além da resolução. "
            "Responda com a tabela problema | ação | prazo e, no fim, MENSAGENS: [{lead_id, channel, channel_user_id, text}].",
            trigger="cron")
        # mensagens ao cliente saem pelo stream outbound
        import json, re
        from brain.core import bus
        m = re.search(r"MENSAGENS:\s*(\[.*\])", result.text, re.S)
        if m:
            try:
                for msg in json.loads(m.group(1)):
                    if await bus.rate_limit(f"issue_msg:{msg.get('lead_id')}", limit=4, window_s=6 * 3600):
                        await bus.publish(bus.OUTBOUND, {**msg, "author": "ai:operations"})
            except json.JSONDecodeError:
                pass
        return result.text

    async def handle_huda_handoff(self, lead_id: str, text: str = "", note: str = "") -> str:
        """A Huda (WhatsApp) transferiu um cliente: pagamento, reembolso, cancelamento, emergência ou pedido de humano.
        A Huda já parou de responder; quem fala com o cliente agora é o humano via Chatwoot. Aqui a máquina prepara o terreno."""
        result = await self.run(
            f"A consultora Huda transferiu o lead {lead_id} para a equipe (motivo: {note or 'não informado'}). Resumo dela:\n{text[:1500]}\n\n"
            "find_lead + conversation_history. Classifique: pagamento/reembolso/cancelamento → abra o fluxo correspondente (request_refund dentro da política, "
            "open_issue kind=payment, etc.) e prepare o que o humano precisa (reserva, valores, política aplicável); emergência → escalate_to_human(trigger_id='travel_emergency') "
            "e open_issue severity alta; pedido de humano/cotação pronta → escalate_to_human(trigger_id='human_requested') com briefing de 5 linhas (quem, de onde, datas, pax, o que quer). "
            "NÃO escreva ao cliente: a Huda já avisou que alguém da equipe assume. Responda com o briefing e as ações feitas.",
            trigger="event")
        return result.text

    async def supplier_email(self, email_text: str, booking_ref: str | None = None) -> str:
        result = await self.run(
            f"E-mail de fornecedor{(' sobre a reserva ' + booking_ref) if booking_ref else ''}:\n{email_text[:4000]}\n\n"
            "classify_supplier_email primeiro. confirmed → record_supplier_confirmation(confirmed=true, supplier_ref); declined → open_issue + buscar alternativa no próximo "
            "fornecedor da prioridade; price_change → se a diferença ≤ 3% do item, aceite e registre; acima, request_ceo_decision(kind='price_change'); question → responda ao "
            "fornecedor (texto pronto). Responda com o que fez em 3 linhas.",
            trigger="event")
        return result.text
