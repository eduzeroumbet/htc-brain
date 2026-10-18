"""Webchat: widget próprio no site (por idioma) → POST /webhooks/webchat; respostas por Server-Sent Events em /webchat/stream/{session}.

Snippet para o site (troque DOMAIN e o market pela página):
<script>
(async () => {
  const sid = localStorage.getItem('dxb_sid') || crypto.randomUUID(); localStorage.setItem('dxb_sid', sid);
  const es = new EventSource(`https://DOMAIN/webchat/stream/${sid}`);
  es.onmessage = (e) => renderBotMessage(JSON.parse(e.data).text);
  window.sendToConsultant = (text) => fetch('https://DOMAIN/webhooks/webchat', {method:'POST', headers:{'content-type':'application/json'},
    body: JSON.stringify({session_id: sid, text, market: 'BR', page: location.href})});
})();
</script>
"""
from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from typing import Any, AsyncIterator

from brain.core import bus

_queues: dict[str, asyncio.Queue] = defaultdict(asyncio.Queue)


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
