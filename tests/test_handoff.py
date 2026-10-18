"""Transbordo para humano sem banco: gatilhos, alerta em até 1 minuto (relógio simulado), deduplicação, SLA vencido,
falha de canal e a métrica da Camada 0 no endpoint do dashboard.

Banco, relógio e canais são dublês: nenhum e-mail ou WhatsApp real sai daqui.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest

from brain.core import consent, db, handoff
from brain.settings import Settings, handoff_config

T0 = datetime(2026, 10, 18, 9, 0, tzinfo=timezone.utc)


# ───────────────────────── dublês ─────────────────────────

class Relogio:
    def __init__(self) -> None:
        self.t = T0

    def __call__(self) -> datetime:
        return self.t

    def avancar(self, **kw: float) -> None:
        self.t += timedelta(**kw)


class Canais:
    """Substitui handoff._enviar_canal: guarda o que sairia; canal em `falhar` levanta, em `lento` estoura o timeout."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str, str]] = []
        self.falhar: set[str] = set()
        self.lento: set[str] = set()

    async def __call__(self, canal: str, destino: str, assunto: str, texto: str) -> None:
        if canal in self.lento:
            await asyncio.sleep(5)
        if canal in self.falhar:
            raise ConnectionError(f"{canal} fora do ar")
        self.sent.append((canal, destino, assunto, texto))

    def canais(self) -> list[str]:
        return [c for c, *_ in self.sent]


DEDUP = ("open", "alerted", "breached", "attended")


class FakeDB:
    """Responde só às consultas do transbordo (e às do orquestrador); SQL inesperado falha o teste."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.leads: dict[str, dict[str, Any]] = {}
        self.messages: list[dict[str, Any]] = []

    # ── helpers de domínio usados pelo orquestrador
    async def upsert_lead(self, channel: str, channel_user_id: str, **fields: Any) -> dict[str, Any]:
        lead = next((x for x in self.leads.values() if x["channel"] == channel and x["channel_user_id"] == channel_user_id), None)
        if lead is None:
            lead = {"id": str(uuid.uuid4()), "channel": channel, "channel_user_id": channel_user_id, "display_name": None,
                    "market_code": None, "language": None}
            self.leads[lead["id"]] = lead
        lead.update({k: v for k, v in fields.items() if v is not None})
        return lead

    async def open_conversation(self, lead_id: str, channel: str) -> dict[str, Any]:
        return {"id": f"00000000-0000-0000-0000-{lead_id[-12:]}", "status": "ai"}

    async def log_message(self, *a: Any, **k: Any) -> None:
        return None

    def add_event(self, **f: Any) -> dict[str, Any]:
        ev = {"id": str(uuid.uuid4()), "conversation_id": str(uuid.uuid4()), "lead_id": None, "trigger": "human_request",
              "trigger_subtype": None, "detected_by": "keyword", "language": "pt", "sla_seconds": 3600, "status": "open",
              "created_at": T0, "alerted_at": None, "attended_at": None, "attended_by": None, "breached_at": None,
              "escalated_at": None, "closed_at": None, "alert_channel": None, "alert_attempts": 0, "last_alert_at": None,
              "last_alert_error": None, "occurrence_count": 1, "last_occurrence_at": T0, "details": {}, **f}
        self.events.append(ev)
        return ev

    def _ev(self, event_id: str) -> dict[str, Any] | None:
        return next((e for e in self.events if e["id"] == event_id), None)

    async def fetchrow(self, sql: str, *a: Any) -> dict[str, Any] | None:
        s = " ".join(sql.split())
        if s.startswith("SELECT * FROM leads WHERE channel"):
            return next((x for x in self.leads.values() if x["channel"] == a[0] and x["channel_user_id"] == a[1]), None)
        if s.startswith("INSERT INTO handoff_events"):
            conv, lead, trig, sub, by, lang, sla, now, details = a
            ev = next((e for e in self.events if e["conversation_id"] == conv and e["trigger"] == trig and e["status"] in DEDUP), None)
            if ev:   # índice único parcial → ON CONFLICT DO UPDATE
                ev["occurrence_count"] += 1
                ev["last_occurrence_at"] = now
                return {"id": ev["id"], "status": ev["status"], "occurrence_count": ev["occurrence_count"], "novo": False}
            ev = self.add_event(conversation_id=conv, lead_id=lead, trigger=trig, trigger_subtype=sub, detected_by=by, language=lang,
                                sla_seconds=sla, created_at=now, last_occurrence_at=now, details=details)
            return {"id": ev["id"], "status": "open", "occurrence_count": 1, "novo": True}
        if s.startswith("UPDATE handoff_events SET alert_attempts"):
            event_id, now, limite, maximo = a
            ev = self._ev(event_id)
            escalonamento = "status = 'breached' AND escalated_at IS NULL" in s
            if not ev or (ev["last_alert_at"] is not None and ev["last_alert_at"] > limite) or ev["alert_attempts"] >= maximo:
                return None
            if escalonamento and not (ev["status"] == "breached" and ev["escalated_at"] is None):
                return None
            if not escalonamento and not (ev["status"] == "open" and ev["alerted_at"] is None):
                return None
            ev["alert_attempts"] += 1
            ev["last_alert_at"] = now
            return dict(ev)
        if s.startswith("SELECT display_name, market_code, channel FROM leads"):
            return self.leads.get(a[0])
        raise AssertionError(f"SQL inesperado: {s[:90]}")

    async def execute(self, sql: str, *a: Any) -> str:
        s = " ".join(sql.split())
        if s.startswith("UPDATE handoff_events SET last_alert_error"):
            self._ev(a[0])["last_alert_error"] = a[1]  # type: ignore[index]
            return "UPDATE 1"
        if s.startswith("UPDATE handoff_events SET escalated_at"):
            ev = self._ev(a[0])
            assert ev is not None
            ev.update(escalated_at=a[1], alert_channel=ev["alert_channel"] or a[2], last_alert_error=a[3])
            return "UPDATE 1"
        if s.startswith("UPDATE handoff_events SET alerted_at"):
            ev = self._ev(a[0])
            assert ev is not None
            ev.update(alerted_at=a[1], alert_channel=a[2], last_alert_error=a[3])
            if ev["status"] == "open":
                ev["status"] = "alerted"
            return "UPDATE 1"
        if s.startswith("UPDATE handoff_events SET status = 'attended'"):
            event_id, conv, now, por = a
            hits = [e for e in self.events if e["status"] in handoff.NA_FILA and (e["id"] == event_id or e["conversation_id"] == conv)]
            for e in hits:
                e.update(status="attended", attended_at=now, attended_by=por)
            return f"UPDATE {len(hits)}"
        if s.startswith("UPDATE handoff_events SET status = 'closed'"):
            conv, now, por = a
            hits = [e for e in self.events if e["conversation_id"] == conv and e["status"] in DEDUP]
            for e in hits:
                e.update(status="closed", closed_at=now, attended_at=e["attended_at"] or now, attended_by=e["attended_by"] or por)
            return f"UPDATE {len(hits)}"
        if s.startswith("UPDATE handoff_events h SET status = 'attended'"):
            n = 0
            for e in self.events:
                if e["status"] not in handoff.NA_FILA:
                    continue
                msgs = sorted((m for m in self.messages if m["conversation_id"] == e["conversation_id"] and m["direction"] == "out"
                               and m["author"].startswith("human:") and m["created_at"] >= e["created_at"]), key=lambda m: m["created_at"])
                if msgs:
                    e.update(status="attended", attended_at=msgs[0]["created_at"], attended_by=msgs[0]["author"])
                    n += 1
            return f"UPDATE {n}"
        raise AssertionError(f"SQL inesperado: {s[:90]}")

    async def fetch(self, sql: str, *a: Any) -> list[dict[str, Any]]:
        s = " ".join(sql.split())
        por_data = sorted(self.events, key=lambda e: e["created_at"])
        if s.startswith("SELECT id FROM handoff_events WHERE status = 'open'"):
            return [{"id": e["id"]} for e in por_data if e["status"] == "open" and e["alerted_at"] is None and e["alert_attempts"] < a[0]]
        if s.startswith("UPDATE handoff_events SET status = 'breached'"):
            now = a[0]
            out = []
            for e in self.events:
                if e["status"] in ("open", "alerted") and e["created_at"] + timedelta(seconds=e["sla_seconds"]) <= now:
                    e.update(status="breached", breached_at=now)
                    out.append({"id": e["id"]})
            return out
        if s.startswith("SELECT id FROM handoff_events WHERE status = 'breached'"):
            return [{"id": e["id"]} for e in por_data if e["status"] == "breached" and e["escalated_at"] is None and e["alert_attempts"] < a[0]]
        if "FROM handoff_events h LEFT JOIN leads" in s:
            vazio = {"display_name": None, "market_code": None, "channel": None}
            return [{**e, **{k: (self.leads.get(e["lead_id"]) or vazio).get(k) for k in vazio}} for e in por_data if e["status"] in handoff.NA_FILA]
        if s.startswith("SELECT trigger, status, created_at, attended_at, sla_seconds FROM handoff_events"):
            return [dict(e) for e in por_data if e["created_at"] >= a[0]]
        raise AssertionError(f"SQL inesperado: {s[:90]}")


# ───────────────────────── fixtures ─────────────────────────

@pytest.fixture
def relogio(monkeypatch: pytest.MonkeyPatch) -> Relogio:
    r = Relogio()
    monkeypatch.setattr(handoff, "agora", r)
    return r


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Só o ambiente do teste (sem .env); destinatários fictícios em domínio .invalid e número de teste."""
    monkeypatch.setenv("HANDOFF_ALERT_CHANNEL", "email")
    monkeypatch.setenv("HANDOFF_ALERT_EMAIL_TO", "equipe@teste.invalid")
    monkeypatch.setenv("HANDOFF_ALERT_WHATSAPP_TO", "+971500000099")
    monkeypatch.setenv("HANDOFF_ESCALATION_EMAIL_TO", "supervisao@teste.invalid")
    monkeypatch.setenv("HANDOFF_ESCALATION_WHATSAPP_TO", "")
    monkeypatch.setenv("HANDOFF_ALERT_MAX_ATTEMPTS", "5")
    monkeypatch.setenv("HANDOFF_ALERT_TIMEOUT_SECONDS", "0.2")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    monkeypatch.setattr(handoff, "get_settings", lambda: s)
    return s


@pytest.fixture
def fake_db(monkeypatch: pytest.MonkeyPatch) -> FakeDB:
    f = FakeDB()
    for name in ("fetchrow", "fetch", "execute", "upsert_lead", "open_conversation", "log_message"):
        monkeypatch.setattr(db, name, getattr(f, name))
    return f


@pytest.fixture
def canais(monkeypatch: pytest.MonkeyPatch) -> Canais:
    c = Canais()
    monkeypatch.setattr(handoff, "_enviar_canal", c)
    return c


@pytest.fixture
def ambiente(relogio: Relogio, settings: Settings, fake_db: FakeDB, canais: Canais) -> tuple[Relogio, FakeDB, Canais]:
    return relogio, fake_db, canais


def det(trigger: str, **extra: Any) -> dict[str, Any]:
    return {"trigger": trigger, "subtype": None, "detected_by": "keyword", "language": "pt", "details": {}, **extra}


CONV = "11111111-1111-1111-1111-111111111111"


# ───────────────────────── gatilhos ─────────────────────────

@pytest.mark.parametrize("msg, lang", [
    ("Quero falar com um atendente, por favor", "pt"),
    ("Posso falar com uma pessoa de verdade?", "pt"),
    ("Can I talk to a human?", "en"),
    ("I need customer service", "en"),
    ("Quiero hablar con una persona", "es"),
    ("¿Puedo hablar con un agente?", "es"),
    ("أريد التحدث مع شخص", "ar"),
    ("أحتاج خدمة العملاء", "ar"),
])
def test_pedido_de_humano_por_palavra_chave(msg: str, lang: str) -> None:
    [d] = handoff.detectar(msg, {"intent": "other"})
    assert d["trigger"] == "human_request" and d["detected_by"] == "keyword" and d["language"] == lang


def test_pedido_de_humano_pelo_modelo() -> None:
    [d] = handoff.detectar("preciso de ajuda com algo diferente", {"intent": "other", "jev_raw": {"p_human": 0.8}, "language": "pt"})
    assert d["trigger"] == "human_request" and d["detected_by"] == "model" and d["language"] == "pt"


@pytest.mark.parametrize("msg, lang", [
    ("Pode me mandar um orçamento para 4 pessoas?", "pt"),
    ("Could you send me a quote for March?", "en"),
    ("¿Me envías un presupuesto?", "es"),
    ("أريد عرض سعر لرحلة دبي", "ar"),
])
def test_proposta_com_confirmacao_do_modelo(msg: str, lang: str) -> None:
    [d] = handoff.detectar(msg, {"intent": "quote_request", "confidence": 0.55})
    assert d["trigger"] == "proposal" and d["detected_by"] == "keyword+model" and d["language"] == lang


@pytest.mark.parametrize("msg, lang", [
    ("Como faço o pagamento? Me manda o link de pagamento", "pt"),
    ("I want to pay now, send the payment link", "en"),
    ("Quiero pagar con tarjeta", "es"),
    ("أرسل لي رابط الدفع", "ar"),
])
def test_pagamento_com_confirmacao_do_modelo(msg: str, lang: str) -> None:
    [d] = handoff.detectar(msg, {"intent": "payment", "confidence": 0.5})
    assert d["trigger"] == "payment" and d["detected_by"] == "keyword+model" and d["language"] == lang


def test_pagamento_e_proposta_so_pelo_modelo_com_confianca_alta() -> None:
    [d] = handoff.detectar("tudo certo, vamos fechar", {"intent": "payment", "confidence": 0.9})
    assert d["trigger"] == "payment" and d["detected_by"] == "model"
    assert handoff.detectar("tudo certo, vamos fechar", {"intent": "payment", "confidence": 0.5}) == []


@pytest.mark.parametrize("msg, triagem", [
    ("não estou falando de pagamento", {"intent": "other", "confidence": 0.9}),       # palavra solta sem o modelo
    ("o pagamento já foi feito ontem, obrigado", {"intent": "inquiry", "confidence": 0.8}),
    ("qual o valor do orçamento que vocês mandaram?", {"intent": "inquiry", "confidence": 0.9}),
    ("quero excluir um passeio do roteiro", {"intent": "booking", "confidence": 0.9}),
    ("olá, quero um pacote para Dubai", {"intent": "greeting", "confidence": 0.9}),
    ("", {"intent": "other"}),
])
def test_falsos_positivos_nao_abrem_transbordo(msg: str, triagem: dict[str, Any]) -> None:
    assert handoff.detectar(msg, triagem) == []


@pytest.mark.parametrize("msg, lang", [
    ("Quero fazer uma reclamação", "pt"),
    ("I want to make a complaint about the driver", "en"),
    ("Quiero poner una queja", "es"),
    ("أريد تقديم شكوى", "ar"),
])
def test_reclamacao_por_palavra_chave(msg: str, lang: str) -> None:
    [d] = handoff.detectar(msg, {"intent": "other"})
    assert d["trigger"] == "complaint" and d["language"] == lang


def test_reclamacao_pelo_modelo() -> None:
    [d] = handoff.detectar("o motorista não apareceu e ninguém responde", {"intent": "complaint", "sentiment": -0.8})
    assert d["trigger"] == "complaint" and d["detected_by"] == "model"
    assert handoff.detectar("o motorista atrasou 5 min", {"intent": "complaint", "sentiment": -0.2}) == []


@pytest.mark.parametrize("msg, sub, lang", [
    ("Quero acesso aos meus dados", "access", "pt"),
    ("Please send me a copy of my data", "access", "en"),
    ("Quiero acceso a mis datos", "access", "es"),
    ("أطلب الوصول إلى بياناتي", "access", "ar"),
    ("Quero excluir meus dados", "erasure", "pt"),
    ("Delete my data please", "erasure", "en"),
    ("Por favor, eliminar mis datos", "erasure", "es"),
    ("احذف بياناتي", "erasure", "ar"),
    ("Quero revogar meu consentimento", "revocation", "pt"),
    ("I withdraw my consent", "revocation", "en"),
    ("Quiero revocar mi consentimiento", "revocation", "es"),
    ("أريد سحب الموافقة", "revocation", "ar"),
])
def test_dsar_por_palavra_chave(msg: str, sub: str, lang: str) -> None:
    [d] = handoff.detectar(msg, {"intent": "other"})
    assert (d["trigger"], d["subtype"], d["language"]) == ("dsar", sub, lang)


def test_dsar_pelo_modelo() -> None:
    [d] = handoff.detectar("não quero mais que vocês guardem nada sobre mim", {"intent": "other", "jev_raw": {"p_dsar": 0.9}})
    assert d["trigger"] == "dsar" and d["detected_by"] == "model" and d["subtype"] is None


def test_descadastro_simples_nao_e_transbordo() -> None:
    """STOP/PARAR é resolvido sozinho pelo consent_log; não acorda a equipe."""
    assert handoff.detectar("STOP", {"intent": "other"}) == []
    assert handoff.detectar("PARAR", {"intent": "other"}) == []


def test_varios_gatilhos_na_mesma_mensagem() -> None:
    found = handoff.detectar("Quero fazer uma reclamação e falar com um atendente", {"intent": "complaint", "sentiment": -0.7})
    assert [d["trigger"] for d in found] == ["human_request", "complaint"]


def test_config_tem_sla_e_aviso_para_todos_os_gatilhos() -> None:
    cfg = handoff_config()
    assert cfg["alert_within_seconds"] <= 60
    for g in handoff.GATILHOS:
        assert handoff.sla_segundos(g) > 0 and cfg["triggers"][g]["label"]
    assert set(cfg["client_notice"]) >= {"pt", "en", "es", "ar"}


def test_aviso_ao_cliente_e_neutro_e_nao_fala_de_ia() -> None:
    proibidos = ("ia", "ai", "inteligência artificial", "artificial intelligence", "inteligencia artificial", "robô", "robot", "bot",
                 "assistente virtual", "virtual assistant", "asistente virtual", "الذكاء الاصطناعي")
    textos = [*handoff_config()["client_notice"].values(), *(handoff.nota_cliente(g, lang) for g in handoff.GATILHOS
                                                             for lang in ("pt", "en", "es", "ar", None))]
    for txt in textos:
        low = f" {consent.normalizar(txt)} "
        for p in proibidos:
            assert f" {consent.normalizar(p)} " not in low, (txt, p)


# ───────────────────────── alerta em até 1 minuto ─────────────────────────

async def test_alerta_em_ate_1_minuto_pelo_fluxo_de_mensagens(ambiente, monkeypatch: pytest.MonkeyPatch) -> None:
    """Mensagem recebida → evento + alerta em segundo plano; o consultor responde mesmo assim, com o aviso neutro."""
    from brain.core import orchestrator, registry

    relogio, fake_db, canais = ambiente
    chamadas: list[dict[str, Any]] = []

    class Router:
        async def triage(self, event: dict[str, Any], lead: Any) -> dict[str, Any]:
            return {"triggers": [], "intent": "human_request", "confidence": 0.9, "language": "es", "jev_raw": {"p_human": 0.9}}

    class Consultant:
        async def handle_inbound(self, event: dict[str, Any], triage: dict[str, Any]) -> None:
            chamadas.append(event)

    monkeypatch.setattr(registry, "get", lambda name: Router() if name == "escalation_router" else Consultant())
    await orchestrator.handle_inbound({"channel": "webchat", "channel_user_id": "sess-1", "text": "Quiero hablar con una persona"})
    await asyncio.gather(*handoff._tarefas)

    [ev] = fake_db.events
    assert ev["trigger"] == "human_request" and ev["status"] == "alerted"
    assert (ev["alerted_at"] - ev["created_at"]).total_seconds() <= 60
    assert canais.sent[0][:2] == ("email", "equipe@teste.invalid")
    [evento_consultor] = chamadas
    assert any("Voy a avisar al equipo" in n for n in evento_consultor["system_notes"])


async def test_alerta_sai_pela_varredura_se_o_envio_imediato_nao_rodou(ambiente) -> None:
    relogio, fake_db, canais = ambiente
    ev = await handoff.registrar(CONV, None, det("complaint"))   # processo caiu antes do envio em segundo plano
    relogio.avancar(seconds=59)                                     # a varredura roda a cada 60 s
    out = await handoff.varrer()
    e = fake_db._ev(ev["id"])
    assert out["alerted"] == 1 and e["status"] == "alerted"
    assert (e["alerted_at"] - e["created_at"]).total_seconds() <= 60


def test_varredura_agendada_a_cada_60_segundos() -> None:
    from brain.core import scheduler

    job = scheduler.build().get_job("handoff_sweep")
    assert job is not None and job.trigger.interval <= timedelta(seconds=60)


# ───────────────────────── deduplicação ─────────────────────────

async def test_sem_duplicidade_por_conversa_e_gatilho(ambiente) -> None:
    relogio, fake_db, canais = ambiente
    a = await handoff.registrar(CONV, None, det("payment"))
    await handoff.alertar(a["id"])
    for _ in range(4):                                  # cliente insiste em sequência
        relogio.avancar(seconds=20)
        b = await handoff.registrar(CONV, None, det("payment"))
        assert b["id"] == a["id"] and b["novo"] is False
        await handoff.alertar(b["id"])                   # mesmo que alguém tente alertar de novo
    await handoff.varrer()
    [ev] = fake_db.events
    assert ev["occurrence_count"] == 5
    assert len(canais.sent) == 1

    c = await handoff.registrar(CONV, None, det("complaint"))     # outro gatilho na mesma conversa = outro evento
    assert c["novo"] is True and len(fake_db.events) == 2


async def test_envio_imediato_e_varredura_simultaneos_nao_duplicam(ambiente) -> None:
    relogio, fake_db, canais = ambiente
    ev = await handoff.registrar(CONV, None, det("human_request"))
    await asyncio.gather(handoff.alertar(ev["id"]), handoff.varrer())
    assert len(canais.sent) == 1


async def test_depois_de_fechado_um_novo_pedido_abre_outro_evento(ambiente) -> None:
    relogio, fake_db, canais = ambiente
    a = await handoff.registrar(CONV, None, det("human_request"))
    await handoff.fechar(conversation_id=CONV, por="ceo")
    b = await handoff.registrar(CONV, None, det("human_request"))
    assert b["novo"] is True and b["id"] != a["id"]


# ───────────────────────── SLA vencido ─────────────────────────

async def test_sla_estourado_escalona_uma_vez(ambiente) -> None:
    relogio, fake_db, canais = ambiente
    ev = await handoff.registrar(CONV, None, det("complaint"))     # SLA 60 min
    await handoff.alertar(ev["id"])
    relogio.avancar(minutes=59)
    assert (await handoff.varrer())["breached"] == 0

    relogio.avancar(minutes=2)
    out = await handoff.varrer()
    e = fake_db._ev(ev["id"])
    assert out["breached"] == 1 and out["escalated"] == 1
    assert e["status"] == "breached" and e["breached_at"] == relogio.t and e["escalated_at"] == relogio.t
    canal, destino, assunto, texto = canais.sent[-1]
    assert destino == "supervisao@teste.invalid" and "SLA vencido" in assunto and "61 min" in texto

    relogio.avancar(minutes=5)
    assert (await handoff.varrer())["escalated"] == 0       # não escala de novo
    assert len(canais.sent) == 2


async def test_humano_respondeu_antes_do_sla_nao_escalona(ambiente) -> None:
    relogio, fake_db, canais = ambiente
    ev = await handoff.registrar(CONV, None, det("payment"))       # SLA 120 min
    await handoff.alertar(ev["id"])
    fake_db.messages.append({"conversation_id": CONV, "direction": "out", "author": "human:mariam",
                             "created_at": relogio.t + timedelta(minutes=30)})
    relogio.avancar(minutes=125)                                    # varredura atrasada: vale a hora da mensagem
    out = await handoff.varrer()
    e = fake_db._ev(ev["id"])
    assert out == {"attended": 1, "alerted": 0, "breached": 0, "escalated": 0}
    assert e["status"] == "attended" and e["attended_by"] == "human:mariam"
    assert e["attended_at"] - e["created_at"] == timedelta(minutes=30)


async def test_mensagem_da_ia_ou_do_sistema_nao_conta_como_atendimento(ambiente) -> None:
    relogio, fake_db, canais = ambiente
    await handoff.registrar(CONV, None, det("human_request"))
    for author in ("ai:consultant", "system"):
        fake_db.messages.append({"conversation_id": CONV, "direction": "out", "author": author, "created_at": relogio.t})
    assert (await handoff.varrer())["attended"] == 0


# ───────────────────────── falha do canal ─────────────────────────

async def test_falha_do_email_usa_o_whatsapp_interno(ambiente) -> None:
    relogio, fake_db, canais = ambiente
    canais.falhar.add("email")
    ev = await handoff.registrar(CONV, None, det("payment"))
    assert await handoff.alertar(ev["id"]) is True
    e = fake_db._ev(ev["id"])
    assert canais.canais() == ["whatsapp"] and e["alert_channel"] == "whatsapp" and e["alerted_at"] == relogio.t
    assert "email: ConnectionError" in e["last_alert_error"]


async def test_falha_total_nao_derruba_e_fica_pendente_ate_o_canal_voltar(ambiente) -> None:
    relogio, fake_db, canais = ambiente
    canais.falhar |= {"email", "whatsapp"}
    ev = await handoff.registrar(CONV, None, det("complaint"))
    assert await handoff.alertar(ev["id"]) is False                # não levanta exceção
    e = fake_db._ev(ev["id"])
    assert e["alerted_at"] is None and e["status"] == "open" and "whatsapp: ConnectionError" in e["last_alert_error"]
    assert (await handoff.metricas_camada0())["alert_pending_count"] == 1

    canais.falhar.clear()
    relogio.avancar(seconds=10)
    assert (await handoff.varrer())["alerted"] == 0                # trava de 30 s entre tentativas
    relogio.avancar(seconds=25)
    assert (await handoff.varrer())["alerted"] == 1
    assert fake_db._ev(ev["id"])["status"] == "alerted"


async def test_canal_lento_estoura_timeout_e_registra(ambiente) -> None:
    relogio, fake_db, canais = ambiente
    canais.lento |= {"email", "whatsapp"}
    ev = await handoff.registrar(CONV, None, det("human_request"))
    assert await handoff.alertar(ev["id"]) is False
    assert "TimeoutError" in fake_db._ev(ev["id"])["last_alert_error"]


async def test_sem_destinatario_configurado_nao_envia_e_registra(ambiente, settings: Settings) -> None:
    relogio, fake_db, canais = ambiente
    settings.handoff_alert_email_to = ""
    settings.handoff_alert_whatsapp_to = ""
    ev = await handoff.registrar(CONV, None, det("human_request"))
    assert await handoff.alertar(ev["id"]) is False
    assert canais.sent == [] and "sem destinatário" in fake_db._ev(ev["id"])["last_alert_error"]


async def test_tentativas_tem_teto(ambiente) -> None:
    relogio, fake_db, canais = ambiente
    canais.falhar |= {"email", "whatsapp"}
    ev = await handoff.registrar(CONV, None, det("human_request"))
    for _ in range(8):
        await handoff.alertar(ev["id"])
        relogio.avancar(seconds=31)
    assert fake_db._ev(ev["id"])["alert_attempts"] == 5


async def test_falha_do_registro_nao_impede_a_resposta_ao_cliente(ambiente, monkeypatch: pytest.MonkeyPatch) -> None:
    from brain.core import orchestrator, registry

    relogio, fake_db, canais = ambiente
    chamadas: list[dict[str, Any]] = []

    class Router:
        async def triage(self, event: dict[str, Any], lead: Any) -> dict[str, Any]:
            return {"triggers": [], "intent": "complaint", "sentiment": -0.9, "language": "pt"}

    class Consultant:
        async def handle_inbound(self, event: dict[str, Any], triage: dict[str, Any]) -> None:
            chamadas.append(event)

    async def quebrado(*a: Any, **k: Any) -> Any:
        raise ConnectionError("postgres fora")

    monkeypatch.setattr(registry, "get", lambda name: Router() if name == "escalation_router" else Consultant())
    monkeypatch.setattr(handoff, "registrar", quebrado)
    await orchestrator.handle_inbound({"channel": "webchat", "channel_user_id": "sess-2", "text": "Quero fazer uma reclamação"})
    assert len(chamadas) == 1 and not chamadas[0].get("system_notes")


# ───────────────────────── Camada 0: métrica no endpoint ─────────────────────────

@pytest.fixture
async def client():
    from fastapi import FastAPI

    from brain.dashboard import api

    app = FastAPI()
    app.include_router(api.router, prefix="/api")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://painel.test") as c:
        yield c


async def test_metrica_camada0_no_endpoint(ambiente, client: httpx.AsyncClient) -> None:
    relogio, fake_db, canais = ambiente
    relogio.avancar(days=4)
    t = relogio.t
    lead = await fake_db.upsert_lead("whatsapp", "971500000001", display_name="Cliente Teste", market_code="SA")
    fake_db.add_event(trigger="complaint", sla_seconds=3600, status="attended", created_at=t - timedelta(minutes=50),
                      attended_at=t - timedelta(minutes=30))                                   # 20 min ≤ 60: dentro
    fake_db.add_event(trigger="payment", sla_seconds=7200, status="attended", created_at=t - timedelta(hours=5),
                      attended_at=t - timedelta(hours=1))                                      # 4 h > 2 h: fora
    vencido = fake_db.add_event(trigger="human_request", sla_seconds=14400, status="breached", created_at=t - timedelta(hours=5),
                                alerted_at=t - timedelta(hours=5), lead_id=lead["id"])        # na fila, 5 h > 4 h: fora
    aberto = fake_db.add_event(trigger="proposal", sla_seconds=1800, status="open", created_at=t - timedelta(minutes=10))
    fake_db.add_event(trigger="dsar", sla_seconds=1296000, status="closed", created_at=t - timedelta(days=3),
                      attended_at=t - timedelta(days=2))                                       # só entra nos 7 dias
    fake_db.add_event(trigger="complaint", sla_seconds=3600, status="closed", created_at=t - timedelta(days=9),
                      attended_at=t - timedelta(days=8))                                       # fora da janela

    r = await client.get("/api/dashboard/layer0")
    assert r.status_code == 200
    m = r.json()
    assert m["open_queue_count"] == 2
    assert m["oldest_wait_seconds"] == 5 * 3600
    assert m["avg_wait_seconds"] == (5 * 3600 + 600) // 2
    assert m["avg_wait_attended_seconds_24h"] == (20 * 60 + 4 * 3600) // 2
    assert m["sla_within_pct_24h"] == 33.3          # 1 dentro de 3 (atendido fora + vencido na fila)
    assert m["sla_within_pct_7d"] == 50.0           # + DSAR dentro
    assert m["breached_open_count"] == 1 and m["alert_pending_count"] == 1
    assert m["by_trigger"] == {"human_request": 1, "proposal": 1, "payment": 0, "complaint": 0, "dsar": 0}
    first, second = m["queue"]
    assert first["id"] == vencido["id"] and first["display_name"] == "Cliente Teste" and first["sla_left_seconds"] < 0
    assert second["id"] == aberto["id"] and second["alert_pending"] is True

    r = await client.post(f"/api/handoffs/{aberto['id']}/attend")
    assert r.status_code == 200 and r.json()["status"] == "attended"
    assert fake_db._ev(aberto["id"])["attended_at"] == t and fake_db._ev(aberto["id"])["attended_by"] == "painel"
    assert (await client.get("/api/dashboard/layer0")).json()["open_queue_count"] == 1

    assert (await client.post(f"/api/handoffs/{aberto['id']}/attend")).status_code == 404   # já atendido
    assert (await client.post("/api/handoffs/nao-e-uuid/attend")).status_code == 404


async def test_camada0_vazia(ambiente, client: httpx.AsyncClient) -> None:
    m = (await client.get("/api/dashboard/layer0")).json()
    assert m["open_queue_count"] == 0 and m["oldest_wait_seconds"] == 0 and m["sla_within_pct_24h"] is None and m["queue"] == []
