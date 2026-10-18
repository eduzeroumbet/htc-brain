"""Consentimento (consent_log), descadastro por palavra-chave e abertura de DSAR de exclusão.

- normalizar(): trim, NFC, minúsculas, sem pontuação, sem diacríticos (latinos, tashkeel árabe, matras do devanágari) e alef árabe unificado.
- detectar_descadastro(): mensagem inteira = gatilho, ou mensagem curta (≤ 3 palavras) só com gatilho + palavras de cortesia.
  Nunca por trecho: "não quero parar de viajar" não revoga.
- revogar_marketing() / pode_enviar_marketing(): o estado vigente é a linha mais recente de consent_log para (lead, canal, 'marketing').
  Sem linha = sem consentimento = marketing bloqueado. Transacional não passa por aqui.
- motivo_bloqueio(): gate do dispatch, com as regras de config/consent.yaml (RG-CONSENT-001). Com revocation_scope all_channels o
  descadastro revoga todos os canais do lead, e uma revogação em qualquer canal posterior ao opt-in do canal de envio bloqueia.
  session_reply só fica fora do gate dentro da janela aberta pela última mensagem do cliente no canal.
- detectar_dsar() / abrir_dsar(): pedido de exclusão em pt, en, ar, hi → data_requests (kind 'erasure') com prazo de 15 dias corridos.
  Só abertura, prazo e status; a execução continua em tools/legal.fulfil_data_request.
"""
from __future__ import annotations

import unicodedata
from typing import Any

import structlog

from brain.core import db
from brain.settings import consent_config

log = structlog.get_logger(__name__)

DSAR_DAYS = 15  # dias corridos (LGPD no Brasil; é também a política da agência para os demais mercados)
CONSENT_VERSION = "v1"

# valores conservadores: chave ausente ou inválida em config/consent.yaml cai aqui
_REGRAS_PADRAO: dict[str, Any] = {"revocation_scope": "all_channels", "followups_without_active_consent": "block",
                                  "transactional_window_reply": "non_marketing", "session_window_hours": 24,
                                  "unclassified_purpose": "transactional"}
_VALORES = {"revocation_scope": ("all_channels", "same_channel"), "followups_without_active_consent": ("block",),
            "transactional_window_reply": ("non_marketing", "marketing"), "unclassified_purpose": ("transactional", "marketing")}


def regras() -> dict[str, Any]:
    """config/consent.yaml validado. Valor fora do previsto → padrão conservador (e aviso no log)."""
    cfg = {**_REGRAS_PADRAO, **(consent_config() or {})}
    for chave, aceitos in _VALORES.items():
        if cfg[chave] not in aceitos:
            log.warning("consent_config_invalid", key=chave, value=str(cfg[chave]), using=_REGRAS_PADRAO[chave])
            cfg[chave] = _REGRAS_PADRAO[chave]
    try:
        cfg["session_window_hours"] = max(0, int(cfg["session_window_hours"]))
    except (TypeError, ValueError):
        cfg["session_window_hours"] = _REGRAS_PADRAO["session_window_hours"]
    return cfg

_ALEF = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ـ": None})  # variantes de alef → alef; tatweel some


def normalizar(texto: str | None) -> str:
    if not texto:
        return ""
    t = unicodedata.normalize("NFC", texto.strip()).casefold()
    t = "".join(ch for ch in unicodedata.normalize("NFD", t) if unicodedata.category(ch) != "Mn")
    t = unicodedata.normalize("NFC", t).translate(_ALEF)
    t = "".join(" " if unicodedata.category(ch)[0] in "PS" else ch for ch in t)  # pontuação e símbolos (inclui emoji)
    return " ".join(t.split())


# idioma de cada gatilho (usado na confirmação quando o idioma do lead é desconhecido)
_GATILHOS = {"parar": "pt", "sair": "pt", "stop": "en", "unsubscribe": "en", "ألغِ": "ar", "रोकें": "hi"}
GATILHOS_DESCADASTRO: dict[str, str] = {normalizar(k): v for k, v in _GATILHOS.items()}  # ألغِ/ألغ/الغ/إلغ → "الغ"; रोकें → "रोक"
# cortesia que pode acompanhar o gatilho sem mudar o sentido ("STOP please", "parar por favor", "ألغِ الاشتراك")
_CORTESIA = {normalizar(w) for w in (
    "por", "favor", "pf", "pfv", "agora", "ja", "obrigado", "obrigada", "please", "pls", "now", "me", "thanks", "thank", "you",
    "promocoes", "promotions", "marketing",  # botão "Stop promotions" que a Meta põe nos templates de marketing
    "الاشتراك", "من", "فضلك", "لو", "سمحت", "شكرا", "कृपया", "धन्यवाद",
)}


def detectar_descadastro(texto: str | None) -> str | None:
    """Devolve o idioma do gatilho se a mensagem for um descadastro; None caso contrário."""
    norm = normalizar(texto)
    if norm in GATILHOS_DESCADASTRO:
        return GATILHOS_DESCADASTRO[norm]
    tokens = norm.split()
    if not 1 < len(tokens) <= 3:
        return None
    gatilhos = [t for t in tokens if t in GATILHOS_DESCADASTRO]
    if gatilhos and all(t in GATILHOS_DESCADASTRO or t in _CORTESIA for t in tokens):
        return GATILHOS_DESCADASTRO[gatilhos[0]]
    return None


FRASES_DSAR: dict[str, tuple[str, ...]] = {
    "pt": ("excluir meus dados", "apagar meus dados", "remover meus dados", "deletar meus dados", "excluir minha conta",
           "apagar minha conta", "excluir os meus dados", "apagar os meus dados", "direito de exclusao", "esquecer meus dados"),
    "en": ("delete my data", "erase my data", "remove my data", "delete my personal data", "delete my account",
           "right to erasure", "right to be forgotten"),
    "ar": ("احذف بياناتي", "امسح بياناتي", "حذف بياناتي", "مسح بياناتي", "احذف حسابي"),
    "hi": ("मेरा डेटा हटाओ", "मेरा डेटा हटा दो", "मेरा डेटा मिटाओ", "मेरा डेटा डिलीट करो", "मेरा डेटा डिलीट कर दो"),
}
_FRASES_DSAR_NORM = [(lang, normalizar(f).split()) for lang, frases in FRASES_DSAR.items() for f in frases]


def detectar_dsar(texto: str | None) -> str | None:
    """Pedido de exclusão: alguma frase-chave aparece como sequência inteira de palavras. Devolve o idioma da frase."""
    tokens = normalizar(texto).split()
    for lang, frase in _FRASES_DSAR_NORM:
        n = len(frase)
        if any(tokens[i:i + n] == frase for i in range(len(tokens) - n + 1)):
            return lang
    return None


CONFIRMACOES = {
    "descadastro": {
        "pt": "Pronto, você não vai mais receber mensagens promocionais por aqui. Avisos sobre suas reservas, pagamentos e viagens continuam chegando normalmente.",
        "en": "Done, you will no longer receive promotional messages here. Updates about your bookings, payments and trips will still reach you as usual.",
        "ar": "تم، لن تصلك رسائل ترويجية هنا بعد الآن. ستستمر رسائل حجوزاتك ومدفوعاتك ورحلاتك بالوصول كالمعتاد.",
        "hi": "हो गया, अब आपको यहाँ प्रचार संदेश नहीं मिलेंगे। आपकी बुकिंग, भुगतान और यात्रा से जुड़ी जानकारी पहले की तरह मिलती रहेगी।",
    },
    "dsar": {
        "pt": "Recebemos seu pedido de exclusão de dados e ele foi registrado. O prazo de atendimento é de até 15 dias corridos, até {prazo}.",
        "en": "We have received and registered your data deletion request. It will be handled within 15 calendar days, by {prazo}.",
        "ar": "استلمنا طلب حذف بياناتك وتم تسجيله. ستتم معالجته خلال 15 يومًا تقويميًا، أي حتى {prazo}.",
        "hi": "आपका डेटा हटाने का अनुरोध मिल गया है और दर्ज कर लिया गया है। इसे 15 कैलेंडर दिनों के भीतर, {prazo} तक, पूरा किया जाएगा।",
    },
}


def idioma_confirmacao(idioma_lead: str | None, idioma_mensagem: str | None) -> str:
    """Idioma do lead se houver texto para ele; senão o idioma da palavra/frase usada; senão inglês."""
    for lang in ((idioma_lead or "").split("-")[0].lower(), idioma_mensagem):
        if lang in CONFIRMACOES["descadastro"]:
            return lang
    return "en"


def texto_confirmacao(tipo: str, idioma: str, **fmt: Any) -> str:
    return CONFIRMACOES[tipo][idioma].format(**fmt)


# ───────────────────────── banco ─────────────────────────

async def registrar_consentimento(lead_id: str, canal: str, *, finalidade: str = "marketing", texto: str, versao: str = CONSENT_VERSION,
                                  idioma: str | None = None, origem: str = "record_consent") -> bool:
    """Opt-in. Idempotente: se já há consentimento ativo para (lead, canal, finalidade), não cria outro. True se gravou."""
    row = await db.fetchrow(
        """INSERT INTO consent_log (lead_id, channel, consent_text, consent_version, language, source, purpose)
           VALUES ($1, $2, $3, $4, $5, $6, $7)
           ON CONFLICT (lead_id, channel, purpose) WHERE status = 'active' DO NOTHING RETURNING id""",
        lead_id, canal, texto, versao, idioma, origem, finalidade)
    if finalidade == "marketing":
        await db.execute("UPDATE leads SET consent_marketing = true, consent_at = now() WHERE id = $1", lead_id)
    return row is not None


async def revogar_marketing(lead_id: str, canal: str, *, texto: str = "", idioma: str | None = None,
                            origem: str = "whatsapp_keyword") -> bool:
    """Revoga o marketing do lead no canal e, com revocation_scope all_channels, nos demais canais. Idempotente: já revogado →
    nada muda. True se revogou alguma coisa agora.

    Sem consentimento anterior no canal, grava uma linha já revogada (prova do opt-out, e pode_enviar_marketing segue False).
    """
    escopo = regras()["revocation_scope"]
    p = await db.pool()
    async with p.acquire() as con, con.transaction():
        # dois STOP simultâneos (no mesmo canal; com all_channels, em qualquer canal do lead)
        await con.execute("SELECT pg_advisory_xact_lock(hashtext($1))",
                          f"consent:{lead_id}" if escopo == "all_channels" else f"consent:{lead_id}:{canal}")
        atual = await con.fetchrow(
            """SELECT id, status FROM consent_log WHERE lead_id = $1 AND channel = $2 AND purpose = 'marketing'
               ORDER BY recorded_at DESC, id DESC LIMIT 1""", lead_id, canal)
        revogou = False
        if not (atual and atual["status"] == "revoked"):
            if atual:
                await con.execute("UPDATE consent_log SET status = 'revoked', revoked_at = now() WHERE id = $1", atual["id"])
            else:
                await con.execute(
                    """INSERT INTO consent_log (lead_id, channel, consent_text, consent_version, language, source, purpose, status, revoked_at)
                       VALUES ($1, $2, $3, $4, $5, $6, 'marketing', 'revoked', now())""",
                    lead_id, canal, texto or "descadastro", CONSENT_VERSION, idioma, origem)
            revogou = True
        outros = 0
        if escopo == "all_channels":
            res = await con.execute(
                """UPDATE consent_log SET status = 'revoked', revoked_at = now()
                   WHERE lead_id = $1 AND channel <> $2 AND purpose = 'marketing' AND status = 'active'""", lead_id, canal)
            outros = int(res.split()[-1])
        if not (revogou or outros):
            return False
        await con.execute("UPDATE leads SET consent_marketing = false WHERE id = $1", lead_id)
    log.info("marketing_revoked", lead_id=lead_id, channel=canal, source=origem, scope=escopo, other_channels=outros)
    return True


async def motivo_bloqueio_marketing(lead_id: str | None, canal: str) -> str | None:
    """Por que marketing para (lead, canal) não pode sair; None = pode. Falha segura: sem lead ou sem consentimento ativo bloqueia."""
    if not lead_id:
        return "sem_lead"
    rows = await db.fetch(
        """SELECT channel, status, recorded_at, revoked_at FROM consent_log WHERE lead_id = $1 AND purpose = 'marketing'
           ORDER BY recorded_at DESC, id DESC""", lead_id)
    atual = next((r for r in rows if r["channel"] == canal), None)
    if atual is None:
        return "sem_registro_de_consentimento"
    if atual["status"] != "active":
        return "consentimento_revogado"
    if regras()["revocation_scope"] == "all_channels" and any(
            r["status"] == "revoked" and r["revoked_at"] > atual["recorded_at"] for r in rows):
        return "revogado_em_outro_canal"  # descadastro em outro canal depois do opt-in deste
    return None


async def pode_enviar_marketing(lead_id: str | None, canal: str) -> bool:
    """Guarda de marketing (também usada pelo follow-up antes de gerar a mensagem). Sem lead ou sem consentimento ativo → False."""
    return await motivo_bloqueio_marketing(lead_id, canal) is None


async def dentro_da_janela(lead_id: str | None, canal: str, horas: int) -> bool:
    """A última mensagem do cliente neste canal foi há menos de `horas`? (janela de atendimento aberta por ele)"""
    if not lead_id or horas <= 0:
        return False
    row = await db.fetchrow(
        """SELECT max(m.created_at) > now() - make_interval(hours => $3) AS aberta FROM messages m
           JOIN conversations c ON c.id = m.conversation_id
           WHERE c.lead_id = $1 AND c.channel = $2 AND m.direction = 'in' AND m.author = 'client'""", lead_id, canal, horas)
    return bool(row and row["aberta"])


async def motivo_bloqueio(event: dict[str, Any]) -> str | None:
    """Gate do dispatch (RG-CONSENT-001). None = pode sair; senão o motivo do bloqueio, para o registro.

    transactional → livre. session_reply → livre dentro da janela do cliente; fora dela, marketing.
    marketing, finalidade desconhecida e (se configurado) envio sem "purpose" → exige consentimento ativo e não revogado.
    """
    cfg = regras()
    finalidade = event.get("purpose") or cfg["unclassified_purpose"]
    if finalidade == "transactional":
        return None
    lead_id, canal = event.get("lead_id"), event["channel"]
    if finalidade == "session_reply" and cfg["transactional_window_reply"] == "non_marketing":
        if await dentro_da_janela(lead_id, canal, cfg["session_window_hours"]):
            return None
        motivo = await motivo_bloqueio_marketing(lead_id, canal)
        return motivo and f"fora_da_janela_{motivo}"
    return await motivo_bloqueio_marketing(lead_id, canal)


async def abrir_dsar(lead_id: str, canal: str, requester: str, texto: str, *, jurisdiction: str | None = None) -> dict[str, Any]:
    """Abre o pedido de exclusão com prazo de 15 dias corridos. Idempotente: já existe pedido aberto → devolve o mesmo (duplicado=True)."""
    row = await db.fetchrow(
        f"""INSERT INTO data_requests (lead_id, requester, kind, jurisdiction, received_at, due_at, channel, source_text)
            VALUES ($1, $2, 'erasure', $3, now(), now() + interval '{DSAR_DAYS} days', $4, $5)
            ON CONFLICT (lead_id, kind) WHERE status NOT IN ('completed', 'refused') DO NOTHING
            RETURNING id, received_at, due_at, status""",
        lead_id, requester, jurisdiction, canal, texto)
    if row:
        log.info("dsar_opened", lead_id=lead_id, channel=canal, request_id=str(row["id"]), due_at=str(row["due_at"]))
        return {**row, "duplicado": False}
    row = await db.fetchrow(
        """SELECT id, received_at, due_at, status FROM data_requests
           WHERE lead_id = $1 AND kind = 'erasure' AND status NOT IN ('completed', 'refused') ORDER BY received_at DESC LIMIT 1""", lead_id)
    assert row is not None
    return {**row, "duplicado": True}
