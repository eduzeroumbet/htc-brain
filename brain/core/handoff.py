"""Transbordo para humano: gatilhos, fila (handoff_events), alerta à equipe, SLA e métricas da Camada 0 do dashboard.

Gatilhos: human_request, proposal, payment, complaint, dsar (acesso, exclusão ou revogação de dados).
- detectar(): frase-chave inteira em pt, en, es, ar (normalizada como em consent.normalizar) + classificação da triagem
  (intenção e probabilidades do Jev; Haiku no fallback). Proposta e pagamento exigem o modelo: palavra solta não abre transbordo.
- registrar(): um evento por (conversa, gatilho) enquanto estiver na fila; repetição só soma occurrence_count.
- alertar(): e-mail e/ou WhatsApp interno (HANDOFF_ALERT_*). Falha de canal nunca sobe para o atendimento: fica em
  last_alert_error e a varredura tenta de novo. Envio na hora + varredura a cada 60 s = alerta em até 1 minuto.
- varrer(): marca atendido quando um humano escreveu na conversa, reenvia alertas pendentes e escala o que venceu o SLA.
- metricas_camada0(): fila aberta, maior espera, tempo médio e % dentro do SLA (24 h e 7 dias).
O relógio é agora(); os testes trocam por um relógio simulado.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from brain.channels import email as email_ch
from brain.channels import whatsapp
from brain.core import consent, db
from brain.settings import get_settings, handoff_config

log = structlog.get_logger(__name__)

GATILHOS = ("human_request", "proposal", "payment", "complaint", "dsar")
NA_FILA = ("open", "alerted", "breached")   # esperando humano
MIN_CONFIANCA = 0.7                          # proposta/pagamento: intenção com confiança ≥ 0,7, ou intenção + frase-chave
CLAIM_S = 30                                 # um envio por vez por evento: o envio na hora e a varredura não alertam em dobro


def agora() -> datetime:
    return datetime.now(timezone.utc)


# ───────────────────────── detecção ─────────────────────────

FRASES: dict[str, dict[str, tuple[str, ...]]] = {
    "human_request": {
        "pt": ("falar com atendente", "falar com um atendente", "falar com uma pessoa", "falar com alguém", "falar com humano",
               "falar com um humano", "atendente humano", "atendimento humano", "pessoa de verdade", "quero um atendente"),
        "en": ("talk to a human", "speak to a human", "talk to a person", "speak to a person", "talk to someone", "speak to someone",
               "real person", "human agent", "talk to an agent", "speak to an agent", "customer service", "representative"),
        "es": ("hablar con un humano", "hablar con una persona", "hablar con alguien", "hablar con un agente", "persona real",
               "agente humano", "atención al cliente"),
        "ar": ("أريد التحدث مع شخص", "التحدث مع موظف", "أريد موظف", "خدمة العملاء", "شخص حقيقي"),
    },
    "proposal": {
        "pt": ("orçamento", "cotação", "proposta", "quanto custa", "quanto fica", "quanto sai"),
        "en": ("quote", "quotation", "proposal", "how much", "price for", "estimate"),
        "es": ("presupuesto", "cotización", "propuesta", "cuánto cuesta", "cuánto sale", "cuánto vale"),
        "ar": ("عرض سعر", "تسعيرة", "كم السعر", "كم التكلفة", "كم سعر"),
    },
    "payment": {
        "pt": ("pagar", "pagamento", "link de pagamento", "forma de pagamento", "pix", "cartão", "boleto", "transferência",
               "reembolso", "estorno", "cobrança"),
        "en": ("pay", "payment", "payment link", "credit card", "bank transfer", "refund", "charge", "invoice"),
        "es": ("pagar", "pago", "enlace de pago", "link de pago", "tarjeta", "transferencia", "reembolso", "factura", "cobro"),
        "ar": ("الدفع", "ادفع", "رابط الدفع", "بطاقة", "تحويل بنكي", "استرداد", "فاتورة"),
    },
    "complaint": {
        "pt": ("reclamação", "quero reclamar", "fazer uma reclamação", "reclame aqui", "procon"),
        "en": ("complaint", "i want to complain", "file a complaint", "make a complaint"),
        "es": ("queja", "reclamo", "reclamación", "quiero reclamar", "poner una queja"),
        "ar": ("شكوى", "أريد تقديم شكوى", "تقديم شكوى"),
    },
}
# DSAR por subtipo; a exclusão em pt, en, ar e hi vem de consent.FRASES_DSAR (o mesmo texto que abre data_requests)
FRASES_DSAR: dict[str, dict[str, tuple[str, ...]]] = {
    "access": {
        "pt": ("acesso aos meus dados", "acessar meus dados", "cópia dos meus dados", "quais dados vocês têm"),
        "en": ("access my data", "access to my data", "copy of my data", "what data do you have", "subject access request"),
        "es": ("acceso a mis datos", "copia de mis datos", "qué datos tienen"),
        "ar": ("الوصول إلى بياناتي", "نسخة من بياناتي"),
    },
    "erasure": {
        **consent.FRASES_DSAR,
        "es": ("eliminar mis datos", "borrar mis datos", "suprimir mis datos", "eliminar mi cuenta", "borrar mi cuenta",
               "derecho al olvido"),
    },
    "revocation": {
        "pt": ("revogar consentimento", "revogar o consentimento", "revogar meu consentimento", "revogo meu consentimento",
               "retirar meu consentimento"),
        "en": ("revoke consent", "revoke my consent", "withdraw consent", "withdraw my consent"),
        "es": ("revocar consentimiento", "revocar mi consentimiento", "retirar mi consentimiento", "revoco mi consentimiento"),
        "ar": ("سحب الموافقة", "سحب موافقتي", "إلغاء موافقتي"),
    },
}


def _normalizar_tabela(tabela: dict[str, tuple[str, ...]]) -> list[tuple[str, str, list[str]]]:
    return [(lang, frase, consent.normalizar(frase).split()) for lang, frases in tabela.items() for frase in frases]


_FRASES_NORM = {g: _normalizar_tabela(t) for g, t in FRASES.items()}
_DSAR_NORM = {sub: _normalizar_tabela(t) for sub, t in FRASES_DSAR.items()}


def _procurar(tokens: list[str], tabela: list[tuple[str, str, list[str]]]) -> tuple[str, list[str]] | None:
    """(idioma com mais frases batidas, frases que bateram) — frase como sequência inteira de palavras, nunca por trecho.
    pt e es dividem palavras ("pagar", "reembolso"): o idioma é o que tem mais frases na mensagem; empate fica com o primeiro."""
    hits = [(lang, frase) for lang, frase, seq in tabela
            if seq and any(tokens[i:i + len(seq)] == seq for i in range(len(tokens) - len(seq) + 1))]
    if not hits:
        return None
    langs = [lang for lang, _ in hits]
    return max(dict.fromkeys(langs), key=langs.count), [f for _, f in hits]


def detectar(texto: str | None, triagem: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Gatilhos de transbordo da mensagem, no máximo um por gatilho: [{trigger, subtype, detected_by, language, details}].

    triagem = saída do Roteador (intent, confidence, sentiment, language, jev_raw com p_human, p_severe, p_dsar).
    """
    tokens = consent.normalizar(texto).split()
    t = triagem or {}
    raw = t.get("jev_raw") or {}
    intent, conf = t.get("intent"), float(t.get("confidence") or 0)
    sentiment = float(t.get("sentiment") or 0)
    kw = {g: _procurar(tokens, tab) for g, tab in _FRASES_NORM.items()}
    dsar_kw = next(((sub, hit) for sub, tab in _DSAR_NORM.items() if (hit := _procurar(tokens, tab))), None)

    modelo = {
        "human_request": intent == "human_request" or float(raw.get("p_human") or 0) >= 0.5,
        "proposal": intent == "quote_request" and (conf >= MIN_CONFIANCA or bool(kw["proposal"])),
        "payment": intent in ("payment", "refund") and (conf >= MIN_CONFIANCA or bool(kw["payment"])),
        "complaint": (intent == "complaint" and sentiment <= -0.6) or float(raw.get("p_severe") or 0) >= 0.5,
        "dsar": float(raw.get("p_dsar") or 0) >= 0.7,
    }
    # proposta e pagamento são o fluxo normal de venda: sem o modelo confirmar, a frase sozinha não abre transbordo
    por_frase = {**kw, "proposal": None, "payment": None, "dsar": dsar_kw[1] if dsar_kw else None}
    if modelo["proposal"]:
        por_frase["proposal"] = kw["proposal"]
    if modelo["payment"]:
        por_frase["payment"] = kw["payment"]

    out = []
    for g in GATILHOS:
        hit, pelo_modelo = por_frase.get(g), modelo[g]
        if not (hit or pelo_modelo):
            continue
        out.append({
            "trigger": g,
            "subtype": dsar_kw[0] if g == "dsar" and dsar_kw else None,
            "detected_by": "keyword+model" if hit and pelo_modelo else "keyword" if hit else "model",
            "language": (hit[0] if hit else None) or t.get("language"),
            "details": {"terms": hit[1] if hit else [], "intent": intent, "confidence": round(conf, 3)},
        })
    return out


# ───────────────────────── fila ─────────────────────────

def sla_segundos(trigger: str) -> int:
    return int(handoff_config()["triggers"][trigger]["sla_minutes"]) * 60


def avisa_cliente(trigger: str) -> bool:
    return bool(handoff_config()["triggers"][trigger].get("notify_client"))


def nota_cliente(trigger: str, idioma: str | None) -> str:
    """Nota de sistema para o consultor: aviso neutro de que a equipe vai assumir, no idioma do cliente."""
    cfg = handoff_config()
    ref = cfg["client_notice"].get((idioma or "").split("-")[0]) or cfg["client_notice"]["pt"]
    return (f"Transbordo '{cfg['triggers'][trigger]['label']}': a equipe já foi avisada. Inclua na resposta, no idioma do cliente, "
            f"um aviso curto e neutro de que a equipe vai assumir (referência: \"{ref}\"). Não prometa prazo, não diga quem vai "
            "atender e não mude o tom da conversa.")


async def registrar(conversation_id: str, lead_id: str | None, deteccao: dict[str, Any]) -> dict[str, Any]:
    """Abre o evento ou, se já houver um na fila para (conversa, gatilho), só conta a nova ocorrência. Devolve {id, novo, status}."""
    now = agora()
    row = await db.fetchrow(
        """INSERT INTO handoff_events (conversation_id, lead_id, trigger, trigger_subtype, detected_by, language, sla_seconds,
                                       created_at, last_occurrence_at, updated_at, details)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $8, $8, $9)
           ON CONFLICT (conversation_id, trigger) WHERE status IN ('open', 'alerted', 'breached', 'attended')
           DO UPDATE SET occurrence_count = handoff_events.occurrence_count + 1,
                         last_occurrence_at = EXCLUDED.last_occurrence_at, updated_at = EXCLUDED.updated_at
           RETURNING id, status, occurrence_count, (xmax = 0) AS novo""",
        conversation_id, lead_id, deteccao["trigger"], deteccao.get("subtype"), deteccao["detected_by"], deteccao.get("language"),
        sla_segundos(deteccao["trigger"]), now, deteccao.get("details") or {})
    assert row is not None
    out = {"id": str(row["id"]), "novo": bool(row["novo"]), "status": row["status"]}
    log.info("handoff_registered" if out["novo"] else "handoff_duplicate", event_id=out["id"], trigger=deteccao["trigger"],
             detected_by=deteccao["detected_by"], conversation_id=conversation_id, occurrences=row["occurrence_count"])
    return out


_tarefas: set[asyncio.Task] = set()


def alertar_em_segundo_plano(event_id: str) -> None:
    """Alerta sem segurar a resposta ao cliente; se o processo cair antes, a varredura de 60 s envia."""
    task = asyncio.create_task(alertar(event_id), name=f"handoff_alert:{event_id[:8]}")
    _tarefas.add(task)
    task.add_done_callback(_tarefas.discard)


async def marcar_atendido(*, event_id: str | None = None, conversation_id: str | None = None, por: str) -> int:
    """Humano assumiu (painel) ou respondeu: atendido_em = agora. Devolve quantos eventos saíram da fila."""
    now = agora()
    res = await db.execute(
        """UPDATE handoff_events SET status = 'attended', attended_at = $3, attended_by = $4, updated_at = $3
           WHERE status IN ('open', 'alerted', 'breached') AND (id = $1::uuid OR conversation_id = $2::uuid)""",
        event_id, conversation_id, now, por)
    return _linhas(res)


async def fechar(*, conversation_id: str, por: str) -> int:
    """Caso resolvido: fecha os eventos da conversa (quem não tinha atendimento registrado fica atendido agora)."""
    now = agora()
    res = await db.execute(
        """UPDATE handoff_events SET status = 'closed', closed_at = $2, attended_at = coalesce(attended_at, $2),
                  attended_by = coalesce(attended_by, $3), updated_at = $2
           WHERE conversation_id = $1::uuid AND status IN ('open', 'alerted', 'breached', 'attended')""",
        conversation_id, now, por)
    return _linhas(res)


def _linhas(res: str | None) -> int:
    try:
        return int((res or "0").split()[-1])
    except ValueError:
        return 0


# ───────────────────────── alerta à equipe ─────────────────────────

def _lista(valor: str) -> list[str]:
    return [v.strip() for v in (valor or "").split(",") if v.strip()]


def destinos(escalonamento: bool = False) -> dict[str, list[str]]:
    s = get_settings()
    email = _lista(s.handoff_escalation_email_to) if escalonamento else []
    wa = _lista(s.handoff_escalation_whatsapp_to) if escalonamento else []
    return {"email": email or _lista(s.handoff_alert_email_to), "whatsapp": wa or _lista(s.handoff_alert_whatsapp_to)}


def canais() -> tuple[list[str], bool]:
    """(ordem dos canais, enviar em todos?). Canal único: o outro só entra se o principal falhar."""
    modo = get_settings().handoff_alert_channel.strip().lower()
    if modo == "both":
        return ["email", "whatsapp"], True
    return (["whatsapp", "email"] if modo == "whatsapp" else ["email", "whatsapp"]), False


def texto_alerta(ev: dict[str, Any], lead: dict[str, Any] | None, escalonamento: bool, now: datetime) -> tuple[str, str]:
    """(assunto, corpo) do alerta interno, em português. Sem texto do cliente nem telefone."""
    cfg = handoff_config()["triggers"][ev["trigger"]]
    quem = (lead or {}).get("display_name") or "cliente"
    espera = int((now - ev["created_at"]).total_seconds() // 60)
    sub = f" ({ev['trigger_subtype']})" if ev.get("trigger_subtype") else ""
    assunto = f"[HTC · {'SLA vencido' if escalonamento else 'Transbordo'}] {cfg['label']} · {quem}"
    corpo = "\n".join([
        *(["SLA VENCIDO: ninguém assumiu esta conversa ainda."] if escalonamento else []),
        f"Gatilho: {cfg['label']}{sub}",
        f"Cliente: {quem} · mercado {(lead or {}).get('market_code') or '?'} · canal {(lead or {}).get('channel') or '?'}",
        f"Conversa: {ev['conversation_id']}",
        f"Esperando há {espera} min · SLA {ev['sla_seconds'] // 60} min",
        f"Detectado por: {ev['detected_by']} · ocorrências: {ev['occurrence_count']}",
        f"Painel (Camada 0 → Assumir): https://{get_settings().domain}/#camada0",
    ])
    return assunto, corpo


async def _enviar_canal(canal: str, destino: str, assunto: str, texto: str) -> None:
    s = get_settings()
    if canal == "email":
        if not s.smtp_host:
            raise RuntimeError("SMTP_HOST vazio")
        await email_ch.send({"channel_user_id": destino, "subject": assunto, "text": texto})
    else:
        if not (s.wa_phone_number_id and s.wa_access_token):
            raise RuntimeError("WhatsApp Cloud API sem credenciais")
        await whatsapp.send({"channel_user_id": destino.lstrip("+"), "text": f"{assunto}\n{texto}"[:4000], "kind": "team_alert"})


async def _enviar(canal: str, para: list[str], assunto: str, texto: str) -> None:
    """Entrega se ao menos um destinatário recebeu; senão levanta o último erro."""
    erro: Exception | None = None
    ok = 0
    for destino in para:
        try:
            await _enviar_canal(canal, destino, assunto, texto)
            ok += 1
        except Exception as exc:  # noqa: BLE001
            erro = exc
    if not ok:
        raise erro or RuntimeError("sem destinatário")


async def alertar(event_id: str, *, escalonamento: bool = False) -> bool:
    """Envia o alerta (ou o de escalonamento) do evento. Nunca levanta exceção: a falha fica no evento. True se entregou."""
    try:
        return await _alertar(event_id, escalonamento)
    except Exception as exc:  # noqa: BLE001 — o atendimento não pode cair por causa do alerta
        log.error("handoff_alert_crashed", event_id=event_id, error=f"{type(exc).__name__}: {exc}"[:300])
        return False


async def _alertar(event_id: str, escalonamento: bool) -> bool:
    s = get_settings()
    now = agora()
    # trava de CLAIM_S segundos por evento; o escalonamento tem cota própria (até o dobro de tentativas)
    ev = await db.fetchrow(
        f"""UPDATE handoff_events SET alert_attempts = alert_attempts + 1, last_alert_at = $2, updated_at = $2
            WHERE id = $1 AND (last_alert_at IS NULL OR last_alert_at <= $3) AND alert_attempts < $4
              AND {"status = 'breached' AND escalated_at IS NULL" if escalonamento else "status = 'open' AND alerted_at IS NULL"}
            RETURNING *""",
        event_id, now, now - timedelta(seconds=CLAIM_S),
        s.handoff_alert_max_attempts * (2 if escalonamento else 1))
    if not ev:
        return False
    lead = await db.fetchrow("SELECT display_name, market_code, channel FROM leads WHERE id = $1", ev["lead_id"]) if ev.get("lead_id") else None
    assunto, texto = texto_alerta(ev, lead, escalonamento, now)
    para = destinos(escalonamento)
    ordem, todos = canais()
    enviados: list[str] = []
    erros: list[str] = []
    for canal in ordem:
        if enviados and not todos:
            break
        if not para[canal]:
            erros.append(f"{canal}: sem destinatário")
            continue
        try:
            await asyncio.wait_for(_enviar(canal, para[canal], assunto, texto), timeout=s.handoff_alert_timeout_s)
            enviados.append(canal)
        except Exception as exc:  # noqa: BLE001 — TimeoutError, SMTP, Graph API: registra e segue para o outro canal
            erros.append(f"{canal}: {type(exc).__name__}: {exc}"[:200])
    erro = "; ".join(erros) or None
    if not enviados:
        await db.execute("UPDATE handoff_events SET last_alert_error = $2, updated_at = $3 WHERE id = $1", event_id, erro, now)
        log.warning("handoff_alert_failed", event_id=event_id, escalation=escalonamento, attempts=ev["alert_attempts"], error=erro)
        return False
    canal_ok = "+".join(enviados)
    if escalonamento:
        await db.execute(
            """UPDATE handoff_events SET escalated_at = $2, alert_channel = coalesce(alert_channel, $3), last_alert_error = $4,
                      updated_at = $2 WHERE id = $1""", event_id, now, canal_ok, erro)
    else:
        await db.execute(
            """UPDATE handoff_events SET alerted_at = $2, alert_channel = $3, last_alert_error = $4, updated_at = $2,
                      status = CASE WHEN status = 'open' THEN 'alerted' ELSE status END WHERE id = $1""", event_id, now, canal_ok, erro)
    log.info("handoff_alerted", event_id=event_id, escalation=escalonamento, channel=canal_ok,
             seconds_since_created=round((now - ev["created_at"]).total_seconds(), 1))
    return True


# ───────────────────────── varredura (scheduler, a cada 60 s) ─────────────────────────

async def varrer() -> dict[str, int]:
    """Atendido por mensagem humana → alertas pendentes → SLA vencido vira 'breached' e é escalonado. Nunca levanta exceção."""
    s = get_settings()
    now = agora()
    out = {"attended": 0, "alerted": 0, "breached": 0, "escalated": 0}
    try:
        # atendido_em = primeira mensagem de humano (author 'human:<nome>') na conversa depois da detecção
        out["attended"] = _linhas(await db.execute(
            """UPDATE handoff_events h SET status = 'attended', attended_at = m.created_at, attended_by = m.author, updated_at = $1
               FROM (SELECT DISTINCT ON (e.id) e.id, msg.created_at, msg.author
                     FROM handoff_events e JOIN messages msg ON msg.conversation_id = e.conversation_id
                     WHERE e.status IN ('open', 'alerted', 'breached') AND msg.direction = 'out' AND msg.author LIKE 'human:%'
                       AND msg.created_at >= e.created_at
                     ORDER BY e.id, msg.created_at) m
               WHERE h.id = m.id""", now))
        pendentes = await db.fetch(
            """SELECT id FROM handoff_events WHERE status = 'open' AND alerted_at IS NULL AND alert_attempts < $1
               ORDER BY created_at LIMIT 50""", s.handoff_alert_max_attempts)
        for p in pendentes:
            out["alerted"] += await alertar(str(p["id"]))
        vencidos = await db.fetch(
            """UPDATE handoff_events SET status = 'breached', breached_at = $1, updated_at = $1
               WHERE status IN ('open', 'alerted') AND created_at + make_interval(secs => sla_seconds) <= $1 RETURNING id""", now)
        out["breached"] = len(vencidos)
        a_escalar = await db.fetch(
            """SELECT id FROM handoff_events WHERE status = 'breached' AND escalated_at IS NULL AND alert_attempts < $1
               ORDER BY created_at LIMIT 50""", 2 * s.handoff_alert_max_attempts)
        for e in a_escalar:
            out["escalated"] += await alertar(str(e["id"]), escalonamento=True)
    except Exception as exc:  # noqa: BLE001
        log.error("handoff_sweep_failed", error=f"{type(exc).__name__}: {exc}"[:300])
    if any(out.values()):
        log.info("handoff_sweep", **out)
    return out


# ───────────────────────── Camada 0 ─────────────────────────

def _espera(r: dict[str, Any], now: datetime) -> float:
    return ((r.get("attended_at") or now) - r["created_at"]).total_seconds()


def _pct_sla(rows: list[dict[str, Any]], now: datetime, desde: datetime) -> float | None:
    """% dentro do SLA dos eventos criados desde `desde`: atendidos (espera ≤ SLA) e os que já venceram na fila (fora).
    Quem ainda está na fila dentro do prazo não entra na conta."""
    dentro = fora = 0
    for r in rows:
        if r["created_at"] < desde:
            continue
        w = _espera(r, now)
        if r.get("attended_at"):
            dentro, fora = dentro + (w <= r["sla_seconds"]), fora + (w > r["sla_seconds"])
        elif w > r["sla_seconds"]:
            fora += 1
    return round(dentro / (dentro + fora) * 100, 1) if dentro + fora else None


def calcular_metricas(fila: list[dict[str, Any]], janela: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    """fila = eventos esperando humano; janela = eventos criados nos últimos 7 dias (qualquer status)."""
    cfg = handoff_config()["triggers"]
    esperas = [_espera(r, now) for r in fila]
    dia = now - timedelta(days=1)
    atendidos_24h = [_espera(r, now) for r in janela if r.get("attended_at") and r["created_at"] >= dia]
    return {
        "generated_at": now,
        "open_queue_count": len(fila),
        "oldest_wait_seconds": round(max(esperas)) if esperas else 0,
        "avg_wait_seconds": round(sum(esperas) / len(esperas)) if esperas else 0,
        "avg_wait_attended_seconds_24h": round(sum(atendidos_24h) / len(atendidos_24h)) if atendidos_24h else None,
        "sla_within_pct_24h": _pct_sla(janela, now, dia),
        "sla_within_pct_7d": _pct_sla(janela, now, now - timedelta(days=7)),
        "breached_open_count": sum(1 for r, w in zip(fila, esperas) if w > r["sla_seconds"]),
        "alert_pending_count": sum(1 for r in fila if not r.get("alerted_at")),
        "by_trigger": {g: sum(1 for r in fila if r["trigger"] == g) for g in GATILHOS},
        "sla_minutes": {g: c["sla_minutes"] for g, c in cfg.items()},
        "queue": [{
            "id": str(r["id"]), "conversation_id": str(r["conversation_id"]), "trigger": r["trigger"], "label": cfg[r["trigger"]]["label"],
            "subtype": r.get("trigger_subtype"), "status": r["status"], "created_at": r["created_at"],
            "wait_seconds": round(w), "sla_seconds": r["sla_seconds"], "sla_left_seconds": round(r["sla_seconds"] - w),
            "alert_pending": not r.get("alerted_at"), "alert_error": r.get("last_alert_error"),
            "occurrences": r.get("occurrence_count", 1), "display_name": r.get("display_name"),
            "market_code": r.get("market_code"), "channel": r.get("channel"),
        } for r, w in sorted(zip(fila, esperas), key=lambda x: -x[1])],
    }


async def metricas_camada0() -> dict[str, Any]:
    now = agora()
    fila = await db.fetch(
        """SELECT h.id, h.conversation_id, h.trigger, h.trigger_subtype, h.status, h.created_at, h.alerted_at, h.attended_at,
                  h.sla_seconds, h.last_alert_error, h.occurrence_count, l.display_name, l.market_code, l.channel
           FROM handoff_events h LEFT JOIN leads l ON l.id = h.lead_id
           WHERE h.status IN ('open', 'alerted', 'breached') ORDER BY h.created_at""")
    janela = await db.fetch(
        "SELECT trigger, status, created_at, attended_at, sla_seconds FROM handoff_events WHERE created_at >= $1",
        now - timedelta(days=7))
    return calcular_metricas(fila, janela, now)
