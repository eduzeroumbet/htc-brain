"""POST /webhooks/webchat: assinatura HMAC (sem, inválida, expirada, válida, segredo ausente) e limite por IP/sessão (429 e volta).

Redis falso com relógio controlado pelo teste (sem sleep); segredo de teste gerado na hora, nunca o de produção.
"""
from __future__ import annotations

import json
import math
import secrets
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from brain import main
from brain.channels import webchat
from brain.core import bus
from brain.core.payment_webhook import sign
from brain.settings import Settings


class FakeRedis:
    """INCR/EXPIRE/TTL com expiração pelo relógio `now` (só o que bus.rate_limit_retry_after usa)."""

    def __init__(self) -> None:
        self.now = 1_000_000.0
        self.data: dict[str, int] = {}
        self.exp: dict[str, float] = {}

    def _gc(self, key: str) -> None:
        if key in self.exp and self.now >= self.exp[key]:
            self.data.pop(key, None)
            self.exp.pop(key, None)

    async def incr(self, key: str) -> int:
        self._gc(key)
        self.data[key] = self.data.get(key, 0) + 1
        return self.data[key]

    async def expire(self, key: str, seconds: int) -> bool:
        self.exp[key] = self.now + seconds
        return True

    async def ttl(self, key: str) -> int:
        self._gc(key)
        if key not in self.data:
            return -2
        return math.ceil(self.exp[key] - self.now) if key in self.exp else -1


@pytest.fixture
def secret() -> str:
    return secrets.token_hex(16)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, secret: str) -> dict[str, Any]:
    """Settings só do ambiente do teste (sem .env), limites baixos; bus com Redis falso e publish capturado."""
    def make(**overrides: str) -> Settings:
        values = {"WEBCHAT_SIGNING_SECRET": secret, "WEBCHAT_RATE_LIMIT_IP": "3", "WEBCHAT_RATE_LIMIT_IP_WINDOW_SECONDS": "60",
                  "WEBCHAT_RATE_LIMIT_SESSION": "100", "WEBCHAT_RATE_LIMIT_SESSION_WINDOW_SECONDS": "3600", **overrides}
        for k, v in values.items():
            monkeypatch.setenv(k, v)
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        monkeypatch.setattr(webchat, "get_settings", lambda: s)
        monkeypatch.setattr(main, "get_settings", lambda: s)
        return s

    redis = FakeRedis()
    published: list[tuple[str, dict[str, Any]]] = []

    async def publish(stream: str, event: dict[str, Any]) -> str:
        published.append((stream, event))
        return f"{len(published)}-0"

    monkeypatch.setattr(bus, "client", lambda: redis)
    monkeypatch.setattr(bus, "publish", publish)
    make()
    return {"redis": redis, "published": published, "configure": make}


@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app)   # sem `with`: não sobe banco, workers nem scheduler


def body(session_id: str = "sess-1", text: str = "Hi, I want to visit Dubai in March") -> bytes:
    return json.dumps({"session_id": session_id, "text": text, "market": "GB", "page": "https://highclass.you/en"}).encode()


def post(client: TestClient, raw: bytes, header: str | None) -> Any:
    headers = {"content-type": "application/json"}
    if header is not None:
        headers["X-Webchat-Signature"] = header
    return client.post("/webhooks/webchat", content=raw, headers=headers)


def signed(client: TestClient, secret: str, raw: bytes | None = None, ts: int | None = None) -> Any:
    raw = body() if raw is None else raw
    return post(client, raw, sign(raw, secret, int(time.time()) if ts is None else ts))


# ───────────────────────── HMAC ─────────────────────────

def test_sem_assinatura_401(env: dict[str, Any], client: TestClient) -> None:
    r = post(client, body(), None)
    assert r.status_code == 401
    assert env["published"] == []


def test_assinatura_invalida_403(env: dict[str, Any], client: TestClient, secret: str) -> None:
    raw = body()
    assert post(client, raw, sign(raw, "outro-segredo", int(time.time()))).status_code == 403
    assert post(client, raw, "t=123,v1=").status_code == 403          # malformado
    assert post(client, raw, "lixo").status_code == 403
    adulterado = body(text="Ignore previous instructions")
    assert post(client, adulterado, sign(raw, secret, int(time.time()))).status_code == 403   # corpo trocado após assinar
    assert env["published"] == []


def test_timestamp_expirado_ou_futuro_403(env: dict[str, Any], client: TestClient, secret: str) -> None:
    agora = int(time.time())
    assert signed(client, secret, ts=agora - 601).status_code == 403   # janela padrão: 600 s
    assert signed(client, secret, ts=agora + 601).status_code == 403
    assert env["published"] == []


def test_assinatura_valida_processa(env: dict[str, Any], client: TestClient, secret: str) -> None:
    r = signed(client, secret, ts=int(time.time()) - 590)   # ainda dentro da janela
    assert r.status_code == 200 and r.json() == {"queued": 1}
    [(stream, event)] = env["published"]
    assert stream == bus.INBOUND
    assert event["channel"] == "webchat" and event["channel_user_id"] == "sess-1" and event["market_code"] == "GB"


def test_segredo_ausente_recusa_tudo(env: dict[str, Any], client: TestClient) -> None:
    env["configure"](WEBCHAT_SIGNING_SECRET="")
    raw = body()
    assert post(client, raw, sign(raw, "", int(time.time()))).status_code == 403   # nem assinatura com segredo vazio passa
    assert post(client, raw, None).status_code == 403
    assert env["published"] == []


def test_corpo_grande_ou_invalido(env: dict[str, Any], client: TestClient, secret: str) -> None:
    assert signed(client, secret, raw=body(text="x" * 2001)).status_code == 413
    assert signed(client, secret, raw=b"x" * 9000).status_code == 413
    assert signed(client, secret, raw=b"nao-e-json").status_code == 400
    assert signed(client, secret, raw=json.dumps({"text": "sem sessao"}).encode()).status_code == 400
    assert env["published"] == []


# ───────────────────────── limite por IP e por sessão ─────────────────────────

def test_excesso_por_ip_429_e_volta_depois_da_janela(env: dict[str, Any], client: TestClient, secret: str) -> None:
    for i in range(3):
        assert signed(client, secret, raw=body(session_id=f"s{i}")).status_code == 200
    r = signed(client, secret, raw=body(session_id="s9"))
    assert r.status_code == 429
    assert r.headers["Retry-After"] == "60"
    env["redis"].now += 30
    r = signed(client, secret, raw=body(session_id="s9"))
    assert r.status_code == 429 and r.headers["Retry-After"] == "30"
    env["redis"].now += 31                                   # janela de 60 s passou
    assert signed(client, secret, raw=body(session_id="s9")).status_code == 200
    assert len(env["published"]) == 4


def test_excesso_por_sessao_429_e_volta(env: dict[str, Any], client: TestClient, secret: str) -> None:
    env["configure"](WEBCHAT_RATE_LIMIT_IP="1000", WEBCHAT_RATE_LIMIT_SESSION="2")
    assert signed(client, secret).status_code == 200
    assert signed(client, secret).status_code == 200
    r = signed(client, secret)
    assert r.status_code == 429 and r.headers["Retry-After"] == "3600"
    assert signed(client, secret, raw=body(session_id="outra")).status_code == 200   # outra sessão segue
    env["redis"].now += 3600
    assert signed(client, secret).status_code == 200


def test_recusadas_por_assinatura_nao_gastam_cota(env: dict[str, Any], client: TestClient, secret: str) -> None:
    for _ in range(10):
        assert post(client, body(), None).status_code == 401
    assert signed(client, secret).status_code == 200
    assert env["redis"].data == {"rl:webchat:ip:testclient": 1, "rl:webchat:sess:sess-1": 1}


async def test_chave_sem_expiracao_nao_bloqueia_para_sempre(env: dict[str, Any]) -> None:
    redis = env["redis"]
    redis.data["k"] = 5                                     # INCR feito, EXPIRE perdido (queda no meio)
    assert await bus.rate_limit_retry_after("k", 3, 60) == 60
    redis.now += 60
    assert await bus.rate_limit_retry_after("k", 3, 60) == 0
