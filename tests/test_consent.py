"""Descadastro, guarda de marketing e DSAR sem banco: regras de texto + fluxo do orquestrador e do dispatch com dublês."""
from __future__ import annotations

import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from brain.core import consent

# ───────────────────────── normalizar ─────────────────────────


@pytest.mark.parametrize("entrada, esperado", [
    ("  STOP!!!  ", "stop"),
    ("Parar.", "parar"),
    ("SAIR 🙏", "sair"),
    ("Não quero", "nao quero"),
    ("ألغِ", "الغ"),
    ("أَلْغِ", "الغ"),
    ("إلغ", "الغ"),
    ("रोकें", "रोक"),
    ("", ""),
    (None, ""),
])
def test_normalizar(entrada: str | None, esperado: str) -> None:
    assert consent.normalizar(entrada) == esperado


def test_normalizar_nfc_e_nfd_dao_o_mesmo() -> None:
    texto = "não quero mais promoções"
    assert consent.normalizar(unicodedata.normalize("NFD", texto)) == consent.normalizar(unicodedata.normalize("NFC", texto))


# ───────────────────────── detectar_descadastro ─────────────────────────


@pytest.mark.parametrize("msg, idioma", [
    ("PARAR", "pt"), ("parar", "pt"), ("STOP", "en"), ("Stop", "en"), ("stop.", "en"), ("  STOP!!!  ", "en"),
    ("SAIR", "pt"), ("sair", "pt"), ("UNSUBSCRIBE", "en"), ("unsubscribe", "en"),
    ("ألغِ", "ar"), ("ألغ", "ar"), ("الغ", "ar"), ("إلغ", "ar"),
    ("रोकें", "hi"),
    ("parar por favor", "pt"), ("STOP please", "en"), ("Stop promotions", "en"), ("ألغِ الاشتراك", "ar"), ("PARAR agora", "pt"),
])
def test_gatilhos_revogam(msg: str, idioma: str) -> None:
    assert consent.detectar_descadastro(msg) == idioma


@pytest.mark.parametrize("msg", [
    "não quero parar de viajar",
    "quero parar de viajar",
    "parar de viajar",
    "posso sair amanhã?",
    "vamos sair às 9h",
    "Bus stop near the hotel?",
    "don't stop",
    "stopover in Dubai",
    "sairemos cedo",
    "unsubscribed",
    "olá, quero um pacote para Dubai",
    "",
])
def test_frases_comuns_nao_revogam(msg: str) -> None:
    assert consent.detectar_descadastro(msg) is None


# ───────────────────────── detectar_dsar ─────────────────────────


@pytest.mark.parametrize("msg, idioma", [
    ("Quero excluir meus dados", "pt"),
    ("por favor APAGAR MEUS DADOS!", "pt"),
    ("Please delete my data", "en"),
    ("I want to exercise my right to erasure.", "en"),
    ("احذف بياناتي", "ar"),
    ("أرجو حذف بياناتي", "ar"),
    ("मेरा डेटा हटाओ", "hi"),
    ("कृपया मेरा डेटा हटा दो", "hi"),
])
def test_dsar_reconhecido(msg: str, idioma: str) -> None:
    assert consent.detectar_dsar(msg) == idioma


@pytest.mark.parametrize("msg", ["meus dados de voo estão certos?", "delete the old booking", "STOP", "quero excluir um passeio"])
def test_dsar_nao_reconhecido(msg: str) -> None:
    assert consent.detectar_dsar(msg) is None


# ───────────────────────── confirmação ─────────────────────────


@pytest.mark.parametrize("lead, msg, esperado", [
    ("pt", "en", "pt"),        # "STOP" de um lead brasileiro → português
    ("pt-BR", None, "pt"),
    (None, "ar", "ar"),
    ("ru", "en", "en"),        # sem texto em russo: idioma da palavra usada
    (None, None, "en"),
    ("hi", "en", "hi"),
])
def test_idioma_confirmacao(lead: str | None, msg: str | None, esperado: str) -> None:
    assert consent.idioma_confirmacao(lead, msg) == esperado


def test_confirmacoes_existem_em_todos_os_idiomas_e_nao_falam_de_ia() -> None:
    for tipo, textos in consent.CONFIRMACOES.items():
        assert set(textos) == {"pt", "en", "ar", "hi"}, tipo
        for lang, txt in textos.items():
            low = txt.lower()
            for proibido in (" ia ", " ai ", "inteligência artificial", "artificial intelligence", "robô", "bot", "assistente virtual",
                             "الذكاء الاصطناعي", "एआई"):
                assert proibido not in f" {low} ", (tipo, lang, proibido)
    assert "15" in consent.texto_confirmacao("dsar", "pt", prazo="02/11/2026")
    assert "02/11/2026" in consent.texto_confirmacao("dsar", "ar", prazo="02/11/2026")


# ───────────────────────── fluxo: orquestrador ─────────────────────────


class FakeStore:
    """Dublê do consent/db/bus usados pelo orquestrador e pelo dispatch."""

    def __init__(self) -> None:
        self.leads: dict[tuple[str, str], dict[str, Any]] = {}
        self.marketing: dict[tuple[str, str], str] = {}   # (lead, canal) → active|revoked
        self.consent_rows = 0
        self.dsar: dict[str, dict[str, Any]] = {}
        self.messages: list[tuple[str, str, str]] = []
        self.outbound: list[dict[str, Any]] = []
        self.sent: list[dict[str, Any]] = []
        self.consultant_calls = 0

    # db
    async def upsert_lead(self, channel: str, channel_user_id: str, **fields: Any) -> dict[str, Any]:
        lead = self.leads.setdefault((channel, channel_user_id), {"id": f"lead-{len(self.leads) + 1}", "channel": channel, "language": None,
                                                                  "market_code": None})
        lead.update({k: v for k, v in fields.items() if v is not None})
        return lead

    async def fetchrow(self, sql: str, channel: str, cuid: str) -> dict[str, Any] | None:
        return self.leads.get((channel, cuid))

    async def open_conversation(self, lead_id: str, channel: str) -> dict[str, Any]:
        return {"id": f"conv-{lead_id}"}

    async def log_message(self, conversation_id: str, direction: str, author: str, body: str, **extra: Any) -> None:
        self.messages.append((direction, author, body))

    # consent
    async def revogar_marketing(self, lead_id: str, canal: str, **kw: Any) -> bool:
        if self.marketing.get((lead_id, canal)) == "revoked":
            return False
        if (lead_id, canal) not in self.marketing:
            self.consent_rows += 1
        self.marketing[(lead_id, canal)] = "revoked"
        return True

    async def motivo_bloqueio_marketing(self, lead_id: str | None, canal: str) -> str | None:
        if not lead_id:
            return "sem_lead"
        return {None: "sem_registro_de_consentimento", "revoked": "consentimento_revogado"}.get(self.marketing.get((lead_id, canal)))

    async def dentro_da_janela(self, lead_id: str | None, canal: str, horas: int) -> bool:
        return False

    async def abrir_dsar(self, lead_id: str, canal: str, requester: str, texto: str, **kw: Any) -> dict[str, Any]:
        if lead_id in self.dsar:
            return {**self.dsar[lead_id], "duplicado": True}
        agora = datetime.now(timezone.utc)
        self.dsar[lead_id] = {"id": f"dsar-{lead_id}", "received_at": agora, "due_at": agora + timedelta(days=15), "status": "open"}
        return {**self.dsar[lead_id], "duplicado": False}

    # bus
    async def publish(self, stream: str, event: dict[str, Any]) -> str:
        self.outbound.append(event)
        return "1-0"


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> FakeStore:
    from brain import channels
    from brain.core import orchestrator, registry

    s = FakeStore()
    for name in ("upsert_lead", "fetchrow", "open_conversation", "log_message"):
        monkeypatch.setattr(orchestrator.db, name, getattr(s, name))
    for name in ("revogar_marketing", "motivo_bloqueio_marketing", "dentro_da_janela", "abrir_dsar"):
        monkeypatch.setattr(consent, name, getattr(s, name))
    monkeypatch.setattr(orchestrator.bus, "publish", s.publish)

    class Router:
        async def triage(self, event: dict[str, Any], lead: Any) -> dict[str, Any]:
            return {"triggers": [], "intent": "other"}

    class Consultant:
        async def handle_inbound(self, event: dict[str, Any], triage: dict[str, Any]) -> None:
            s.consultant_calls += 1

    monkeypatch.setattr(registry, "get", lambda name: Router() if name == "escalation_router" else Consultant())

    async def fake_send(event: dict[str, Any]) -> None:
        s.sent.append(event)

    monkeypatch.setitem(channels.SENDERS, "whatsapp", fake_send)
    return s


def _wa(text: str, user: str = "971585153946") -> dict[str, Any]:
    return {"channel": "whatsapp", "channel_user_id": user, "text": text, "message_id": "wamid.1", "phone": f"+{user}"}


async def test_stop_revoga_responde_e_nao_chama_o_consultor(store: FakeStore) -> None:
    from brain.core import orchestrator

    store.leads[("whatsapp", "5511999")] = {"id": "L1", "channel": "whatsapp", "language": "pt", "market_code": "BR"}
    store.marketing[("L1", "whatsapp")] = "active"
    await orchestrator.handle_inbound(_wa("STOP", "5511999"))
    assert store.marketing[("L1", "whatsapp")] == "revoked"
    assert store.consultant_calls == 0
    [out] = store.outbound
    assert out["purpose"] == "transactional" and out["lead_id"] == "L1"
    assert out["text"] == consent.CONFIRMACOES["descadastro"]["pt"]  # idioma do lead, não o da palavra
    assert [m[0] for m in store.messages] == ["in", "out"]


async def test_descadastro_duas_vezes_nao_duplica(store: FakeStore) -> None:
    from brain.core import orchestrator

    await orchestrator.handle_inbound(_wa("PARAR"))
    await orchestrator.handle_inbound(_wa("parar!"))
    assert store.consent_rows == 1
    assert len(store.leads) == 1
    assert store.marketing == {("lead-1", "whatsapp"): "revoked"}


async def test_primeira_mensagem_descadastro_cria_lead_e_responde_no_idioma_da_palavra(store: FakeStore) -> None:
    from brain.core import orchestrator

    await orchestrator.handle_inbound(_wa("ألغِ", "971500000001"))
    assert ("whatsapp", "971500000001") in store.leads
    assert store.outbound[0]["text"] == consent.CONFIRMACOES["descadastro"]["ar"]


async def test_frase_com_parar_segue_para_o_consultor(store: FakeStore) -> None:
    from brain.core import orchestrator

    await orchestrator.handle_inbound(_wa("não quero parar de viajar"))
    assert store.consultant_calls == 1
    assert store.marketing == {} and store.outbound == []


async def test_outros_canais_nao_passam_pelo_gancho(store: FakeStore) -> None:
    from brain.core import orchestrator

    await orchestrator.handle_inbound({**_wa("STOP"), "channel": "instagram"})
    assert store.consultant_calls == 1 and store.marketing == {}


async def test_pedido_de_exclusao_abre_dsar_com_15_dias(store: FakeStore) -> None:
    from brain.core import orchestrator

    store.leads[("whatsapp", "919800000000")] = {"id": "L9", "channel": "whatsapp", "language": "hi", "market_code": "IN"}
    await orchestrator.handle_inbound(_wa("कृपया मेरा डेटा हटा दो", "919800000000"))
    d = store.dsar["L9"]
    assert d["due_at"] - d["received_at"] == timedelta(days=15) and d["status"] == "open"
    assert store.consultant_calls == 0
    assert store.outbound[0]["purpose"] == "transactional"
    assert f"{d['due_at']:%d/%m/%Y}" in store.outbound[0]["text"]
    await orchestrator.handle_inbound(_wa("मेरा डेटा हटाओ", "919800000000"))
    assert len(store.dsar) == 1  # idempotente
    assert store.outbound[1]["text"] == store.outbound[0]["text"]  # mesmo prazo


# ───────────────────────── fluxo: guarda única no dispatch ─────────────────────────


async def test_dispatch_bloqueia_marketing_apos_revogacao(store: FakeStore) -> None:
    from brain.channels import dispatch
    from brain.core import orchestrator

    store.leads[("whatsapp", "5511999")] = {"id": "L1", "channel": "whatsapp", "language": "pt", "market_code": "BR"}
    store.marketing[("L1", "whatsapp")] = "active"
    mk = {"channel": "whatsapp", "channel_user_id": "5511999", "text": "Oferta Dubai", "lead_id": "L1", "purpose": "marketing"}
    await dispatch(mk)
    assert len(store.sent) == 1  # com consentimento ativo, sai

    await orchestrator.handle_inbound(_wa("STOP", "5511999"))
    store.sent.clear()
    await dispatch(mk)                                                              # follow-up / campanha
    await dispatch({**mk, "template": {"name": "promo_dubai", "language": {"code": "pt_BR"}}})  # template de marketing
    assert store.sent == []

    await dispatch({"channel": "whatsapp", "channel_user_id": "5511999", "text": "Seu voucher", "lead_id": "L1"})  # transacional
    await dispatch({"channel": "whatsapp", "channel_user_id": "5511999", "text": "Pagamento recebido", "lead_id": "L1", "purpose": "transactional"})
    assert [e["text"] for e in store.sent] == ["Seu voucher", "Pagamento recebido"]


async def test_dispatch_marketing_sem_lead_ou_sem_consentimento_e_bloqueado(store: FakeStore) -> None:
    from brain.channels import dispatch

    await dispatch({"channel": "whatsapp", "channel_user_id": "1", "text": "promo", "purpose": "marketing"})
    await dispatch({"channel": "whatsapp", "channel_user_id": "1", "text": "promo", "purpose": "marketing", "lead_id": "nunca-consentiu"})
    assert store.sent == []


async def test_followup_marca_marketing_e_respeita_a_guarda(store: FakeStore, monkeypatch: pytest.MonkeyPatch) -> None:
    from brain.agents import consultant as consultant_mod

    lead = {"id": "L1", "stage": "quoted", "consent_marketing": True, "channel": "whatsapp", "channel_user_id": "5511999", "market_code": "BR"}

    async def fetchrow(sql: str, *a: Any) -> dict[str, Any]:
        return lead

    async def rate_limit(*a: Any, **k: Any) -> bool:
        return True

    class Result:
        status, text, cost_usd = "ok", "Que tal um jantar no deserto?", 0.0

    async def run(*a: Any, **k: Any) -> Result:
        return Result()

    monkeypatch.setattr(consultant_mod.db, "fetchrow", fetchrow)
    monkeypatch.setattr(consultant_mod.db, "open_conversation", store.open_conversation)
    monkeypatch.setattr(consultant_mod.db, "log_message", store.log_message)
    monkeypatch.setattr(consultant_mod.bus, "rate_limit", rate_limit)
    monkeypatch.setattr(consultant_mod.bus, "publish", store.publish)
    agent = consultant_mod.ConsultantAgent.__new__(consultant_mod.ConsultantAgent)
    monkeypatch.setattr(agent, "run", run, raising=False)

    store.marketing[("L1", "whatsapp")] = "active"
    await agent.followup("L1", "D+3")
    assert store.outbound[-1]["purpose"] == "marketing"

    store.outbound.clear()
    store.marketing[("L1", "whatsapp")] = "revoked"
    await agent.followup("L1", "D+7")
    assert store.outbound == []  # nem chega a gerar a mensagem

    store.marketing.clear()  # leads.consent_marketing = true, mas nenhuma linha no consent_log
    await agent.followup("L1", "D+1")
    assert store.outbound == []


# ───────────────────────── RG-CONSENT-001: escopo da revogação e follow-ups (config/consent.yaml) ─────────────────────────
# Gate real (motivo_bloqueio, revogar_marketing) sobre um consent_log em memória. Casos T1–T12 da decisão da etapa 3.

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


class FakeConsentLog:
    """consent_log, janela de atendimento e conexão do banco em memória; entende só as consultas de brain/core/consent.py."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.janela: set[tuple[str, str]] = set()   # (lead, canal) com mensagem do cliente dentro da janela
        self.agora = T0
        self.locks: list[str] = []
        self.sent: list[dict[str, Any]] = []

    def add(self, lead: str, canal: str, dia: int = 0, revogado_dia: int | None = None) -> None:
        self.rows.append({"id": len(self.rows) + 1, "lead_id": lead, "channel": canal, "recorded_at": T0 + timedelta(days=dia),
                          "status": "active" if revogado_dia is None else "revoked",
                          "revoked_at": None if revogado_dia is None else T0 + timedelta(days=revogado_dia)})

    def _do_lead(self, lead: str) -> list[dict[str, Any]]:
        return sorted((r for r in self.rows if r["lead_id"] == lead), key=lambda r: (r["recorded_at"], r["id"]), reverse=True)

    def estado(self, lead: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for r in self._do_lead(lead):
            out.setdefault(r["channel"], r["status"])  # linha mais recente de cada canal
        return out

    # brain.core.db
    async def fetch(self, sql: str, lead: str) -> list[dict[str, Any]]:
        assert "FROM consent_log" in sql and "purpose = 'marketing'" in sql
        return [dict(r) for r in self._do_lead(lead)]

    async def fetchrow(self, sql: str, lead: str, canal: str, *a: Any) -> dict[str, Any] | None:
        if "FROM messages" in sql:
            return {"aberta": (lead, canal) in self.janela}
        return next((dict(r) for r in self._do_lead(lead) if r["channel"] == canal), None)  # linha vigente do canal

    async def execute(self, sql: str, *a: Any) -> str:
        if "pg_advisory_xact_lock" in sql:
            self.locks.append(a[0])
            return "SELECT 1"
        if sql.startswith("UPDATE leads"):
            return "UPDATE 1"
        if sql.lstrip().startswith("INSERT INTO consent_log"):
            self.rows.append({"id": len(self.rows) + 1, "lead_id": a[0], "channel": a[1], "recorded_at": self.agora,
                              "status": "revoked", "revoked_at": self.agora})
            return "INSERT 0 1"
        if "channel <> $2" in sql:  # all_channels: demais canais ativos do lead
            alvo = [r for r in self.rows if r["lead_id"] == a[0] and r["channel"] != a[1] and r["status"] == "active"]
        else:
            alvo = [r for r in self.rows if r["id"] == a[0]]
        for r in alvo:
            r.update(status="revoked", revoked_at=self.agora)
        return f"UPDATE {len(alvo)}"

    def transaction(self) -> "FakeConsentLog":
        return self

    def acquire(self) -> "FakeConsentLog":
        return self

    async def __aenter__(self) -> "FakeConsentLog":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def pool(self) -> "FakeConsentLog":
        return self


@pytest.fixture
def clog(monkeypatch: pytest.MonkeyPatch) -> FakeConsentLog:
    from brain import channels

    f = FakeConsentLog()
    for name in ("fetch", "fetchrow", "execute", "pool"):
        monkeypatch.setattr(consent.db, name, getattr(f, name))

    async def fake_send(event: dict[str, Any]) -> None:
        f.sent.append(event)

    for canal in ("whatsapp", "email", "messenger", "instagram"):
        monkeypatch.setitem(channels.SENDERS, canal, fake_send)
    return f


def _cfg(monkeypatch: pytest.MonkeyPatch, **over: Any) -> None:
    from brain.settings import consent_config

    base = dict(consent_config())
    monkeypatch.setattr(consent, "consent_config", lambda: {**base, **over})


def _mk(lead: str | None, canal: str = "whatsapp", **extra: Any) -> dict[str, Any]:
    ev = {"channel": canal, "channel_user_id": "u1", "text": "Oferta Dubai", "lead_id": lead, "purpose": "marketing", **extra}
    return {k: v for k, v in ev.items() if v is not None}


def test_config_consent_yaml_tem_as_decisoes_conservadoras() -> None:
    from brain.settings import consent_config

    cfg = consent_config()
    assert cfg["revocation_scope"] == "all_channels"
    assert cfg["followups_without_active_consent"] == "block"
    assert cfg["transactional_window_reply"] == "non_marketing" and cfg["session_window_hours"] == 24
    assert cfg["unclassified_purpose"] == "transactional"
    assert consent.regras() == cfg


def test_config_invalida_cai_no_padrao_conservador(monkeypatch: pytest.MonkeyPatch) -> None:
    _cfg(monkeypatch, revocation_scope="por_canal", followups_without_active_consent="allow", session_window_hours="x",
         unclassified_purpose="talvez")
    r = consent.regras()
    assert r["revocation_scope"] == "all_channels"
    assert r["followups_without_active_consent"] == "block"
    assert r["session_window_hours"] == 24
    assert r["unclassified_purpose"] == "transactional"


async def test_t1_lead_sem_registro_bloqueia_e_registra_sem_dados_pessoais(clog: FakeConsentLog) -> None:
    from structlog.testing import capture_logs

    from brain.channels import dispatch

    with capture_logs() as logs:
        await dispatch({**_mk("L1"), "channel_user_id": "971585153946", "phone": "+971585153946"})
    assert clog.sent == []
    [rec] = [e for e in logs if e["event"] == "marketing_blocked"]
    assert rec["reason"] == "sem_registro_de_consentimento" and rec["lead_id"] == "L1" and rec["channel"] == "whatsapp"
    assert not {"channel_user_id", "phone", "text", "email"} & set(rec)
    assert "971585153946" not in str(rec)


async def test_marketing_sem_lead_bloqueia(clog: FakeConsentLog) -> None:
    assert await consent.motivo_bloqueio(_mk(None)) == "sem_lead"


async def test_t2_consentimento_ativo_no_canal_sai(clog: FakeConsentLog) -> None:
    from brain.channels import dispatch

    clog.add("L2", "whatsapp")
    await dispatch(_mk("L2"))
    assert len(clog.sent) == 1


async def test_t3_consentimento_so_no_whatsapp_nao_vale_no_messenger(clog: FakeConsentLog) -> None:
    clog.add("L3", "whatsapp")
    assert await consent.motivo_bloqueio(_mk("L3", "messenger")) == "sem_registro_de_consentimento"


async def test_t4_stop_no_whatsapp_revoga_todos_os_canais(clog: FakeConsentLog) -> None:
    clog.add("L4", "whatsapp")
    clog.add("L4", "email")
    clog.add("L5", "email")  # outro lead não é afetado
    clog.agora = T0 + timedelta(days=5)
    assert await consent.revogar_marketing("L4", "whatsapp", texto="STOP") is True
    assert clog.estado("L4") == {"whatsapp": "revoked", "email": "revoked"}
    assert clog.estado("L5") == {"email": "active"}
    assert clog.locks == ["consent:L4"]  # trava por lead: STOP simultâneo em dois canais não corre
    assert await consent.revogar_marketing("L4", "whatsapp", texto="STOP") is False  # idempotente
    assert await consent.revogar_marketing("L4", "email", texto="STOP") is False


async def test_t4b_stop_sem_registro_no_canal_grava_prova_e_revoga_os_outros(clog: FakeConsentLog) -> None:
    clog.add("L4", "email")
    clog.agora = T0 + timedelta(days=5)
    assert await consent.revogar_marketing("L4", "whatsapp", texto="PARAR") is True
    assert clog.estado("L4") == {"email": "revoked", "whatsapp": "revoked"}


async def test_t5_t6_apos_descadastro_marketing_bloqueado_no_canal_e_em_outro(clog: FakeConsentLog) -> None:
    from brain.channels import dispatch

    clog.add("L4", "whatsapp")
    clog.add("L4", "email")
    clog.agora = T0 + timedelta(days=5)
    await consent.revogar_marketing("L4", "whatsapp", texto="STOP")
    await dispatch(_mk("L4", "whatsapp"))                                 # T5
    await dispatch(_mk("L4", "email", template={"name": "promo_dubai"}))  # T6
    assert clog.sent == []
    assert await consent.motivo_bloqueio(_mk("L4", "email")) == "consentimento_revogado"


async def test_t6b_revogacao_em_outro_canal_bloqueia_mesmo_com_linha_ativa(clog: FakeConsentLog) -> None:
    clog.add("L4", "email", dia=0)                      # opt-in no e-mail
    clog.add("L4", "whatsapp", dia=1, revogado_dia=5)   # STOP no WhatsApp depois do opt-in do e-mail (linha antiga, carga, corrida)
    assert await consent.motivo_bloqueio(_mk("L4", "email")) == "revogado_em_outro_canal"
    clog.rows[0].update(status="revoked", revoked_at=T0 + timedelta(days=5))
    clog.add("L4", "email", dia=6)                      # novo opt-in explícito no e-mail, depois do STOP
    assert await consent.motivo_bloqueio(_mk("L4", "email")) is None
    assert await consent.motivo_bloqueio(_mk("L4", "whatsapp")) == "consentimento_revogado"  # o WhatsApp segue revogado


async def test_same_channel_revoga_so_o_canal(clog: FakeConsentLog, monkeypatch: pytest.MonkeyPatch) -> None:
    _cfg(monkeypatch, revocation_scope="same_channel")
    clog.add("L4", "whatsapp")
    clog.add("L4", "email")
    clog.agora = T0 + timedelta(days=5)
    assert await consent.revogar_marketing("L4", "whatsapp", texto="STOP") is True
    assert clog.estado("L4") == {"whatsapp": "revoked", "email": "active"}
    assert clog.locks == ["consent:L4:whatsapp"]
    assert await consent.motivo_bloqueio(_mk("L4", "email")) is None
    assert await consent.motivo_bloqueio(_mk("L4", "whatsapp")) == "consentimento_revogado"


async def test_t7_transacional_sai_mesmo_apos_descadastro(clog: FakeConsentLog) -> None:
    from brain.channels import dispatch

    clog.add("L4", "whatsapp", revogado_dia=5)
    await dispatch(_mk("L4", purpose="transactional", text="Sua proposta solicitada"))
    assert [e["text"] for e in clog.sent] == ["Sua proposta solicitada"]


async def test_t8_resposta_dentro_da_janela_sai_sem_consentimento(clog: FakeConsentLog) -> None:
    from brain.channels import dispatch

    clog.janela.add(("L5", "whatsapp"))
    await dispatch(_mk("L5", purpose="session_reply", text="Claro, seguem as opções"))
    assert len(clog.sent) == 1


async def test_resposta_fora_da_janela_vira_marketing(clog: FakeConsentLog) -> None:
    assert await consent.motivo_bloqueio(_mk("L5", purpose="session_reply")) == "fora_da_janela_sem_registro_de_consentimento"
    clog.add("L5", "whatsapp")
    assert await consent.motivo_bloqueio(_mk("L5", purpose="session_reply")) is None  # fora da janela, mas com opt-in ativo


async def test_janela_aberta_nao_libera_marketing(clog: FakeConsentLog) -> None:
    clog.janela.add(("L5", "whatsapp"))
    assert await consent.motivo_bloqueio(_mk("L5")) == "sem_registro_de_consentimento"


@pytest.mark.skip(reason="T9 pendente: consent_log não tem expires_at e o esquema não muda nesta entrega; prazo de expiração "
                         "vai ao advogado (dossiê 7606d709)")
async def test_t9_consentimento_expirado_bloqueia() -> None:
    raise AssertionError


async def test_t10_sem_purpose_segue_a_config(clog: FakeConsentLog, monkeypatch: pytest.MonkeyPatch) -> None:
    sem_purpose = {"channel": "whatsapp", "channel_user_id": "u1", "text": "Oi", "lead_id": "L7"}
    assert await consent.motivo_bloqueio(sem_purpose) is None  # padrão atual: transacional
    _cfg(monkeypatch, unclassified_purpose="marketing")
    assert await consent.motivo_bloqueio(sem_purpose) == "sem_registro_de_consentimento"


async def test_finalidade_desconhecida_e_tratada_como_marketing(clog: FakeConsentLog) -> None:
    assert await consent.motivo_bloqueio(_mk("L7", purpose="promo")) == "sem_registro_de_consentimento"


async def test_t11_followup_fora_da_janela_com_consentimento_ativo_sai(clog: FakeConsentLog) -> None:
    from brain.channels import dispatch

    clog.add("L8", "whatsapp")
    await dispatch(_mk("L8", template={"name": "followup_d3"}, template_required=True))
    assert len(clog.sent) == 1


async def test_t12_descadastrado_reabre_contato_resposta_sai_followup_nao(clog: FakeConsentLog) -> None:
    from brain.channels import dispatch

    clog.add("L9", "whatsapp")
    clog.agora = T0 + timedelta(days=2)
    await consent.revogar_marketing("L9", "whatsapp", texto="STOP")
    clog.janela.add(("L9", "whatsapp"))  # cliente volta pedindo orçamento
    await dispatch(_mk("L9", purpose="session_reply", text="Segue o orçamento"))
    await dispatch(_mk("L9", text="Que tal um jantar no deserto?"))  # follow-up promocional sem novo opt-in
    assert [e["text"] for e in clog.sent] == ["Segue o orçamento"]
