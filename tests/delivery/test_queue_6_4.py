"""Cenário 6.4 — fila de envio: ack só depois de sucesso (ou falha gravada), backoff exponencial com jitter, 5 tentativas,
130497 direto ao stream dlq, DLQ sem segredos e sem mensagem duplicada.

Redis, banco e Graph simulados; relógio e jitter fixos. O ciclo da fila é o de produção (orchestrator.process_message +
retry.route_failure); o FakeQueue só imita o Redis (stream, ZSET de retries, DLQ, marcas de envio e acks).
"""
from __future__ import annotations

import json
import secrets
from typing import Any

import pytest

from brain.channels import dispatch
from brain.core import orchestrator, retry
from tests.delivery.conftest import AE, IN, restricted_body

POLICY = retry.RetryPolicy(max_attempts=5, base_delay_s=2.0, max_delay_s=600.0, jitter_ratio=0.2)
OK = (200, {"messages": [{"id": "wamid.OK"}]})
FAIL_5XX = (500, {"error": {"code": 1, "message": "Unknown error"}})


class FixedJitter:
    """Jitter determinístico: sempre o topo da faixa (+ratio)."""

    def uniform(self, a: float, b: float) -> float:
        return b


def clock() -> float:
    return 1_000.0


class FakeQueue:
    """Redis simulado: stream de saída, retries agendados (vencem na hora), DLQ, marcas de envio e acks."""

    def __init__(self) -> None:
        self.seq = 0
        self.stream: list[tuple[str, dict[str, Any]]] = []
        self.retries: list[dict[str, Any]] = []
        self.delays: list[float] = []
        self.dlq: list[dict[str, Any]] = []
        self.acks: list[str] = []
        self.delivered: set[str] = set()
        self.fail_schedule = False

    def add(self, event: dict[str, Any]) -> str:
        self.seq += 1
        msg_id = f"{self.seq}-0"
        self.stream.append((msg_id, json.loads(json.dumps(event, default=str))))   # o Redis guarda JSON
        return msg_id

    async def schedule_retry(self, stream: str, event: dict[str, Any], delay_s: float) -> None:
        if self.fail_schedule:
            raise ConnectionError("redis fora do ar")
        self.retries.append(event)
        self.delays.append(delay_s)

    async def dead_letter(self, record: dict[str, Any]) -> str:
        self.dlq.append(json.loads(json.dumps(record, default=str)))
        return f"dlq-{len(self.dlq)}"

    async def ack(self, stream: str, group: str, msg_id: str) -> None:
        self.acks.append(msg_id)

    async def already_delivered(self, key: str) -> bool:
        return key in self.delivered

    async def mark_delivered(self, key: str) -> None:
        self.delivered.add(key)

    def pump(self) -> None:
        """Como bus.pump_retries: retry vencido volta ao stream com id novo."""
        while self.retries:
            self.add(self.retries.pop(0))

    async def drain(self, handler) -> list[str]:
        out = []
        while self.stream:
            msg_id, event = self.stream.pop(0)
            out.append(await orchestrator.process_message("outbound", handler, msg_id, event, POLICY, sink=self,
                                                          rng=FixedJitter(), clock=clock))
            self.pump()
        return out


def scripted(graph, responses: list[tuple[int, dict[str, Any]]]):
    """Handler de produção (dispatch → whatsapp.send) com a Graph respondendo em sequência."""
    it = iter(responses)

    async def handler(event: dict[str, Any]) -> None:
        graph.respond(*next(it))
        await dispatch(event)
    return handler


def wa(to: str = AE, **extra: Any) -> dict[str, Any]:
    return {"channel": "whatsapp", "channel_user_id": to, "text": "Seu roteiro em Dubai está pronto.", **extra}


# T-6.4.1 ─ 3ª tentativa com sucesso, sem duplicar mensagem
async def test_third_attempt_succeeds_without_duplicate(settings, fake_db, fake_bus, graph):
    q = FakeQueue()
    first = q.add(wa())
    outcomes = await q.drain(scripted(graph, [FAIL_5XX, (503, {}), OK]))

    assert outcomes == ["retry", "retry", "sent"]
    assert len(graph.calls) == 3                               # 2 falhas + 1 envio que deu certo
    assert len(fake_bus.on("delivery")) == 1                   # uma única mensagem entregue
    assert q.dlq == []
    assert len(q.acks) == len(set(q.acks)) == 3                # cada entrada do stream recebe um único ack
    assert q.delays == pytest.approx([2.4, 4.8])               # 2·2^(n-1) · (1 + 0.2): exponencial com jitter
    assert q.delivered == {first}                              # a chave do envio é o id da 1ª entrega, em todos os retries

    # o worker cai depois do envio e antes do ack: a mesma entrega volta ao stream e NÃO é enviada de novo
    q.add({**wa(), retry.META_KEY: {"delivery_id": first, "attempts": 2}})
    assert await q.drain(scripted(graph, [OK])) == ["duplicate"]
    assert len(graph.calls) == 3 and len(fake_bus.on("delivery")) == 1


# T-6.4.2 ─ 5 falhas transitórias → DLQ com payload, tentativas e last_error, sem segredos
async def test_five_failures_go_to_dlq(settings, fake_db, fake_bus, graph):
    q = FakeQueue()
    q.add(wa())
    outcomes = await q.drain(scripted(graph, [FAIL_5XX] * 5))

    assert outcomes == ["retry"] * 4 + ["dlq"]
    assert len(graph.calls) == 5 and fake_bus.on("delivery") == []
    assert q.delays == pytest.approx([2.4, 4.8, 9.6, 19.2])
    assert len(q.acks) == 5                                    # nenhuma entrada fica perdida nem pendente
    [rec] = q.dlq
    assert rec["source_stream"] == "outbound" and rec["attempts"] == 5
    assert rec["last_error"].startswith("max_attempts(5)") and "HTTP 500" in rec["last_error"]
    assert rec["payload"] == wa()                              # payload para reprocessar (sem os metadados internos)
    assert rec["first_failed_at"] == rec["dead_at"] == 1_000.0
    assert settings.wa_access_token not in json.dumps(rec)


async def test_dlq_record_has_no_secrets(settings, fake_db, fake_bus):
    token = "EAA" + secrets.token_hex(20)
    api_key = secrets.token_hex(16)

    async def leaky(event: dict[str, Any]) -> None:   # erro de rede cuja mensagem traz URL com token e o telefone
        raise ConnectionError(f"POST https://graph.facebook.com/v21.0/x?access_token={token} para +971 50 000 0001 falhou")

    q = FakeQueue()
    q.add(wa(api_key=api_key, authorization=f"Bearer {token}"))
    assert await q.drain(leaky) == ["retry"] * 4 + ["dlq"]

    [rec] = q.dlq
    dumped = json.dumps(rec)
    assert token not in dumped and api_key not in dumped
    assert "+971 50 000 0001" not in rec["last_error"] and "0001" in rec["last_error"]   # telefone mascarado no erro
    assert rec["payload"]["api_key"] == rec["payload"]["authorization"] == "***REDACTED***"
    assert rec["payload"]["channel_user_id"] == AE           # o destino fica: sem ele o replay não envia


# T-6.4.3 ─ 130497 vai direto ao stream dlq, sem retentativa, reaproveitando o runbook (registro + rota alternativa)
async def test_130497_goes_straight_to_dlq(settings, approved_cfg, fake_db, fake_bus, graph):
    q = FakeQueue()
    q.add(wa(to=IN))
    outcomes = await q.drain(scripted(graph, [(400, restricted_body())]))

    assert outcomes == ["dlq"]
    assert len(graph.calls) == 1 and q.retries == [] and q.delays == []
    [rec] = q.dlq
    assert rec["attempts"] == 1 and rec["error_code"] == 130497
    assert rec["last_error"].startswith("permanent") and "130497" in rec["last_error"]
    assert IN not in rec["last_error"]
    assert q.acks == ["1-0"]
    [ev] = fake_db.events                                      # runbook do 130497 rodou uma vez (código + mercado)
    assert (ev["error_code"], ev["market_code"], ev["retryable"]) == (130497, "IN", False)


# ack só depois de a falha estar gravada: sem retry durável, a entrega fica pendente no stream
async def test_no_ack_when_failure_not_recorded(settings, fake_db, fake_bus, graph):
    q = FakeQueue()
    q.fail_schedule = True
    q.add(wa())
    assert await q.drain(scripted(graph, [FAIL_5XX])) == ["pending"]
    assert q.acks == [] and q.dlq == []


def test_backoff_is_capped_and_jittered():
    p = retry.RetryPolicy(max_attempts=5, base_delay_s=2.0, max_delay_s=10.0, jitter_ratio=0.2)
    assert p.delay(10, rng=FixedJitter()) == 10.0              # teto
    low = type("Low", (), {"uniform": lambda self, a, b: a})()
    assert p.delay(2, rng=low) == pytest.approx(3.2)           # 4 · (1 − 0.2)
    assert p.delay(1, retry_after=7, rng=low) == 7.0           # Retry-After do destino prevalece
