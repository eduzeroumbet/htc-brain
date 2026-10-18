"""Lease com fencing token para o balcão de propostas (proposal_requests, migração 012).

claim   — pega UMA solicitação livre (sem lease ou com lease vencido) com FOR UPDATE SKIP LOCKED numa única
          instrução: dois workers nunca recebem a mesma linha. Cada captura incrementa fencing_token.
renew   — estende o lease só se quem pede ainda é o dono (locked_by + fencing_token) e o lease não venceu.
finish  — grava o resultado só se o token ainda é o atual. Worker "zumbi" (lease vencido e linha recapturada,
          token maior) recebe False e não pode enviar nada ao cliente.
release — devolve a linha sem resultado (falha do worker), para outro tentar já.

Worker que morre sem liberar: o lease vence sozinho após o TTL e a linha volta a ser elegível.
As funções recebem o módulo de banco (brain.core.db) como parâmetro para poderem ser testadas sem Postgres.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

OPEN_STATUSES = ("requested", "interim_sent")


class DB(Protocol):
    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class Lease:
    request_id: str
    owner: str
    token: int


CLAIM_SQL = """
UPDATE proposal_requests p
   SET locked_by = $1, locked_until = now() + make_interval(secs => $2), fencing_token = p.fencing_token + 1,
       attempts = p.attempts + 1
  FROM (SELECT id FROM proposal_requests
         WHERE status IN ('requested','interim_sent') AND (locked_until IS NULL OR locked_until < now())
         ORDER BY due_at
         LIMIT 1
         FOR UPDATE SKIP LOCKED) c
 WHERE p.id = c.id
RETURNING p.id, p.fencing_token"""

RENEW_SQL = """
UPDATE proposal_requests SET locked_until = now() + make_interval(secs => $4)
 WHERE id = $1 AND locked_by = $2 AND fencing_token = $3 AND locked_until > now()
RETURNING id"""

FINISH_SQL = """
UPDATE proposal_requests
   SET status = $4,
       quote_id = COALESCE($5::uuid, quote_id),
       sent_at = CASE WHEN $4 = 'sent' THEN now() ELSE sent_at END,
       escalated_at = CASE WHEN $4 = 'escalated' THEN now() ELSE escalated_at END,
       locked_by = NULL, locked_until = NULL
 WHERE id = $1 AND locked_by = $2 AND fencing_token = $3
RETURNING id"""

RELEASE_SQL = """
UPDATE proposal_requests SET locked_by = NULL, locked_until = NULL
 WHERE id = $1 AND locked_by = $2 AND fencing_token = $3
RETURNING id"""


async def claim(db: DB, owner: str, ttl_s: int) -> Lease | None:
    row = await db.fetchrow(CLAIM_SQL, owner, float(ttl_s))
    return Lease(str(row["id"]), owner, int(row["fencing_token"])) if row else None


async def renew(db: DB, lease: Lease, ttl_s: int) -> bool:
    return await db.fetchrow(RENEW_SQL, lease.request_id, lease.owner, lease.token, float(ttl_s)) is not None


async def finish(db: DB, lease: Lease, status: str, quote_id: str | None = None) -> bool:
    if status not in ("sent", "escalated"):
        raise ValueError("status final inválido")
    return await db.fetchrow(FINISH_SQL, lease.request_id, lease.owner, lease.token, status, quote_id) is not None


async def release(db: DB, lease: Lease) -> bool:
    return await db.fetchrow(RELEASE_SQL, lease.request_id, lease.owner, lease.token) is not None
