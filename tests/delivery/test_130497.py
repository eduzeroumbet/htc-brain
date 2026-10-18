"""Erro 130497 da Meta: falha permanente, sem retentativa, registro com código e mercado, rota alternativa uma única vez.

Tudo simulado (Graph, banco, Redis). Nenhuma mensagem real sai daqui.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import pytest

from brain.channels import delivery_failures as df
from brain.channels import dispatch, whatsapp
from brain.settings import ROOT, Settings, alt_route_config
from tests.delivery.conftest import AE, BR, GB, IN, restricted_body

OPT_OUT = ["PARAR", "STOP", "SAIR", "UNSUBSCRIBE", "ألغِ", "रोकें"]


def wa_event(to: str = BR, text: str = "Olá! Segue o roteiro.", **extra: Any) -> dict[str, Any]:
    return {"channel": "whatsapp", "channel_user_id": to, "text": text, **extra}


def status_payload(wamid: str = "wamid.FAIL1", to: str = BR, code: Any = 130497) -> dict[str, Any]:
    return {"object": "whatsapp_business_account", "entry": [{"id": "waba", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp", "metadata": {"phone_number_id": "test-phone-id"},
        "statuses": [{"id": wamid, "status": "failed", "timestamp": "1760000000", "recipient_id": to,
                      "errors": [{"code": code, "title": "Restricted", "error_data": {"details": "detalhe"}}]}]}}]}]}


def message_payload(to: str = BR) -> dict[str, Any]:
    return {"object": "whatsapp_business_account", "entry": [{"id": "waba", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp", "contacts": [{"wa_id": to}],
        "messages": [{"from": to, "id": "wamid.MSG1", "type": "unsupported", "errors": [{"code": "130497"}]}]}}]}]}


def value_payload() -> dict[str, Any]:
    return {"object": "whatsapp_business_account", "entry": [{"id": "waba", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp", "errors": [{"code": 130497, "title": "Restricted"}]}}]}]}


@pytest.fixture
def br_enabled(settings: Settings) -> Settings:
    """Flag ligada SÓ neste objeto de teste (nada persiste), para exercitar o caminho síncrono da Graph."""
    settings.wa_br_delivery_enabled = True
    return settings


# 1 ─ critério de pronto: sem retentativa
async def test_sync_130497_not_retried(br_enabled, approved_cfg, br_lead, fake_bus, graph):
    graph.respond(400, restricted_body())
    await dispatch(wa_event(lead_id="lead-wa"))

    assert len(graph.calls) == 1
    assert not [e for e in fake_bus.on("outbound") if e["channel"] == "whatsapp"]
    assert fake_bus.on("delivery") == [] and fake_bus.on("tasks") == []
    [ev] = br_lead.events
    assert ev["delivery_status"] == "failed_permanent" and ev["retryable"] is False and ev["source"] == "sync"
    assert ev["fbtrace_id"] == "AbCdEf123"


# 2 ─ mesmo tratamento pelo webhook, nos caminhos com destinatário
@pytest.mark.parametrize("payload", [status_payload(), message_payload()], ids=["statuses", "messages"])
async def test_webhook_failed_130497_not_retried(settings, approved_cfg, br_lead, fake_bus, graph, payload):
    n = await whatsapp.handle_webhook(payload)

    assert n == 0 and graph.calls == []
    assert fake_bus.on("inbound") == []
    [ev] = br_lead.events
    assert (ev["error_code"], ev["source"], ev["market_code"]) == (130497, "webhook", "BR")
    assert ev["wamid"] in ("wamid.FAIL1", "wamid.MSG1")


async def test_webhook_value_errors_without_recipient(settings, approved_cfg, fake_db, fake_bus, graph):
    await whatsapp.handle_webhook(value_payload())

    [ev] = fake_db.events
    assert (ev["market_code"], ev["country_prefix"], ev["lead_id"]) == ("unknown", None, None)
    assert ev["alt_route_status"] == "not_applicable_market"
    assert fake_bus.on("outbound") == [] and len(fake_bus.on("alerts")) == 1


def test_extract_error_codes_all_paths():
    assert df.extract_error_codes(restricted_body()) == [130497]
    assert df.extract_error_codes(status_payload()) == [130497]
    assert df.extract_error_codes(message_payload()) == [130497]
    assert df.extract_error_codes(value_payload()) == [130497]
    assert df.extract_error_codes({"error": {"code": "abc"}}) == []
    assert df.extract_error_codes(None) == []


# 3 ─ critério de pronto: registro com código e mercado, sem dado pessoal
async def test_event_has_code_and_market(br_enabled, approved_cfg, br_lead, fake_bus, graph, capsys):
    graph.respond(400, restricted_body())
    await dispatch(wa_event(lead_id="lead-wa"))

    [ev] = br_lead.events
    assert ev["error_code"] == 130497
    assert ev["category"] == "wa_country_restricted"
    assert (ev["market_code"], ev["country_prefix"]) == ("BR", "+55")
    assert ev["retryable"] is False and ev["lead_id"] == "lead-wa"
    assert all(BR not in str(v) for v in ev.values())
    out = capsys.readouterr()
    assert BR not in out.out + out.err
    assert all(BR not in a["text"] for a in fake_bus.on("alerts"))


# 4 ─ critério de pronto: rota alternativa disparada, uma vez, por outro canal
async def test_alt_route_dispatched(br_enabled, approved_cfg, br_lead, fake_bus, graph):
    graph.respond(400, restricted_body())
    await dispatch(wa_event(lead_id="lead-wa"))

    [msg] = fake_bus.on("outbound")
    assert msg["channel"] == "messenger" and msg["channel_user_id"] == "psid-1"
    assert msg["kind"] == "alt_route_notice" and msg["lead_id"] == "lead-ms"
    for link in ("https://teste.invalid/chat", "atendimento@teste.invalid", "https://m.me/teste", "@teste"):
        assert link in msg["text"]
    assert "{" not in msg["text"] and "}" not in msg["text"]
    assert br_lead.events[0]["alt_route_status"] == "dispatched"
    assert br_lead.events[0]["alt_route_channel"] == "messenger"


def test_alt_route_only_configured_channels(settings, approved_cfg):
    settings.alt_route_webchat_url = settings.alt_route_email = ""
    text = df.render_alt_route_text(approved_cfg)
    assert "Messenger" in text and "Instagram" in text
    assert "Chat no site" not in text and "E-mail" not in text


# 5 ─ persona: a Huda não se apresenta como IA
def test_alt_route_text_persona(settings, approved_cfg):
    text = df.render_alt_route_text(approved_cfg).casefold()
    assert "huda" in text
    for banned in (r"\bia\b", r"\bai\b", "inteligência artificial", "assistente virtual", r"\brob[ôo]\b", r"\bbot\b", "chatbot"):
        assert not re.search(banned, text), banned


# 6 ─ idempotência
async def test_idempotent(br_enabled, approved_cfg, br_lead, fake_bus, graph):
    await whatsapp.handle_webhook(status_payload())
    await whatsapp.handle_webhook(status_payload())          # a Meta reenviou o mesmo webhook
    assert len(br_lead.events) == 1
    assert len(fake_bus.on("outbound")) == 1

    graph.respond(400, restricted_body())                     # outro envio ao mesmo lead dentro de 24 h
    await dispatch(wa_event(text="Outra mensagem", lead_id="lead-wa"))
    assert len(br_lead.events) == 2
    assert br_lead.events[1]["alt_route_status"] == "skipped_recent"
    assert len(fake_bus.on("outbound")) == 1


# 7 ─ descadastro e consentimento
@pytest.mark.parametrize("term", OPT_OUT)
async def test_optout_blocks_alt_route(br_enabled, approved_cfg, br_lead, fake_bus, graph, term):
    br_lead.inbound.append(("lead-wa", term))
    graph.respond(400, restricted_body())
    await dispatch(wa_event(lead_id="lead-wa"))

    assert fake_bus.on("outbound") == []
    assert br_lead.events[0]["alt_route_status"] == "skipped_opted_out"


@pytest.mark.parametrize("dsar, expected", [
    ({"kind": "access", "status": "open"}, "skipped_dsar"),
    ({"kind": "consent_withdrawal", "status": "completed"}, "skipped_opted_out"),
])
async def test_dsar_or_withdrawal_blocks_alt_route(br_enabled, approved_cfg, br_lead, fake_bus, graph, dsar, expected):
    br_lead.dsar.append({"lead_id": "lead-ms", **dsar})
    graph.respond(400, restricted_body())
    await dispatch(wa_event(lead_id="lead-wa"))

    assert fake_bus.on("outbound") == []
    assert br_lead.events[0]["alt_route_status"] == expected


def test_opt_out_matcher():
    assert df.is_opt_out("parar") and df.is_opt_out("STOP please") and df.is_opt_out("ألغ") and df.is_opt_out("Sair!")
    assert not df.is_opt_out("Quero sair do hotel cedo no dia do passeio de barco")
    assert not df.is_opt_out("") and not df.is_opt_out(None)


# 8 ─ texto sem aprovação ou sem canais
async def test_text_not_approved(br_enabled, br_lead, fake_bus, graph):
    assert alt_route_config()["approved"] is False   # arquivo real do repositório
    graph.respond(400, restricted_body())
    await dispatch(wa_event(lead_id="lead-wa"))

    assert fake_bus.on("outbound") == []
    assert br_lead.events[0]["alt_route_status"] == "skipped_text_not_approved"
    assert len(fake_bus.on("alerts")) == 1


async def test_no_channels_configured(br_enabled, approved_cfg, br_lead, fake_bus, graph):
    for attr in ("alt_route_webchat_url", "alt_route_email", "alt_route_messenger_url", "alt_route_instagram_handle"):
        setattr(br_enabled, attr, "")
    graph.respond(400, restricted_body())
    await dispatch(wa_event(lead_id="lead-wa"))

    assert fake_bus.on("outbound") == []
    assert br_lead.events[0]["alt_route_status"] == "skipped_no_channels"
    assert len(fake_bus.on("alerts")) == 1


# 9 ─ lead só no WhatsApp: nunca tenta de novo pelo WhatsApp
async def test_unreachable_no_whatsapp_loop(br_enabled, approved_cfg, fake_db, fake_bus, graph):
    fake_db.add_lead("lead-wa", "whatsapp", BR, phone=f"+{BR}")
    fake_db.inbound.append(("lead-wa", "Oi"))
    graph.respond(400, restricted_body())
    await dispatch(wa_event(lead_id="lead-wa"))

    assert len(graph.calls) == 1
    assert fake_bus.on("outbound") == []
    assert fake_db.events[0]["alt_route_status"] == "unreachable"
    assert len(fake_bus.on("alerts")) == 1


async def test_ceo_alert_130497_does_not_loop(br_enabled, approved_cfg, fake_db, fake_bus, graph):
    graph.respond(400, restricted_body())
    await whatsapp.send({"channel_user_id": BR, "text": "alerta", "kind": "ceo_alert"})

    assert len(graph.calls) == 1 and len(fake_db.events) == 1
    assert fake_bus.on("alerts") == [] and fake_bus.on("outbound") == []


# 10 ─ mercado pelo prefixo
def test_market_mapping():
    assert df.market_from_phone("+5511900000001") == ("BR", "+55")
    assert df.market_from_phone(AE) == ("AE", "+971")
    assert df.market_from_phone(IN) == ("IN", "+91")
    assert df.market_from_phone(GB) == ("GB", "+44")
    assert df.market_from_phone("+12125550100") == ("ambiguous", "+1")
    assert df.market_from_phone("011900000001") == ("unknown", None)
    assert df.market_from_phone("") == ("unknown", None)


async def test_130497_other_market_no_alt_route(settings, approved_cfg, fake_db, fake_bus, graph):
    fake_db.add_lead("lead-in", "whatsapp", IN, phone=f"+{IN}")
    graph.respond(400, restricted_body())
    await dispatch(wa_event(to=IN, lead_id="lead-in"))

    [ev] = fake_db.events
    assert (ev["market_code"], ev["country_prefix"], ev["error_code"]) == ("IN", "+91", 130497)
    assert ev["alt_route_status"] == "not_applicable_market"
    assert fake_bus.on("outbound") == [] and len(fake_bus.on("alerts")) == 1


# 11 ─ dashboard: contador próprio
async def test_dashboard_separate_counter(settings, approved_cfg, br_lead, fake_bus, graph):
    await dispatch(wa_event(text="pausado", lead_id="lead-wa"))           # guarda do Brasil
    graph.respond(400, restricted_body())
    await dispatch(wa_event(to=IN, text="restrito"))                       # 130497 real
    graph.respond(400, {"error": {"code": 131047, "message": "Re-engagement message"}})
    await dispatch(wa_event(to=AE, text="janela fechada"))                 # outra falha

    out = await df.dashboard_counts(30)
    assert out["totals"] == {"wa_country_restricted": 1, "wa_br_paused_by_flag": 1}
    assert {(r["market_code"], r["category"]) for r in out["daily"]} == {("BR", "wa_br_paused_by_flag"), ("IN", "wa_country_restricted")}
    assert len(br_lead.agent_runs) == 1   # o 131047 segue no registro antigo, fora da categoria do 130497


# 12 ─ Brasil pausado por flag
async def test_br_guard_flag_off(settings, approved_cfg, br_lead, fake_bus, graph):
    assert settings.wa_br_delivery_enabled is False
    await dispatch(wa_event(lead_id="lead-wa"))

    assert graph.calls == []
    [ev] = br_lead.events
    assert (ev["category"], ev["source"], ev["error_code"], ev["market_code"]) == ("wa_br_paused_by_flag", "guard", None, "BR")
    assert ev["alt_route_status"] == "dispatched"
    assert [m["channel"] for m in fake_bus.on("outbound")] == ["messenger"]


async def test_br_guard_flag_on(br_enabled, approved_cfg, br_lead, fake_bus, graph):
    await dispatch(wa_event(lead_id="lead-wa"))
    assert len(graph.calls) == 1 and br_lead.events == []


@pytest.mark.parametrize("to", [AE, IN, GB])
async def test_br_guard_other_markets(settings, fake_db, fake_bus, graph, to):
    await dispatch(wa_event(to=to))
    assert len(graph.calls) == 1 and fake_db.events == []


async def test_br_guard_proactive_only(settings, approved_cfg, br_lead, fake_bus, graph):
    settings.wa_br_block_scope = "proactive_only"
    await dispatch(wa_event(lead_id="lead-wa"))                                  # resposta livre passa
    assert len(graph.calls) == 1
    await dispatch(wa_event(text="follow-up", lead_id="lead-wa", template_required=True))
    assert len(graph.calls) == 1 and br_lead.events[0]["category"] == "wa_br_paused_by_flag"


async def test_br_guard_only_whatsapp(settings, fake_db, fake_bus, graph, monkeypatch):
    sent: list[dict[str, Any]] = []

    async def fake_messenger(event: dict[str, Any]) -> None:
        sent.append(event)

    from brain import channels
    monkeypatch.setitem(channels.SENDERS, "messenger", fake_messenger)
    await dispatch({"channel": "messenger", "channel_user_id": "psid-1", "text": "oi", "phone": f"+{BR}"})
    assert len(sent) == 1 and fake_db.events == []


# 13 ─ flag desligada por padrão e nunca ligada pelo código
def test_flag_default_false_and_never_set(monkeypatch):
    monkeypatch.delenv("WA_BR_DELIVERY_ENABLED", raising=False)
    assert Settings(_env_file=None).wa_br_delivery_enabled is False  # type: ignore[call-arg]
    assert re.search(r"^WA_BR_DELIVERY_ENABLED=false$", (ROOT / ".env.example").read_text(), re.M)
    cfg = alt_route_config()
    assert cfg["approved"] is False and cfg["approved_by"] is None

    turn_on = re.compile(r"wa_br_delivery_enabled\s*=\s*True|WA_BR_DELIVERY_ENABLED\s*[=:]\s*[\"']?(true|1|yes|on)\b", re.I)
    files = [p for d in ("brain", "db", "config", "scripts") for p in (ROOT / d).rglob("*") if p.suffix in (".py", ".sql", ".yaml", ".yml", ".sh")]
    files += [ROOT / ".env.example", ROOT / "docker-compose.yml", ROOT / "docker-compose.override.yml"]   # nunca o .env
    hits = [str(p.relative_to(ROOT)) for p in files if p.is_file() and turn_on.search(p.read_text(errors="ignore"))]
    assert hits == []


# 14 ─ outros erros mantêm o comportamento atual
@pytest.mark.parametrize("status, body, runs", [
    (400, {"error": {"code": 131047, "message": "Re-engagement message"}}, 1),
    (500, {"error": {"code": 1, "message": "Unknown error"}}, 0),
    (502, {}, 0),
])
async def test_other_errors_unchanged(settings, fake_db, fake_bus, graph, status, body, runs):
    graph.respond(status, body)
    await dispatch(wa_event(to=AE))

    assert len(graph.calls) == 1
    assert fake_db.events == [] and len(fake_db.agent_runs) == runs
    assert fake_bus.on("outbound") == [] and fake_bus.on("alerts") == []


async def test_other_webhook_failures_unchanged(settings, fake_db, fake_bus, graph):
    await whatsapp.handle_webhook(status_payload(to=AE, code=131026))
    assert fake_db.events == []
    assert len(fake_bus.on("alerts")) == 1   # alerta antigo de falha genérica continua


# 15 ─ migração aplica e reverte (precisa de Postgres descartável com pgvector: TEST_DATABASE_URL)
@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="defina TEST_DATABASE_URL (banco descartável) para rodar")
async def test_migration_up_down():
    import asyncpg

    con = await asyncpg.connect(os.environ["TEST_DATABASE_URL"])
    try:
        for f in sorted((ROOT / "db" / "migrations").glob("*.sql")):
            await con.execute(f.read_text())
        assert await con.fetchval("SELECT to_regclass('delivery_failure_events') IS NOT NULL")
        await con.execute("""INSERT INTO delivery_failure_events (error_code, category, market_code, country_prefix, source, outbound_ref)
                             VALUES (130497, 'wa_country_restricted', 'BR', '+55', 'sync', 'r1')""")
        with pytest.raises(asyncpg.UniqueViolationError):
            await con.execute("""INSERT INTO delivery_failure_events (error_code, category, market_code, source, outbound_ref)
                                 VALUES (130497, 'wa_country_restricted', 'BR', 'webhook', 'r1')""")
        with pytest.raises(asyncpg.CheckViolationError):
            await con.execute("""INSERT INTO delivery_failure_events (category, market_code, source, outbound_ref, retryable)
                                 VALUES ('wa_country_restricted', 'BR', 'sync', 'r2', true)""")
        down = re.search(r"^--\s+(DROP TABLE IF EXISTS delivery_failure_events;)", Path(ROOT / "db/migrations/012_delivery_failures.sql").read_text(), re.M)
        await con.execute(down.group(1))
        assert await con.fetchval("SELECT to_regclass('delivery_failure_events') IS NULL")
        await con.execute((ROOT / "db" / "migrations" / "012_delivery_failures.sql").read_text())
        assert await con.fetchval("SELECT to_regclass('delivery_failure_events') IS NOT NULL")
    finally:
        await con.close()
