"""WhatsApp Cloud API (Meta). Webhook de entrada + envio (texto, documento, template fora da janela de 24h)."""
from __future__ import annotations

import hashlib
import hmac
from typing import Any

import httpx
import structlog

from brain.channels import delivery_failures
from brain.core import bus, db
from brain.settings import get_settings

log = structlog.get_logger(__name__)
GRAPH = "https://graph.facebook.com/v21.0"


def verify_signature(body: bytes, signature_header: str | None) -> bool:
    secret = get_settings().wa_app_secret
    if not secret:
        return True  # dev
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, signature_header.split("=", 1)[1])


def _restricted(errors: Any) -> bool:
    return delivery_failures.COUNTRY_RESTRICTED in delivery_failures.extract_error_codes({"errors": errors})


async def handle_webhook(payload: dict[str, Any]) -> int:
    """Normaliza e publica cada mensagem recebida. Retorna quantas publicou."""
    n = 0
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            contacts = {c["wa_id"]: c.get("profile", {}).get("name") for c in value.get("contacts", [])}
            if _restricted(value.get("errors")):  # erro no nível do value: sem destinatário → mercado unknown, só alerta
                await delivery_failures.handle_permanent_failure(
                    category=delivery_failures.CAT_COUNTRY_RESTRICTED, source="webhook", to=None,
                    ref=delivery_failures.webhook_ref(value), error_code=delivery_failures.COUNTRY_RESTRICTED)
            for msg in value.get("messages", []):
                if _restricted(msg.get("errors")):
                    await delivery_failures.handle_permanent_failure(
                        category=delivery_failures.CAT_COUNTRY_RESTRICTED, source="webhook", to=msg.get("from"),
                        ref=f"wamid:{msg.get('id')}", wamid=msg.get("id"), error_code=delivery_failures.COUNTRY_RESTRICTED)
                    continue
                text, media = "", None
                t = msg.get("type")
                if t == "text":
                    text = msg["text"]["body"]
                elif t == "audio":
                    media = msg[t].get("id")
                    from brain.core.transcribe import whatsapp_audio_to_text
                    transcript = await whatsapp_audio_to_text(media)
                    text = f"[áudio do cliente, transcrito] {transcript}" if transcript else "[áudio recebido — transcrição indisponível: peça com jeito para escrever ou resuma o que entendeu]"
                elif t in ("image", "document", "video"):
                    media = msg[t].get("id")
                    text = msg[t].get("caption", "") or f"[{t} recebido]"
                elif t == "interactive":
                    i = msg["interactive"]
                    text = (i.get("button_reply") or i.get("list_reply") or {}).get("title", "")
                elif t == "location":
                    text = f"[location] {msg['location'].get('latitude')},{msg['location'].get('longitude')}"
                else:
                    text = f"[{t}]"
                await bus.publish(bus.INBOUND, {
                    "channel": "whatsapp", "channel_user_id": msg["from"], "display_name": contacts.get(msg["from"]),
                    "phone": f"+{msg['from']}", "text": text, "media_url": media, "message_id": msg.get("id"),
                })
                n += 1
            for status in value.get("statuses", []):
                if status.get("status") == "failed" and _restricted(status.get("errors")):
                    await delivery_failures.handle_permanent_failure(
                        category=delivery_failures.CAT_COUNTRY_RESTRICTED, source="webhook", to=status.get("recipient_id"),
                        ref=f"wamid:{status.get('id')}", wamid=status.get("id"), error_code=delivery_failures.COUNTRY_RESTRICTED)
                elif status.get("status") == "failed":
                    errs = [{"code": e.get("code"), "title": e.get("title"), "detail": (e.get("error_data") or {}).get("details")} for e in status.get("errors", [])]
                    log.error("wa_delivery_failed", id=status.get("id"), to=status.get("recipient_id"), errors=errs)
                    await bus.publish(bus.ALERTS, {"kind": "channel", "severity": "high", "text": f"WhatsApp não entregou mensagem para {status.get('recipient_id')}: {errs}"})
                else:
                    log.debug("wa_status", id=status.get("id"), status=status.get("status"))
    return n


async def send(event: dict[str, Any]) -> None:
    s = get_settings()
    to = event["channel_user_id"]
    url = f"{GRAPH}/{s.wa_phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {s.wa_access_token}"}
    body: dict[str, Any]
    if event.get("template"):
        body = {"messaging_product": "whatsapp", "to": to, "type": "template", "template": event["template"]}
    elif event.get("document_url"):
        body = {"messaging_product": "whatsapp", "to": to, "type": "document",
                "document": {"link": event["document_url"], "filename": event.get("filename", "cotacao.pdf"), "caption": event.get("text", "")[:1000]}}
    else:
        body = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"preview_url": True, "body": event["text"][:4096]}}
    async with httpx.AsyncClient(timeout=20, headers=headers) as c:
        r = await c.post(url, json=body)
        if r.status_code >= 400:
            try:
                err = r.json()
            except ValueError:
                err = {}
            err = err if isinstance(err, dict) else {}
            if delivery_failures.COUNTRY_RESTRICTED in delivery_failures.extract_error_codes(err):
                # 130497: falha permanente. Não retenta, não loga número nem corpo; registra e oferece outro canal.
                await delivery_failures.handle_permanent_failure(
                    category=delivery_failures.CAT_COUNTRY_RESTRICTED, source="sync", to=to, ref=delivery_failures.outbound_ref(event),
                    lead_id=event.get("lead_id"), error_code=delivery_failures.COUNTRY_RESTRICTED,
                    fbtrace_id=(err.get("error") or {}).get("fbtrace_id"), offer_alt_route=event.get("kind") != "ceo_alert")
                return
            log.error("wa_send_failed", status=r.status_code, body=r.text[:500])
            # janela de 24h fechada → precisa de template aprovado
            if "131047" in r.text or "131026" in r.text:
                await db.execute("INSERT INTO agent_runs (agent, trigger, input_summary, status, error) VALUES ('_channels','send','whatsapp template_required','error',$1)", r.text[:500])
            return
        await bus.publish("delivery", {"channel": "whatsapp", "to": to, "id": r.json().get("messages", [{}])[0].get("id")})
