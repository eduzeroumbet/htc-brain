"""Orquestrador: consome os streams e chama o agente certo.

inbound  → triagem (Jev → roteador) → gatilho humano? handoff : consultor do mercado (24/7, sem fila humana)
tasks    → agente.método (cron/eventos)
outbound → adaptador do canal
alerts   → WhatsApp do CEO
"""
from __future__ import annotations

import asyncio
from typing import Any

import structlog

from brain.channels import dispatch, email as email_ch, whatsapp
from brain.core import bus, consent, db, guardrails, registry, retry
from brain.settings import escalation_config, get_settings

log = structlog.get_logger(__name__)
GROUP = "brain"


async def _severe_complaint_confirmed(lead_id: str) -> bool:
    rows = await db.fetch(
        """SELECT m.sentiment FROM messages m JOIN conversations c ON c.id = m.conversation_id
           WHERE c.lead_id = $1 AND m.direction = 'in' ORDER BY m.created_at DESC LIMIT 2""", lead_id)
    return len(rows) == 2 and all((r["sentiment"] or 0) <= -0.6 for r in rows)


async def _handle_consent(event: dict[str, Any], lead: dict[str, Any] | None) -> bool:
    """Descadastro (PARAR, STOP...) e pedido de exclusão de dados no WhatsApp, antes de qualquer agente.

    True = tratado aqui (registrou e respondeu com a confirmação transacional no idioma do lead); o consultor não responde.
    """
    if event["channel"] != "whatsapp":
        return False
    text = event.get("text", "")
    lang_descadastro = consent.detectar_descadastro(text)
    lang_dsar = None if lang_descadastro else consent.detectar_dsar(text)
    if not (lang_descadastro or lang_dsar):
        return False
    if lead is None:  # primeira mensagem já é o descadastro/pedido: o lead precisa existir para o registro
        lead = await db.upsert_lead(event["channel"], event["channel_user_id"], display_name=event.get("display_name"), phone=event.get("phone"))
    lead_id = str(lead["id"])
    lang = consent.idioma_confirmacao(lead.get("language"), lang_descadastro or lang_dsar)
    if lang_descadastro:
        await consent.revogar_marketing(lead_id, event["channel"], texto=text, idioma=lang)
        reply = consent.texto_confirmacao("descadastro", lang)
    else:
        req = await consent.abrir_dsar(lead_id, event["channel"], event["channel_user_id"], text,
                                       jurisdiction="LGPD" if lead.get("market_code") == "BR" else None)
        reply = consent.texto_confirmacao("dsar", lang, prazo=f"{req['due_at']:%d/%m/%Y}")
    conv = await db.open_conversation(lead_id, event["channel"])
    await db.log_message(str(conv["id"]), "in", "client", text, channel_message_id=event.get("message_id"), language=lang,
                         intent="unsubscribe" if lang_descadastro else "dsar_erasure")
    await db.log_message(str(conv["id"]), "out", "system", reply)
    await bus.publish(bus.OUTBOUND, {"channel": event["channel"], "channel_user_id": event["channel_user_id"], "text": reply,
                                     "lead_id": lead_id, "conversation_id": str(conv["id"]), "author": "system",
                                     "purpose": "transactional", "reply_to": event.get("message_id")})
    return True


async def handle_inbound(event: dict[str, Any]) -> None:
    router = registry.get("escalation_router")
    consultant = registry.get("consultant")
    lead = await db.fetchrow("SELECT * FROM leads WHERE channel = $1 AND channel_user_id = $2", event["channel"], event["channel_user_id"])
    if await _handle_consent(event, lead):
        return
    triage = await router.triage(event, lead)  # type: ignore[attr-defined]

    triggers = [t for t in triage["triggers"] if not t.endswith(":candidate")]
    if "severe_complaint:candidate" in triage["triggers"] and lead and await _severe_complaint_confirmed(str(lead["id"])):
        triggers.append("severe_complaint")
    if "vip_arrival:candidate" in triage["triggers"] and "vip_arrival" in {t["id"] for t in escalation_config()["triggers"]}:
        triggers.append("vip_arrival")
    if "business_decision:candidate" in triage["triggers"] or triage.get("intent") == "mice":
        # MICE / grupo grande: o consultor acolhe e o MICE & Eventos (HCB1) monta o RFP e a proposta
        # aviso do sistema vai em campo próprio, nunca concatenado ao texto do cliente (defesa contra injeção de prompt)
        event = {**event, "system_notes": [*event.get("system_notes", []), "Pedido de grupo/evento. Acolha, confirme pax, datas e empresa, diga que a equipe de eventos (HCB1) envia proposta preliminar em 24 h. Não cote aqui."]}
        if lead:
            await bus.publish(bus.TASKS, {"agent": "mice_events", "task": "handle_rfp", "lead_id": str(lead["id"]), "note": event.get("text", "")[:1500]})
    # B2B: agência de viagens pedindo parceria → Prospecção, não o consultor
    if triage.get("intent") == "partner_agency" and not triggers:
        await bus.publish(bus.TASKS, {"agent": "prospector", "task": "inbound_partner", "event": event})

    # o consultor responde SEMPRE (mesmo com handoff, manda a mensagem-ponte do gatilho e abre o caso pela ferramenta)
    if triggers:
        cfg = {t["id"]: t for t in escalation_config()["triggers"]}
        first = sorted(triggers, key=lambda t: ["critical", "high", "medium"].index(cfg[t]["severity"]))[0]
        event = {**event, "system_notes": [*event.get("system_notes", []), f"Gatilho de escalonamento '{first}' detectado. "
                 f"Responda com a mensagem-ponte definida ({cfg[first]['ai_reply_before_handoff'].strip()}) e chame "
                 f"escalate_to_human(trigger_id='{first}') com resumo e ação sugerida."]}
    await consultant.handle_inbound(event, triage)  # type: ignore[attr-defined]


async def handle_task(task: dict[str, Any]) -> None:
    agent_name, method = task["agent"], task["task"]
    if agent_name == "_channels":
        if method == "poll_email":
            await email_ch.poll()
        return
    if agent_name == "prospector" and method == "inbound_partner":
        ev = task["event"]
        prospector = registry.get("prospector")
        text = (await prospector.run(f"Mensagem recebida via {ev['channel']} de uma agência de viagens interessada em parceria:\n"  # type: ignore[attr-defined]
                                     f"{guardrails.untrusted('mensagem_cliente', ev.get('text', ''))}\n{guardrails.DATA_RULE}\n\n"
                                     "Cadastre com upsert_partner_agency (o que der para inferir), responda no idioma dela em ≤ 100 palavras com a proposta de valor "
                                     "(DMC licenciada em Dubai desde 2010, frota própria, comissão a combinar) e peça o e-mail/site; registre com log_outreach.", trigger="event")).text
        if text.strip():
            await bus.publish(bus.OUTBOUND, {"channel": ev["channel"], "channel_user_id": ev["channel_user_id"], "text": text.strip(), "author": "ai:prospector"})
        return
    agent = registry.get(agent_name)
    fn = getattr(agent, method, None)
    if fn is None:
        log.error("task_unknown", agent=agent_name, task=method)
        return
    kwargs: dict[str, Any] = {}
    params = fn.__code__.co_varnames[: fn.__code__.co_argcount]
    if task.get("market_code") is not None and "market_code" in params:
        kwargs["market_code"] = task["market_code"]
    if task.get("note") and "note" in params:
        kwargs["note"] = task["note"]
    if method == "followup":
        kwargs = {"lead_id": task["lead_id"], "note": task.get("note", "")}
    for key in ("lead_id", "partner_id", "text"):
        if task.get(key) and key in params and key not in kwargs:
            kwargs[key] = task[key]
    if task.get("delegated_by"):
        log.info("task_delegated", agent=agent_name, task=method, by=task["delegated_by"], tier_hint=task.get("tier_hint"))
    out = await fn(**kwargs)
    log.info("task_done", agent=agent_name, task=method, market=task.get("market_code"), chars=len(str(out or "")))
    # tarefas encadeadas
    if agent_name == "content_studio" and method == "daily_batch":
        await bus.publish(bus.TASKS, {"agent": "compliance", "task": "review_pending", "market_code": task.get("market_code")})
    if agent_name == "paid_media" and method == "optimize":
        await bus.publish(bus.TASKS, {"agent": "compliance", "task": "review_pending"})
    if agent_name == "ceo" and method == "ceo_briefing":
        await bus.publish(bus.TASKS, {"agent": "ceo", "task": "approve_within_rules"})
    if agent_name == "strategist" and method == "weekly_strategy":
        await bus.publish(bus.TASKS, {"agent": "paid_media", "task": "optimize"})


async def handle_alert(alert: dict[str, Any]) -> None:
    s = get_settings()
    if not s.ceo_whatsapp:
        log.warning("alert_no_ceo_number", text=alert.get("text", "")[:200])
        return
    prefix = {"critical": "🚨 ", "high": "⚠️ ", "medium": "• ", "low": ""}.get(alert.get("severity", "low"), "")
    await whatsapp.send({"channel_user_id": s.ceo_whatsapp.lstrip("+"), "text": f"{prefix}{alert.get('text', '')}"[:4000], "kind": "ceo_alert"})


def _policy(stream: str) -> retry.RetryPolicy:
    """Envio (outbound/alerts) retenta com backoff; inbound/tasks não retentam (evita resposta e custo de LLM em dobro),
    mas a falha vai para a DLQ em vez de sumir."""
    s = get_settings()
    attempts = s.queue_max_attempts if stream in (bus.OUTBOUND, bus.ALERTS) else 1
    return retry.RetryPolicy(max_attempts=max(1, attempts), base_delay_s=s.queue_retry_base_delay_s,
                             max_delay_s=s.queue_retry_max_delay_s, jitter_ratio=s.queue_retry_jitter_ratio)


async def _loop(stream: str, handler, consumer: str) -> None:
    policy = _policy(stream)
    async for msg_id, event in bus.consume(stream, GROUP, consumer):
        try:
            await handler(event)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:  # noqa: BLE001 — nada derruba o worker; a falha vira retry agendado ou DLQ
            try:
                d = await retry.route_failure(bus, stream, msg_id, event, exc, policy)
                log.error("handler_failed", stream=stream, consumer=consumer, action=d.action, attempts=d.attempts,
                          delay_s=round(d.delay_s, 1), error=d.reason[:400])
            except Exception as route_exc:  # noqa: BLE001 — sem registro durável não há ack: a entrega fica pendente
                log.error("failure_routing_failed", stream=stream, msg_id=msg_id, error=f"{type(route_exc).__name__}"[:200])
                continue
        try:  # ack só depois de sucesso ou de a falha estar gravada (retry/DLQ)
            await bus.ack(stream, GROUP, msg_id)
        except Exception:  # noqa: BLE001
            log.error("ack_failed", stream=stream, msg_id=msg_id)


async def _retry_pump() -> None:
    """Devolve aos streams as reentregas cujo backoff venceu."""
    while True:
        for stream in (bus.OUTBOUND, bus.ALERTS, bus.INBOUND, bus.TASKS):
            n = await bus.pump_retries(stream)
            if n:
                log.info("retry_requeued", stream=stream, n=n)
        await asyncio.sleep(1)


async def _supervise_pump() -> None:
    while True:
        try:
            await _retry_pump()
        except asyncio.CancelledError:
            raise
        except BaseException as exc:  # noqa: BLE001
            log.error("worker_died", stream="retry", consumer="retry-pump", error=f"{type(exc).__name__}: {exc}"[:400])
            await asyncio.sleep(5)


async def _supervise(stream: str, handler, consumer: str) -> None:
    """Mantém o worker vivo: se o loop morrer (Redis caiu, bug), registra e sobe de novo em 5 s."""
    while True:
        try:
            await _loop(stream, handler, consumer)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:  # noqa: BLE001
            log.error("worker_died", stream=stream, consumer=consumer, error=f"{type(exc).__name__}: {exc}"[:400])
            await asyncio.sleep(5)


async def run_workers() -> list[asyncio.Task]:
    """Sobe os consumidores supervisionados. Vários consumidores de inbound para responder em paralelo."""
    specs = [*((bus.INBOUND, handle_inbound, f"inbound-{i}") for i in range(4)),
             *((bus.TASKS, handle_task, f"tasks-{i}") for i in range(2)),
             (bus.OUTBOUND, dispatch, "outbound-0"), (bus.ALERTS, handle_alert, "alerts-0")]
    tasks = [asyncio.create_task(_supervise(*spec), name=f"worker:{spec[2]}") for spec in specs]
    tasks.append(asyncio.create_task(_supervise_pump(), name="worker:retry-pump"))
    log.info("workers_started", n=len(tasks))
    return tasks
