"""Barramento de eventos em Redis Streams.

Streams:
  inbound   — mensagens de clientes normalizadas pelos canais  → consumidas pelo roteador/consultor
  outbound  — respostas para enviar                             → consumidas pelo despachante de canais
  tasks     — tarefas para agentes (cron ou eventos)            → consumidas pelo orquestrador
  alerts    — avisos para o CEO                                 → consumidas pelo despachante (WhatsApp do CEO)
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

import redis.asyncio as aioredis

from brain.settings import get_settings

import structlog
log = structlog.get_logger(__name__)

INBOUND, OUTBOUND, TASKS, ALERTS = "inbound", "outbound", "tasks", "alerts"
_client: aioredis.Redis | None = None


def client() -> aioredis.Redis:
    global _client
    if _client is None:
        # socket_timeout=None é obrigatório: XREADGROUP bloqueia até block_ms e um timeout de socket menor mata o worker
        _client = aioredis.from_url(get_settings().redis_url, decode_responses=True, socket_timeout=None,
                                    socket_connect_timeout=10, socket_keepalive=True, health_check_interval=30, retry_on_timeout=True)
    return _client


async def publish(stream: str, event: dict[str, Any]) -> str:
    return await client().xadd(stream, {"json": json.dumps(event, ensure_ascii=False, default=str)}, maxlen=100_000)


async def ensure_group(stream: str, group: str) -> None:
    try:
        await client().xgroup_create(stream, group, id="$", mkstream=True)
    except aioredis.ResponseError as exc:  # grupo já existe
        if "BUSYGROUP" not in str(exc):
            raise


async def consume(stream: str, group: str, consumer: str, block_ms: int = 2000) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Itera eventos do grupo; o chamador deve dar ack(). Na partida, reclama mensagens pendentes de consumidores mortos."""
    await ensure_group(stream, group)
    try:  # XAUTOCLAIM: entregas que ficaram presas (processo reiniciado no meio) voltam para este consumidor
        claimed = await client().xautoclaim(stream, group, consumer, min_idle_time=60_000, start_id="0-0", count=10)
        for msg_id, fields in (claimed[1] if claimed else []):
            if fields:
                yield msg_id, json.loads(fields["json"])
    except Exception:  # noqa: BLE001
        pass
    while True:
        try:
            resp = await client().xreadgroup(group, consumer, {stream: ">"}, count=10, block=block_ms)
        except (TimeoutError, aioredis.TimeoutError, aioredis.ConnectionError) as exc:
            log.warning("redis_read_retry", stream=stream, consumer=consumer, error=str(exc)[:120])
            await asyncio.sleep(1)
            continue
        if not resp:
            continue
        for _stream, entries in resp:
            for msg_id, fields in entries:
                yield msg_id, json.loads(fields["json"])


async def ack(stream: str, group: str, msg_id: str) -> None:
    await client().xack(stream, group, msg_id)


# ───────────────────────── chaves auxiliares ─────────────────────────

async def rate_limit(key: str, limit: int, window_s: int) -> bool:
    """True se ainda cabe dentro do limite (ex.: mensagens ativas por lead por dia)."""
    r = client()
    n = await r.incr(key)
    if n == 1:
        await r.expire(key, window_s)
    return n <= limit


async def cache_get(key: str) -> Any | None:
    v = await client().get(key)
    return json.loads(v) if v else None


async def cache_set(key: str, value: Any, ttl_s: int = 3600) -> None:
    await client().set(key, json.dumps(value, default=str), ex=ttl_s)
