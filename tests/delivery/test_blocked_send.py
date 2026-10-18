"""BlockedSendError: envio barrado por política não retenta nem vai para a DLQ; PermanentError (4xx) segue para a DLQ.

Sem rede, sem Redis: o sink é falso.
"""
from __future__ import annotations

from typing import Any

from brain.core import retry


class FakeSink:
    def __init__(self) -> None:
        self.retries: list[tuple[str, dict[str, Any], float]] = []
        self.dead: list[dict[str, Any]] = []

    async def schedule_retry(self, stream: str, event: dict[str, Any], delay_s: float) -> None:
        self.retries.append((stream, event, delay_s))

    async def dead_letter(self, record: dict[str, Any]) -> None:
        self.dead.append(record)


EVENT = {"channel": "whatsapp", "channel_user_id": "5511900000001", "text": "promo", "purpose": "marketing", "lead_id": "L1"}


def test_blocked_send_nao_herda_de_permanent_error() -> None:
    assert not issubclass(retry.BlockedSendError, retry.PermanentError)
    assert not issubclass(retry.BlockedSendError, retry.TransientError)


def test_blocked_send_descarta_sem_retry_e_sem_dlq() -> None:
    d = retry.decide(EVENT, retry.BlockedSendError("sem consentimento"), retry.RetryPolicy())
    assert d.action == "discard"


async def test_route_failure_blocked_nao_toca_no_sink() -> None:
    sink = FakeSink()
    d = await retry.route_failure(sink, "outbound", "1-0", EVENT, retry.BlockedSendError("br pausado"), retry.RetryPolicy())
    assert d.action == "discard"
    assert sink.retries == [] and sink.dead == []


async def test_permanent_error_continua_indo_para_dlq() -> None:
    sink = FakeSink()
    d = await retry.route_failure(sink, "outbound", "1-0", EVENT, retry.http_failure("whatsapp", 400), retry.RetryPolicy())
    assert d.action == "dlq"
    assert sink.retries == [] and len(sink.dead) == 1
