"""Política de retry da fila: backoff exponencial com jitter, limite de tentativas e DLQ.

Usado pelo orquestrador (brain/core/orchestrator._loop). Sem dependências: dá para testar sem Redis.

- PermanentError (ou HTTP 4xx que não seja 408/425/429) → DLQ direto, sem retentar.
- BlockedSendError (envio barrado por política: consentimento, pausa do Brasil) → descarta com registro: sem retry e
  sem DLQ, para o replay nunca reenviar marketing revogado nem +55 pausado. Não herda de PermanentError por isso.
- Demais falhas → retry até max_attempts; depois, DLQ com motivo, payload, tentativas e carimbos de hora.
- Atraso da tentativa n (n ≥ 1): min(cap, base·2^(n-1)) com jitter de ±ratio; respeita Retry-After quando houver.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any

from brain.core.logsafe import redact

META_KEY = "_delivery"          # metadados de entrega guardados dentro do evento (tentativas, primeiro erro)


class PermanentError(Exception):
    """Falha que não melhora com retry (destinatário inválido, 130497, payload recusado). Vai direto para a DLQ."""


class BlockedSendError(Exception):
    """Envio barrado por política (sem consentimento de marketing, Brasil pausado). Não é falha de entrega: não retenta,
    não vai para a DLQ e não conta como 130497 (esse segue em delivery_failures.handle_permanent_failure)."""


class TransientError(Exception):
    """Falha que pode passar (rede, 5xx, 429). `retry_after` em segundos, se o destino informou."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 5
    base_delay_s: float = 2.0
    max_delay_s: float = 600.0
    jitter_ratio: float = 0.2

    def delay(self, attempt: int, retry_after: float | None = None, rng: random.Random | None = None) -> float:
        """Atraso antes da próxima tentativa, dado que `attempt` tentativas já falharam."""
        raw = min(self.max_delay_s, self.base_delay_s * (2 ** max(0, attempt - 1)))
        r = (rng or random).uniform(-self.jitter_ratio, self.jitter_ratio)
        d = max(0.0, raw * (1 + r))
        if retry_after:
            d = max(d, float(retry_after))
        return min(d, self.max_delay_s)


def http_failure(label: str, status: int, retry_after: str | None = None, code: Any = None) -> Exception:
    """Erro tipado para resposta HTTP de falha de um canal (sem corpo: pode conter dados do cliente)."""
    msg = f"{label} HTTP {status}" + (f" code={code}" if code is not None else "")
    if status in (408, 425, 429) or status >= 500:
        try:
            ra = float(retry_after) if retry_after else None
        except ValueError:
            ra = None
        return TransientError(msg, retry_after=ra)
    return PermanentError(msg)


def is_permanent(exc: BaseException) -> bool:
    if isinstance(exc, PermanentError):
        return True
    if isinstance(exc, (TransientError, TimeoutError, ConnectionError)):
        return False
    status = getattr(getattr(exc, "response", None), "status_code", None)      # httpx.HTTPStatusError
    if isinstance(status, int):
        return 400 <= status < 500 and status not in (408, 425, 429)
    return isinstance(exc, (KeyError, ValueError, TypeError))                   # payload malformado: retry não resolve


@dataclass(frozen=True)
class Decision:
    action: str                 # "retry" | "dlq" | "discard"
    attempts: int               # tentativas já feitas (incluindo a que acabou de falhar)
    delay_s: float = 0.0
    reason: str = ""


def decide(event: dict[str, Any], exc: BaseException, policy: RetryPolicy, rng: random.Random | None = None) -> Decision:
    attempts = int((event.get(META_KEY) or {}).get("attempts", 0)) + 1
    reason = redact(f"{type(exc).__name__}: {exc}")[:500]      # mensagens de erro podem trazer URL com token
    if isinstance(exc, BlockedSendError):
        return Decision("discard", attempts, reason=f"blocked · {reason}")
    if is_permanent(exc):
        return Decision("dlq", attempts, reason=f"permanent · {reason}")
    if attempts >= policy.max_attempts:
        return Decision("dlq", attempts, reason=f"max_attempts({policy.max_attempts}) · {reason}")
    return Decision("retry", attempts, policy.delay(attempts, getattr(exc, "retry_after", None), rng), reason)


def with_attempt(event: dict[str, Any], decision: Decision, now: float | None = None) -> dict[str, Any]:
    """Cópia do evento com o contador de tentativas atualizado (o que volta para a fila)."""
    now = time.time() if now is None else now
    meta = dict(event.get(META_KEY) or {})
    meta.setdefault("first_failed_at", now)
    meta.update(attempts=decision.attempts, last_error=decision.reason, last_failed_at=now)
    return {**event, META_KEY: meta}


def dlq_record(stream: str, msg_id: str, event: dict[str, Any], decision: Decision, now: float | None = None) -> dict[str, Any]:
    """Registro da DLQ: fila de origem, id original, motivo, tentativas, carimbos e o payload completo para reprocessar."""
    now = time.time() if now is None else now
    meta = event.get(META_KEY) or {}
    payload = {k: v for k, v in event.items() if k != META_KEY}
    return {"source_stream": stream, "source_id": msg_id, "reason": redact(decision.reason), "attempts": decision.attempts,
            "first_failed_at": meta.get("first_failed_at", now), "dead_at": now, "payload": payload}


async def route_failure(sink: Any, stream: str, msg_id: str, event: dict[str, Any], exc: BaseException,
                        policy: RetryPolicy, rng: random.Random | None = None) -> Decision:
    """Grava a falha de forma durável (retry agendado ou DLQ). Só depois disso o chamador pode dar ack.
    `sink` expõe schedule_retry(stream, event, delay_s) e dead_letter(record) — brain.core.bus em produção."""
    decision = decide(event, exc, policy, rng)
    if decision.action == "discard":
        return decision                                         # o registro fica no log handler_failed do chamador
    if decision.action == "retry":
        await sink.schedule_retry(stream, with_attempt(event, decision), decision.delay_s)
    else:
        await sink.dead_letter(dlq_record(stream, msg_id, with_attempt(event, decision), decision))
    return decision


def for_replay(record: dict[str, Any], dlq_id: str) -> dict[str, Any]:
    """Evento a republicar a partir da DLQ: contador zerado, histórico preservado."""
    history = {"replayed_from": dlq_id, "previous_attempts": record.get("attempts"), "previous_reason": record.get("reason")}
    return {**record["payload"], META_KEY: {"attempts": 0, "replays": [history]}}
