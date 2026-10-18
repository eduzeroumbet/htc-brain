"""Envio simulado: banco, Redis e Graph API falsos. Qualquer tentativa de rede real (HTTP ou SMTP) derruba o teste."""
from __future__ import annotations

import secrets
from collections import Counter
from datetime import date
from typing import Any

import httpx
import pytest

from brain.channels import delivery_failures as df
from brain.channels import whatsapp
from brain.settings import Settings, alt_route_config

BR = "5511900000001"      # números fictícios
IN = "919800000001"
AE = "971500000001"
GB = "447700000001"


class FakeDB:
    """Responde só às consultas do fluxo de falha permanente; SQL inesperado falha o teste."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.leads: list[dict[str, Any]] = []
        self.inbound: list[tuple[str, str]] = []
        self.dsar: list[dict[str, Any]] = []
        self.agent_runs: list[tuple[Any, ...]] = []

    def add_lead(self, id: str, channel: str, channel_user_id: str, phone: str | None = None, email: str | None = None) -> None:
        self.leads.append({"id": id, "channel": channel, "channel_user_id": channel_user_id, "phone": phone, "email": email})

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
        if sql.lstrip().startswith("INSERT INTO delivery_failure_events"):
            code, cat, market, prefix, source, ref, lead_id, wamid, fbtrace = args
            if any(e["outbound_ref"] == ref and e["category"] == cat for e in self.events):
                return None   # UNIQUE (outbound_ref, category)
            ev = {"id": f"ev{len(self.events) + 1}", "day": date.today(), "error_code": code, "category": cat,
                  "market_code": market, "country_prefix": prefix, "source": source, "outbound_ref": ref, "lead_id": lead_id,
                  "wamid": wamid, "fbtrace_id": fbtrace, "retryable": False, "delivery_status": "failed_permanent",
                  "alt_route_status": None, "alt_route_channel": None}
            self.events.append(ev)
            return {"id": ev["id"]}
        if "FROM leads WHERE channel = 'whatsapp'" in sql:
            return next(({"id": lead["id"]} for lead in self.leads
                         if lead["channel"] == "whatsapp" and lead["channel_user_id"] == args[0]), None)
        if "FROM data_requests" in sql:
            ids = set(args[0])
            for d in self.dsar:
                if d["lead_id"] not in ids:
                    continue
                if "status NOT IN" in sql and d["status"] not in ("completed", "refused"):
                    return {"?column?": 1}
                if "kind IN" in sql and d["kind"] in ("consent_withdrawal", "objection", "erasure"):
                    return {"?column?": 1}
            return None
        raise AssertionError(f"SQL inesperado: {sql[:90]}")

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        if "WITH me AS" in sql:
            me = next(lead for lead in self.leads if lead["id"] == args[0])
            return [{"id": lead["id"], "channel": lead["channel"], "channel_user_id": lead["channel_user_id"]}
                    for lead in self.leads
                    if lead["id"] == me["id"] or (me["phone"] and lead["phone"] == me["phone"])
                    or (me["email"] and lead["email"] == me["email"])]
        if "FROM messages m" in sql:
            ids = set(args[0])
            return [{"lead_id": lid, "body": body} for lid, body in self.inbound if lid in ids]
        if "FROM delivery_failure_events" in sql:
            agg = Counter((e["day"], e["market_code"], e["category"]) for e in self.events)
            return [{"day": d, "market_code": m, "category": c, "n": n} for (d, m, c), n in sorted(agg.items())]
        raise AssertionError(f"SQL inesperado: {sql[:90]}")

    async def execute(self, sql: str, *args: Any) -> str:
        if sql.lstrip().startswith("UPDATE delivery_failure_events"):
            ev = next(e for e in self.events if e["id"] == args[0])
            ev["alt_route_status"], ev["alt_route_channel"] = args[1], args[2]
            return "UPDATE 1"
        if "INTO agent_runs" in sql:
            self.agent_runs.append(args)
            return "INSERT 0 1"
        raise AssertionError(f"SQL inesperado: {sql[:90]}")


class FakeBus:
    INBOUND, OUTBOUND, TASKS, ALERTS = "inbound", "outbound", "tasks", "alerts"

    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, Any]]] = []
        self.counters: Counter[str] = Counter()

    async def publish(self, stream: str, event: dict[str, Any]) -> str:
        self.published.append((stream, event))
        return f"{len(self.published)}-0"

    async def rate_limit(self, key: str, limit: int, window_s: int) -> bool:
        self.counters[key] += 1
        return self.counters[key] <= limit

    def on(self, stream: str) -> list[dict[str, Any]]:
        return [e for s, e in self.published if s == stream]


class FakeGraph:
    """Graph API simulada: guarda cada chamada e devolve a resposta configurada."""

    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []
        self.status, self.body = 200, {"messages": [{"id": "wamid.OK"}]}

    def respond(self, status: int, body: dict[str, Any]) -> None:
        self.status, self.body = status, body

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        return httpx.Response(self.status, json=self.body)


def restricted_body() -> dict[str, Any]:
    return {"error": {"message": "(#130497) Business account is restricted from messaging users in this country.",
                      "type": "OAuthException", "code": 130497, "fbtrace_id": "AbCdEf123"}}


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    async def blocked(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("rede real bloqueada no teste")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", blocked)
    import aiosmtplib
    monkeypatch.setattr(aiosmtplib, "send", blocked)


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Settings só do ambiente do teste (sem .env), segredos aleatórios, Brasil pausado como no padrão."""
    for key in ("WA_BR_DELIVERY_ENABLED", "WA_BR_BLOCK_SCOPE", "SMTP_HOST", "META_IG_ACCOUNT_ID"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("WA_PHONE_NUMBER_ID", "test-phone-id")
    monkeypatch.setenv("WA_ACCESS_TOKEN", secrets.token_hex(16))
    monkeypatch.setenv("WA_APP_SECRET", secrets.token_hex(16))
    monkeypatch.setenv("META_PAGE_ID", "test-page")
    monkeypatch.setenv("META_PAGE_ACCESS_TOKEN", secrets.token_hex(16))
    monkeypatch.setenv("ALT_ROUTE_WEBCHAT_URL", "https://teste.invalid/chat")
    monkeypatch.setenv("ALT_ROUTE_EMAIL", "atendimento@teste.invalid")
    monkeypatch.setenv("ALT_ROUTE_MESSENGER_URL", "https://m.me/teste")
    monkeypatch.setenv("ALT_ROUTE_INSTAGRAM_HANDLE", "@teste")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    monkeypatch.setattr(df, "get_settings", lambda: s)
    monkeypatch.setattr(whatsapp, "get_settings", lambda: s)
    return s


@pytest.fixture
def approved_cfg(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Cópia do config/alt_route.yaml aprovada SÓ no teste (o arquivo do repositório continua approved: false)."""
    cfg = {**alt_route_config(), "approved": True, "approved_by": "teste"}
    monkeypatch.setattr(df, "alt_route_config", lambda: cfg)
    return cfg


@pytest.fixture
def fake_db(monkeypatch: pytest.MonkeyPatch) -> FakeDB:
    fdb = FakeDB()
    monkeypatch.setattr(df, "db", fdb)
    monkeypatch.setattr(whatsapp, "db", fdb)
    return fdb


@pytest.fixture
def fake_bus(monkeypatch: pytest.MonkeyPatch) -> FakeBus:
    fbus = FakeBus()
    monkeypatch.setattr(df, "bus", fbus)
    monkeypatch.setattr(whatsapp, "bus", fbus)
    return fbus


@pytest.fixture
def graph(monkeypatch: pytest.MonkeyPatch) -> FakeGraph:
    g = FakeGraph()
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(g.handler), **kw))
    return g


@pytest.fixture
def br_lead(fake_db: FakeDB) -> FakeDB:
    """Contato +55 no WhatsApp que também já escreveu pelo Messenger (mesmo telefone registrado)."""
    fake_db.add_lead("lead-wa", "whatsapp", BR, phone=f"+{BR}")
    fake_db.add_lead("lead-ms", "messenger", "psid-1", phone=f"+{BR}")
    fake_db.inbound += [("lead-wa", "Oi, quero ir a Dubai em março"), ("lead-ms", "Oi, vi o anúncio")]
    return fake_db
