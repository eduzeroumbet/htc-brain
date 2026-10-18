"""Webchat: widget próprio no site (por idioma) → POST /webhooks/webchat; respostas por Server-Sent Events em /webchat/stream/{session}.

Toda requisição precisa vir assinada (HMAC-SHA256, mesmo formato de brain/core/payment_webhook.py):
  X-Webchat-Signature: t=<unix em segundos>,v1=<hex de HMAC-SHA256(WEBCHAT_SIGNING_SECRET, "<t>." + corpo bruto)>
O corpo assinado é exatamente o enviado (sem reserializar). Fora da janela WEBCHAT_SIGNATURE_TOLERANCE_SECONDS → recusado.
O segredo NUNCA vai para o navegador: o widget posta para uma rota do próprio site (servidor), que assina e repassa.
Recusas: 401 sem assinatura; 403 assinatura inválida/fora da janela/segredo não configurado; 413 corpo grande;
400 corpo inválido; 429 com Retry-After ao passar do limite por IP ou por sessão (Redis, janela fixa).

Snippet para o site (troque DOMAIN e o market pela página; /api/webchat é a rota do servidor do site que assina):
<script>
(async () => {
  const sid = localStorage.getItem('dxb_sid') || crypto.randomUUID(); localStorage.setItem('dxb_sid', sid);
  const es = new EventSource(`https://DOMAIN/webchat/stream/${sid}`);
  es.onmessage = (e) => renderBotMessage(JSON.parse(e.data).text);
  window.sendToConsultant = (text) => fetch('/api/webchat', {method:'POST', headers:{'content-type':'application/json'},
    body: JSON.stringify({session_id: sid, text, market: 'BR', page: location.href})});
})();
</script>
Rota do servidor do site (ex.: Node): body = JSON.stringify(dados); t = Math.floor(Date.now()/1000);
  v1 = createHmac('sha256', process.env.WEBCHAT_SIGNING_SECRET).update(`${t}.${body}`).digest('hex');
  fetch('https://DOMAIN/webhooks/webchat', {method:'POST', body, headers:{'content-type':'application/json',
    'X-Webchat-Signature': `t=${t},v1=${v1}`}})
"""
from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from typing import Any, AsyncIterator

from brain.core import bus
from brain.core.payment_webhook import SignatureError, verify_signature
from brain.settings import get_settings

_queues: dict[str, asyncio.Queue] = defaultdict(asyncio.Queue)


def verify(raw_body: bytes, header: str | None, now: float | None = None) -> dict[str, Any]:
    """Devolve o payload se a assinatura vale e o corpo é uma mensagem do widget; senão SignatureError (sem detalhe ao cliente)."""
    s = get_settings()
    if len(raw_body) > s.webchat_max_body_bytes:
        raise SignatureError(413, "body_too_large")
    verify_signature(raw_body, header, s.webchat_signing_secret, s.webchat_signature_tolerance_s, now)
    try:
        payload = json.loads(raw_body)
    except ValueError:
        raise SignatureError(400, "body_not_json") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("session_id"), str) or not payload["session_id"].strip():
        raise SignatureError(400, "session_id_missing")
    if not isinstance(payload.get("text", ""), str):
        raise SignatureError(400, "text_invalid")
    if len(payload.get("text", "")) > s.webchat_max_text_chars:
        raise SignatureError(413, "text_too_long")
    return payload


async def retry_after(ip: str | None, session_id: str) -> int:
    """0 se cabe nos limites; senão segundos para o Retry-After. Só conta requisições já autenticadas."""
    s = get_settings()
    wait = await bus.rate_limit_retry_after(f"rl:webchat:ip:{ip or 'unknown'}", s.webchat_rate_limit_ip,
                                            s.webchat_rate_limit_ip_window_s)
    if wait:
        return wait
    return await bus.rate_limit_retry_after(f"rl:webchat:sess:{session_id}", s.webchat_rate_limit_session,
                                            s.webchat_rate_limit_session_window_s)


async def handle_post(payload: dict[str, Any]) -> int:
    await bus.publish(bus.INBOUND, {
        "channel": "webchat", "channel_user_id": payload["session_id"], "display_name": payload.get("name"),
        "email": payload.get("email"), "text": payload.get("text", ""), "market_code": payload.get("market"),
        "message_id": None, "page": payload.get("page"),
    })
    return 1


async def send(event: dict[str, Any]) -> None:
    await _queues[event["channel_user_id"]].put({"text": event["text"], "document_url": event.get("document_url")})


async def stream(session_id: str) -> AsyncIterator[str]:
    q = _queues[session_id]
    while True:
        try:
            item = await asyncio.wait_for(q.get(), timeout=25)
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
        except asyncio.TimeoutError:
            yield ": keepalive\n\n"
