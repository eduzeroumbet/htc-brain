"""Handoff humano: abre caso no Chatwoot, registra escalonamento, avisa o CEO."""
from __future__ import annotations

from typing import Any

import httpx

from brain.core import bus, db
from brain.settings import escalation_config, get_settings
from brain.tools import create_sdk_mcp_server, err, ok, tool

SERVER = "handoff"


async def _chatwoot_open(lead: dict[str, Any], summary: str, severity: str) -> int | None:
    s = get_settings()
    if not (s.chatwoot_url and s.chatwoot_api_token and s.chatwoot_human_inbox_id):
        return None
    base = f"{s.chatwoot_url}/api/v1/accounts/{s.chatwoot_account_id}"
    h = {"api_access_token": s.chatwoot_api_token}
    async with httpx.AsyncClient(timeout=20, headers=h) as c:
        contact = await c.post(f"{base}/contacts", json={
            "inbox_id": s.chatwoot_human_inbox_id, "name": lead.get("display_name") or lead["channel_user_id"],
            "phone_number": lead.get("phone"), "email": lead.get("email"),
            "identifier": f"{lead['channel']}:{lead['channel_user_id']}"})
        cid = (contact.json().get("payload") or {}).get("contact", {}).get("id") or contact.json().get("id")
        conv = await c.post(f"{base}/conversations", json={
            "inbox_id": s.chatwoot_human_inbox_id, "contact_id": cid, "status": "open",
            "custom_attributes": {"severity": severity, "market": lead.get("market_code")}})
        conv_id = conv.json().get("id")
        await c.post(f"{base}/conversations/{conv_id}/messages", json={"content": summary, "message_type": "outgoing", "private": True})
        return conv_id


@tool("escalate_to_human", "Abre um caso humano. trigger_id deve ser um dos ids de config/escalation.yaml. Inclua resumo em português, ação sugerida e severidade.", {"lead_id": str, "conversation_id": str, "trigger_id": str, "summary": str, "suggested_action": str})
async def escalate_to_human(args: dict[str, Any]) -> dict[str, Any]:
    cfg = escalation_config()
    trig = next((t for t in cfg["triggers"] if t["id"] == args["trigger_id"]), None)
    if not trig:
        return err(f"trigger desconhecido: {args['trigger_id']}")
    lead = await db.fetchrow("SELECT * FROM leads WHERE id = $1", args["lead_id"])
    if not lead:
        return err("lead não encontrado")
    text = (f"[{trig['label']} · {trig['severity']}] {lead.get('display_name') or lead['channel_user_id']} "
            f"({lead.get('market_code')}, {lead['channel']})\n\nResumo: {args['summary']}\n\nAção sugerida: {args.get('suggested_action','')}")
    cw_id = await _chatwoot_open(lead, text, trig["severity"])
    row = await db.fetchrow(
        """INSERT INTO escalations (conversation_id, lead_id, trigger_id, severity, summary, suggested_action, chatwoot_conversation_id, notified_ceo)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING id""",
        args.get("conversation_id"), args["lead_id"], trig["id"], trig["severity"], args["summary"], args.get("suggested_action"),
        cw_id, bool(trig.get("notify_ceo")),
    )
    await db.execute("UPDATE conversations SET status = 'human', escalation_trigger = $2, chatwoot_conversation_id = $3 WHERE id = $1",
                     args.get("conversation_id"), trig["id"], cw_id)
    if trig.get("notify_ceo"):
        await bus.publish(bus.ALERTS, {"kind": "escalation", "severity": trig["severity"], "text": text,
                                       "call": bool(trig.get("call_ceo")), "escalation_id": str(row["id"])})  # type: ignore[index]
    return ok({"escalation_id": str(row["id"]), "chatwoot_conversation_id": cw_id, "sla_minutes": trig["sla_minutes"],  # type: ignore[index]
               "ai_reply_before_handoff": trig.get("ai_reply_before_handoff", "")})


@tool("request_ceo_decision", "Registra uma decisão que só o CEO pode tomar (desconto acima do limite, novo fornecedor, aumento de orçamento...). Retorna id; o dashboard mostra para aprovar/recusar.", {"kind": str, "context": str, "recommendation": str, "amount_usd": float, "market_code": str, "requested_by": str})
async def request_ceo_decision(args: dict[str, Any]) -> dict[str, Any]:
    row = await db.fetchrow(
        """INSERT INTO decisions (kind, context, recommendation, requested_by, amount_usd, market_code)
           VALUES ($1,$2,$3,$4,$5,$6) RETURNING id""",
        args["kind"], args["context"], args["recommendation"], args.get("requested_by") or "ai", args.get("amount_usd"), args.get("market_code"),
    )
    await bus.publish(bus.ALERTS, {"kind": "decision", "severity": "medium", "text": f"Decisão pendente: {args['kind']} — {args['context'][:300]}"})
    return ok({"decision_id": str(row["id"]), "status": "pending"})  # type: ignore[index]


@tool("notify_ceo", "Manda uma mensagem curta ao CEO pelo WhatsApp (use só para emergências, briefing e aprovações).", {"text": str, "severity": str})
async def notify_ceo(args: dict[str, Any]) -> dict[str, Any]:
    await bus.publish(bus.ALERTS, {"kind": "note", "severity": args.get("severity") or "low", "text": args["text"]})
    return ok({"queued": True})


def server():
    return create_sdk_mcp_server(SERVER, "1.0.0", [escalate_to_human, request_ceo_decision, notify_ceo])
