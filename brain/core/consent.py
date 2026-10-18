"""Consentimento (consent_log), descadastro por palavra-chave e abertura de DSAR de exclusão.

- normalizar(): trim, NFKC, minúsculas, sem pontuação/emoji, sem diacríticos (latinos, tashkeel árabe, matras do devanágari),
  alef árabe unificado, dígitos árabes/devanágari → 0-9 e 3+ letras repetidas → 1.
- detectar_descadastro(): os seis termos originais. Mensagem inteira = gatilho, ou mensagem curta (≤ 3 palavras) só com gatilho +
  palavras de cortesia. Nunca por trecho: "não quero parar de viajar" não revoga. O que fica fora deles: brain/core/descadastro.py.
- revogar_marketing() / pode_enviar_marketing(): o estado vigente é a linha mais recente de consent_log para (lead, canal, 'marketing'),
  ignorando as suspensões já retomadas ('lifted'). Sem linha = sem consentimento = marketing bloqueado. Transacional não passa por aqui.
- motivo_bloqueio(): gate do dispatch, com as regras de config/consent.yaml (RG-CONSENT-001). Com revocation_scope all_channels o
  descadastro revoga todos os canais do lead, e uma revogação em qualquer canal posterior ao opt-in do canal de envio bloqueia.
  session_reply só fica fora do gate dentro da janela aberta pela última mensagem do cliente no canal.
- suspender_marketing() / retomar_marketing() / abrir_revisao_humana(): pedido ambíguo ou claro fora da lista → linha 'suspended'
  (bloqueia marketing pela mesma guarda) até "sim" (revoga), "não" (retoma) ou decisão humana. Silêncio: vencer_confirmacoes().
- detectar_dsar() / abrir_dsar(): pedido de exclusão em pt, en, ar, hi → data_requests (kind 'erasure') com prazo de 15 dias corridos.
  Só abertura, prazo e status; a execução continua em tools/legal.fulfil_data_request.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

import structlog

from brain.core import db
from brain.settings import consent_config, descadastro_config, escalation_config

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


_REPETIDAS = re.compile(r"([^\W\d_])\1{2,}")  # "stooop" → "stop"; "stoop" (2) fica


def normalizar(texto: str | None) -> str:
    if not texto:
        return ""
    t = unicodedata.normalize("NFKC", texto.strip()).casefold()  # NFKC: largura total, ligaduras e formas de apresentação árabes
    t = "".join(ch for ch in unicodedata.normalize("NFD", t) if unicodedata.category(ch) not in ("Mn", "Cf"))  # Cf: ZWJ, RLM
    t = unicodedata.normalize("NFC", t).translate(_ALEF)
    t = "".join(str(unicodedata.decimal(ch)) if ch.isdecimal() and not ch.isascii() else ch for ch in t)  # ٣ ۳ ३ → 3
    t = "".join(" " if unicodedata.category(ch)[0] in "PS" else ch for ch in t)  # pontuação e símbolos (inclui emoji)
    return " ".join(_REPETIDAS.sub(r"\1", t).split())


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
    # textos em ar, hi e ru: revisão por falante nativo antes de produção (config/descadastro.yaml → revisao_nativa_pendente)
    "descadastro": {
        "pt": "Pronto, você não vai mais receber mensagens promocionais por aqui. Avisos sobre suas reservas, pagamentos e viagens continuam chegando normalmente.",
        "en": "Done, you will no longer receive promotional messages here. Updates about your bookings, payments and trips will still reach you as usual.",
        "ar": "تم، لن تصلك رسائل ترويجية هنا بعد الآن. ستستمر رسائل حجوزاتك ومدفوعاتك ورحلاتك بالوصول كالمعتاد.",
        "hi": "हो गया, अब आपको यहाँ प्रचार संदेश नहीं मिलेंगे। आपकी बुकिंग, भुगतान और यात्रा से जुड़ी जानकारी पहले की तरह मिलती रहेगी।",
        "ru": "Готово, вы больше не будете получать здесь рекламные сообщения. Информация о ваших бронированиях, оплатах и поездках будет приходить как обычно.",
        "de": "Erledigt, Sie erhalten hier keine Werbenachrichten mehr. Informationen zu Ihren Buchungen, Zahlungen und Reisen bekommen Sie weiterhin wie gewohnt.",
    },
    # pergunta única do caso ambíguo (marketing já suspenso enquanto espera)
    "pergunta": {
        "pt": "Só para confirmar: você quer parar de receber mensagens promocionais por aqui? Responda SIM ou NÃO. Avisos sobre suas reservas e viagens continuam normalmente.",
        "en": "Just to confirm: would you like to stop receiving promotional messages here? Please reply YES or NO. Updates about your bookings and trips will continue as usual.",
        "ar": "للتأكيد فقط: هل تريد إيقاف الرسائل الترويجية هنا؟ يرجى الرد بـ نعم أو لا. ستستمر رسائل حجوزاتك ورحلاتك كالمعتاد.",
        "hi": "बस पुष्टि के लिए: क्या आप यहाँ प्रचार संदेश पाना बंद करना चाहते हैं? कृपया हाँ या नहीं में जवाब दें। आपकी बुकिंग और यात्रा से जुड़ी जानकारी पहले की तरह मिलती रहेगी।",
        "ru": "Уточним: вы хотите отказаться от рекламных сообщений здесь? Пожалуйста, ответьте ДА или НЕТ. Информация о ваших бронированиях и поездках будет приходить как обычно.",
        "de": "Nur zur Bestätigung: Möchten Sie hier keine Werbenachrichten mehr erhalten? Bitte antworten Sie mit JA oder NEIN. Informationen zu Ihren Buchungen und Reisen erhalten Sie weiterhin wie gewohnt.",
    },
    # pedido claro fora da lista: marketing suspenso, a equipe confirma
    "pausa": {
        "pt": "Entendido. Pausamos as mensagens promocionais para você, e nossa equipe vai confirmar o seu pedido. Avisos sobre suas reservas, pagamentos e viagens continuam normalmente.",
        "en": "Understood. We have paused promotional messages for you, and our team will confirm your request. Updates about your bookings, payments and trips will continue as usual.",
        "ar": "تم الفهم. أوقفنا الرسائل الترويجية لك مؤقتًا، وسيؤكد فريقنا طلبك. ستستمر رسائل حجوزاتك ومدفوعاتك ورحلاتك كالمعتاد.",
        "hi": "समझ गए। हमने आपके लिए प्रचार संदेश रोक दिए हैं और हमारी टीम आपके अनुरोध की पुष्टि करेगी। आपकी बुकिंग, भुगतान और यात्रा से जुड़ी जानकारी पहले की तरह मिलती रहेगी।",
        "ru": "Понятно. Мы приостановили для вас рекламные сообщения, и наша команда подтвердит ваш запрос. Информация о ваших бронированиях, оплатах и поездках будет приходить как обычно.",
        "de": "Verstanden. Wir haben Werbenachrichten für Sie pausiert, und unser Team bestätigt Ihre Anfrage. Informationen zu Ihren Buchungen, Zahlungen und Reisen erhalten Sie weiterhin wie gewohnt.",
    },
    # resposta "não" à pergunta: nada muda
    "mantido": {
        "pt": "Combinado, mantivemos tudo como estava.",
        "en": "All right, we have kept everything as it was.",
        "ar": "حسنًا، أبقينا كل شيء كما كان.",
        "hi": "ठीक है, हमने सब कुछ पहले जैसा ही रखा है।",
        "ru": "Хорошо, мы оставили всё как было.",
        "de": "Alles klar, wir haben alles so gelassen, wie es war.",
    },
    "dsar": {
        "pt": "Recebemos seu pedido de exclusão de dados e ele foi registrado. O prazo de atendimento é de até 15 dias corridos, até {prazo}.",
        "en": "We have received and registered your data deletion request. It will be handled within 15 calendar days, by {prazo}.",
        "ar": "استلمنا طلب حذف بياناتك وتم تسجيله. ستتم معالجته خلال 15 يومًا تقويميًا، أي حتى {prazo}.",
        "hi": "आपका डेटा हटाने का अनुरोध मिल गया है और दर्ज कर लिया गया है। इसे 15 कैलेंडर दिनों के भीतर, {prazo} तक, पूरा किया जाएगा।",
    },
}


def idioma_confirmacao(idioma_lead: str | None, idioma_mensagem: str | None, tipo: str = "descadastro") -> str:
    """Idioma do lead se houver texto para ele; senão o idioma da palavra/frase usada; senão inglês."""
    for lang in ((idioma_lead or "").split("-")[0].lower(), idioma_mensagem):
        if lang in CONFIRMACOES[tipo]:
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


# estado vigente: linha mais recente, sem contar suspensões já retomadas ('lifted' é só histórico)
_SQL_ATUAL = """SELECT id, status, detection_class, awaiting_until, escalation_id, language, consent_text,
                       coalesce(awaiting_until > now(), false) AS aguardando FROM consent_log
                WHERE lead_id = $1 AND channel = $2 AND purpose = 'marketing' AND status <> 'lifted'
                ORDER BY recorded_at DESC, id DESC LIMIT 1"""


async def _travar(con: Any, lead_id: str, canal: str) -> None:
    # dois STOP simultâneos (no mesmo canal; com all_channels, em qualquer canal do lead)
    chave = f"consent:{lead_id}" if regras()["revocation_scope"] == "all_channels" else f"consent:{lead_id}:{canal}"
    await con.execute("SELECT pg_advisory_xact_lock(hashtext($1))", chave)


async def revogar_marketing(lead_id: str, canal: str, *, texto: str = "", idioma: str | None = None,
                            origem: str = "whatsapp_keyword", classe: str | None = None, resposta: str | None = None) -> bool:
    """Revoga o marketing do lead no canal e, com revocation_scope all_channels, nos demais canais. Idempotente: já revogado →
    nada muda. True se revogou alguma coisa agora.

    Sem consentimento anterior no canal, grava uma linha já revogada (prova do opt-out, e pode_enviar_marketing segue False).
    Com suspensão aberta, revoga a suspensão e o consentimento ativo por baixo dela (senão um novo opt-in bateria no índice único).
    classe: lista | ambiguo | claro (consent_log.detection_class); resposta: o "sim" que confirmou a pergunta, quando houver.
    """
    escopo = regras()["revocation_scope"]
    p = await db.pool()
    async with p.acquire() as con, con.transaction():
        await _travar(con, lead_id, canal)
        atual = await con.fetchrow(_SQL_ATUAL, lead_id, canal)
        revogou = False
        if not (atual and atual["status"] == "revoked"):
            if atual:
                await con.execute(
                    """UPDATE consent_log SET status = 'revoked', revoked_at = now(), detection_class = coalesce(detection_class, $3),
                              reply_text = coalesce($4, reply_text)
                       WHERE lead_id = $1 AND channel = $2 AND purpose = 'marketing' AND status IN ('active', 'suspended')""",
                    lead_id, canal, classe, resposta)
            else:
                await con.execute(
                    """INSERT INTO consent_log (lead_id, channel, consent_text, consent_version, language, source, purpose, status, revoked_at,
                                                detection_class)
                       VALUES ($1, $2, $3, $4, $5, $6, 'marketing', 'revoked', now(), $7)""",
                    lead_id, canal, texto or "descadastro", CONSENT_VERSION, idioma, origem, classe)
            revogou = True
        outros = 0
        if escopo == "all_channels":
            res = await con.execute(
                """UPDATE consent_log SET status = 'revoked', revoked_at = now()
                   WHERE lead_id = $1 AND channel <> $2 AND purpose = 'marketing' AND status IN ('active', 'suspended')""",
                lead_id, canal)
            outros = int(res.split()[-1])
        if not (revogou or outros):
            return False
        await con.execute("UPDATE leads SET consent_marketing = false WHERE id = $1", lead_id)
    log.info("marketing_revoked", lead_id=lead_id, channel=canal, source=origem, scope=escopo, other_channels=outros,
             detection_class=classe)
    return True


async def motivo_bloqueio_marketing(lead_id: str | None, canal: str) -> str | None:
    """Por que marketing para (lead, canal) não pode sair; None = pode. Falha segura: sem lead, sem consentimento ativo ou com
    suspensão aberta (pedido ambíguo/fora da lista) bloqueia. Suspensões já retomadas ('lifted') não contam."""
    if not lead_id:
        return "sem_lead"
    rows = await db.fetch(
        """SELECT channel, status, recorded_at, revoked_at FROM consent_log
           WHERE lead_id = $1 AND purpose = 'marketing' AND status <> 'lifted'
           ORDER BY recorded_at DESC, id DESC""", lead_id)
    atual = next((r for r in rows if r["channel"] == canal), None)
    if atual is None:
        return "sem_registro_de_consentimento"
    if atual["status"] == "suspended":
        return "marketing_suspenso"
    if atual["status"] != "active":
        return "consentimento_revogado"
    if regras()["revocation_scope"] == "all_channels" and any(
            r["status"] == "revoked" and r["revoked_at"] > atual["recorded_at"] for r in rows):
        return "revogado_em_outro_canal"  # descadastro em outro canal depois do opt-in deste
    return None


async def pode_enviar_marketing(lead_id: str | None, canal: str) -> bool:
    """Guarda de marketing (também usada pelo follow-up antes de gerar a mensagem). Falha segura: sem lead, sem consentimento ativo
    ou com suspensão aberta (pedido ambíguo/fora da lista) → False."""
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


def prazo_confirmacao_dias() -> int:
    return int(descadastro_config().get("prazo_confirmacao_dias", 7))


async def suspender_marketing(lead_id: str, canal: str, *, texto: str, idioma: str | None, classe: str,
                              origem: str = "whatsapp_fora_da_lista") -> dict[str, Any]:
    """Suspende o marketing sem revogar: grava uma linha 'suspended' em consent_log com a origem e a classe (ambiguo | claro).

    Idempotente: com suspensão já aberta devolve a mesma ({"nova": False}); já revogado devolve {"status": "revoked"}.
    Caso ambíguo: awaiting_until = agora + prazo; nesse intervalo um "sim" revoga e um "não" retoma.
    """
    p = await db.pool()
    async with p.acquire() as con, con.transaction():
        await _travar(con, lead_id, canal)
        atual = await con.fetchrow(_SQL_ATUAL, lead_id, canal)
        if atual and atual["status"] in ("revoked", "suspended"):
            return {**atual, "nova": False}
        row = await con.fetchrow(
            f"""INSERT INTO consent_log (lead_id, channel, consent_text, consent_version, language, source, purpose, status,
                                         detection_class, awaiting_until)
                VALUES ($1, $2, $3, $4, $5, $6, 'marketing', 'suspended', $7,
                        CASE WHEN $7 = 'ambiguo' THEN now() + interval '{prazo_confirmacao_dias()} days' END)
                RETURNING id, status, detection_class, awaiting_until, escalation_id, language, consent_text,
                          awaiting_until IS NOT NULL AS aguardando""",
            lead_id, canal, texto or "descadastro", CONSENT_VERSION, idioma, origem, classe)
    log.info("marketing_suspended", lead_id=lead_id, channel=canal, source=origem, detection_class=classe)
    return {**row, "nova": True}  # type: ignore[dict-item]


async def confirmacao_pendente(lead_id: str, canal: str) -> dict[str, Any] | None:
    """Suspensão ambígua ainda dentro do prazo da pergunta (é nela que "sim"/"não" valem)."""
    row = await db.fetchrow(_SQL_ATUAL, lead_id, canal)
    return row if row and row["status"] == "suspended" and row["aguardando"] else None


async def retomar_marketing(lead_id: str, canal: str, *, resposta: str = "") -> bool:
    """Encerra a suspensão sem revogar ("não" do cliente ou decisão humana). O estado volta a ser o de antes:
    consentimento ativo → marketing volta; sem consentimento → continua bloqueado. True se havia suspensão aberta."""
    status = await db.execute(
        """UPDATE consent_log SET status = 'lifted', lifted_at = now(), reply_text = $3
           WHERE lead_id = $1 AND channel = $2 AND purpose = 'marketing' AND status = 'suspended'""", lead_id, canal, resposta or None)
    retomou = status != "UPDATE 0"
    if retomou:
        log.info("marketing_suspension_lifted", lead_id=lead_id, channel=canal)
    return retomou


async def abrir_revisao_humana(lead_id: str, canal: str, *, resumo: str, conversation_id: str | None = None) -> dict[str, Any] | None:
    """Tarefa humana (escalations, gatilho consent_review) para a suspensão aberta. Uma por suspensão: se já existe, devolve a mesma.
    None se não há suspensão aberta (já revogado ou retomado)."""
    trig = next(t for t in escalation_config()["triggers"] if t["id"] == "consent_review")
    p = await db.pool()
    async with p.acquire() as con, con.transaction():
        await _travar(con, lead_id, canal)
        atual = await con.fetchrow(_SQL_ATUAL, lead_id, canal)
        if not atual or atual["status"] != "suspended":
            return None
        if atual["escalation_id"]:
            return {"escalation_id": str(atual["escalation_id"]), "duplicado": True}
        esc = await con.fetchrow(
            """INSERT INTO escalations (conversation_id, lead_id, trigger_id, severity, summary, suggested_action)
               VALUES ($1, $2, $3, $4, $5, $6) RETURNING id""",
            conversation_id, lead_id, trig["id"], trig["severity"], resumo, (trig.get("suggested_action") or "").strip() or None)
        await con.execute("UPDATE consent_log SET escalation_id = $2 WHERE id = $1", atual["id"], esc["id"])
    log.info("consent_review_opened", lead_id=lead_id, channel=canal, escalation_id=str(esc["id"]))
    return {"escalation_id": str(esc["id"]), "duplicado": False}


async def vencer_confirmacoes() -> int:
    """Silêncio: passada a data da pergunta sem "sim" nem "não", o marketing continua suspenso e abre tarefa humana (uma vez).
    Roda pelo scheduler. Devolve quantas tarefas abriu."""
    rows = await db.fetch(
        """SELECT lead_id::text AS lead_id, channel, consent_text FROM consent_log
           WHERE purpose = 'marketing' AND status = 'suspended' AND awaiting_until <= now() AND escalation_id IS NULL""")
    n = 0
    for r in rows:
        res = await abrir_revisao_humana(
            r["lead_id"], r["channel"],
            resumo=f"Sem resposta em {prazo_confirmacao_dias()} dias à pergunta de descadastro (mensagem: {r['consent_text'][:300]!r}). "
                   "O marketing segue suspenso.")
        n += bool(res and not res["duplicado"])
    if n:
        log.info("consent_confirmations_expired", n=n)
    return n


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
