"""Barramento de eventos em Redis Streams.

Streams:
  inbound   — mensagens de clientes normalizadas pelos canais  → consumidas pelo roteador/consultor
  outbound  — respostas para enviar                             → consumidas pelo despachante de canais
  tasks     — tarefas para agentes (cron ou eventos)            → consumidas pelo orquestrador
  alerts    — avisos para o CEO                                 → consumidas pelo despachante (WhatsApp do CEO)
  dlq       — eventos que esgotaram as tentativas (motivo, payload, tentativas, horários) → scripts/dlq.py
  retry:<stream> (ZSET) — reentregas agendadas com backoff; o orquestrador as devolve ao stream quando vencem
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


# ───────────────────────── retry agendado e DLQ (política em brain/core/retry.py) ─────────────────────────

DLQ, DLQ_AUDIT = "dlq", "dlq:replayed"

# move atomicamente os retries vencidos do ZSET para o stream (nem perde nem duplica se dois processos rodarem)
_PUMP_LUA = """
local items = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[1], 'LIMIT', 0, tonumber(ARGV[2]))
for _, m in ipairs(items) do
  local sep = string.find(m, '|', 1, true)
  redis.call('XADD', KEYS[2], 'MAXLEN', '~', 100000, '*', 'json', string.sub(m, sep + 1))
  redis.call('ZREM', KEYS[1], m)
end
return #items
"""
# reprocessa uma entrada da DLQ uma única vez: só republica se ela ainda existia (XDEL devolveu 1)
_REPLAY_LUA = """
if redis.call('XDEL', KEYS[1], ARGV[1]) == 1 then
  redis.call('XADD', KEYS[2], 'MAXLEN', '~', 100000, '*', 'json', ARGV[2])
  redis.call('XADD', KEYS[3], 'MAXLEN', '~', 10000, '*', 'json', ARGV[3])
  return 1
end
return 0
"""


async def schedule_retry(stream: str, event: dict[str, Any], delay_s: float) -> None:
    """Agenda a reentrega (durável: ZSET no Redis com AOF). Chamar ANTES do ack da mensagem original."""
    import time
    import uuid
    member = f"{uuid.uuid4().hex}|{json.dumps(event, ensure_ascii=False, default=str)}"
    await client().zadd(f"retry:{stream}", {member: time.time() + delay_s})


async def pump_retries(stream: str, limit: int = 100) -> int:
    import time
    return int(await client().eval(_PUMP_LUA, 2, f"retry:{stream}", stream, time.time(), limit))


async def dead_letter(record: dict[str, Any]) -> str:
    return await client().xadd(DLQ, {"json": json.dumps(record, ensure_ascii=False, default=str)}, maxlen=100_000)


async def dlq_entries(count: int = 50) -> list[tuple[str, dict[str, Any]]]:
    return [(i, json.loads(f["json"])) for i, f in await client().xrange(DLQ, count=count)]


async def dlq_replay(dlq_id: str, event: dict[str, Any], stream: str, audit: dict[str, Any]) -> bool:
    ok = await client().eval(_REPLAY_LUA, 3, DLQ, stream, DLQ_AUDIT, dlq_id,
                             json.dumps(event, ensure_ascii=False, default=str), json.dumps(audit, default=str))
    return bool(ok)


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
