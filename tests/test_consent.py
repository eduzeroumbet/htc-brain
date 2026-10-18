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

    async def pode_enviar_marketing(self, lead_id: str | None, canal: str) -> bool:
        return bool(lead_id) and self.marketing.get((lead_id, canal)) == "active"  # type: ignore[arg-type]

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
    for name in ("revogar_marketing", "pode_enviar_marketing", "abrir_dsar"):
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
