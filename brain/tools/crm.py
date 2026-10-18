"""CRM: leads, estágios, consentimento, histórico."""
from __future__ import annotations

from typing import Any

from brain.core import db
from brain.tools import create_sdk_mcp_server, err, ok, tool

SERVER = "crm"


@tool("find_lead", "Busca o lead pelo id ou pelo identificador do canal (telefone, ig id, chat id, e-mail).", {"lead_id": str, "channel": str, "channel_user_id": str})
async def find_lead(args: dict[str, Any]) -> dict[str, Any]:
    if args.get("lead_id"):
        row = await db.fetchrow("SELECT * FROM leads WHERE id = $1", args["lead_id"])
    else:
        row = await db.fetchrow("SELECT * FROM leads WHERE channel = $1 AND channel_user_id = $2",
                                args.get("channel"), args.get("channel_user_id"))
    return ok(row or {"found": False})


@tool("update_lead", "Atualiza campos do lead: stage, segment, travel_dates (YYYY-MM-DD/YYYY-MM-DD), pax_adults, pax_children, budget_usd_min, budget_usd_max, occasion, display_name, email, phone, notes, language.", {"lead_id": str, "fields": dict})
async def update_lead(args: dict[str, Any]) -> dict[str, Any]:
    allowed = {"stage", "segment", "travel_dates", "pax_adults", "pax_children", "budget_usd_min", "budget_usd_max",
               "occasion", "display_name", "email", "phone", "notes", "language", "score"}
    fields = {k: v for k, v in (args.get("fields") or {}).items() if k in allowed}
    if not fields:
        return err("nenhum campo válido")
    if "travel_dates" in fields and isinstance(fields["travel_dates"], str) and "/" in fields["travel_dates"]:
        a, b = fields["travel_dates"].split("/")
        fields["travel_dates"] = f"[{a},{b}]"
    sets = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(fields))
    row = await db.fetchrow(f"UPDATE leads SET {sets} WHERE id = $1 RETURNING *", args["lead_id"], *fields.values())
    return ok(row or {"updated": False})


@tool("record_consent", "Registra consentimento de marketing e opt-in de WhatsApp do lead.", {"lead_id": str, "marketing": bool, "whatsapp": bool})
async def record_consent(args: dict[str, Any]) -> dict[str, Any]:
    await db.execute(
        "UPDATE leads SET consent_marketing = $2, opt_in_whatsapp = $3, consent_at = now() WHERE id = $1",
        args["lead_id"], bool(args.get("marketing")), bool(args.get("whatsapp")),
    )
    return ok({"recorded": True})


@tool("conversation_history", "Últimas N mensagens da conversa do lead (padrão 20).", {"lead_id": str, "limit": int})
async def conversation_history(args: dict[str, Any]) -> dict[str, Any]:
    rows = await db.fetch(
        """SELECT m.direction, m.author, m.body, m.created_at FROM messages m
           JOIN conversations c ON c.id = m.conversation_id
           WHERE c.lead_id = $1 ORDER BY m.created_at DESC LIMIT $2""",
        args["lead_id"], int(args.get("limit") or 20),
    )
    return ok(list(reversed(rows)))


@tool("lead_bookings", "Cotações e reservas do lead.", {"lead_id": str})
async def lead_bookings(args: dict[str, Any]) -> dict[str, Any]:
    quotes = await db.fetch("SELECT id, title, total_usd, total_local, local_currency, status, valid_until, pdf_url FROM quotes WHERE lead_id = $1 ORDER BY created_at DESC LIMIT 5", args["lead_id"])
    bookings = await db.fetch("SELECT id, ref, travel_start, travel_end, total_usd, paid_usd, payment_status, status FROM bookings WHERE lead_id = $1 ORDER BY created_at DESC LIMIT 5", args["lead_id"])
    return ok({"quotes": quotes, "bookings": bookings})


@tool("schedule_followup", "Agenda um follow-up (D+1, D+3, D+7) para o lead com uma mensagem-guia.", {"lead_id": str, "days": int, "note": str})
async def schedule_followup(args: dict[str, Any]) -> dict[str, Any]:
    from brain.core import bus
    await bus.publish(bus.TASKS, {"agent": "consultant", "task": "followup", "lead_id": args["lead_id"],
                                  "due_in_days": int(args.get("days") or 1), "note": args.get("note", "")})
    return ok({"scheduled": True, "days": int(args.get("days") or 1)})


@tool("promise_proposal", "Registra a PROMESSA de proposta em até 30 min (use quando o cliente confirmou interesse e deu os dados). summary = o que montar: datas/mês, pax, hotel/voo/atrações/transfer, orçamento sinalizado, preferências. Devolve o horário-limite para você dizer ao cliente.", {"lead_id": str, "conversation_id": str, "summary": str})
async def promise_proposal(args: dict[str, Any]) -> dict[str, Any]:
    row = await db.fetchrow(
        """INSERT INTO proposal_requests (lead_id, conversation_id, summary, due_at) VALUES ($1, $2, $3, now() + interval '30 minutes')
           RETURNING id, due_at""", args["lead_id"], args.get("conversation_id"), args["summary"][:3000])
    await db.execute("UPDATE leads SET stage = CASE WHEN stage IN ('new','qualifying') THEN 'qualified' ELSE stage END WHERE id = $1", args["lead_id"])
    from brain.core import bus
    await bus.publish(bus.ALERTS, {"kind": "proposal", "severity": "medium", "text": f"Proposta prometida para {row['due_at']:%H:%M} (Dubai) — lead {args['lead_id'][:8]}: {args['summary'][:200]}"})  # type: ignore[index]
    return ok({"proposal_request_id": str(row["id"]), "due_at": str(row["due_at"]), "say_to_client": "proposta em até 30 minutos"})  # type: ignore[index]


@tool("proposal_queue", "Propostas prometidas ainda não enviadas, com minutos restantes (negativo = atrasada).", {})
async def proposal_queue(args: dict[str, Any]) -> dict[str, Any]:
    rows = await db.fetch("""SELECT p.id, p.lead_id, p.conversation_id, p.summary, p.status, p.due_at, extract(epoch from (p.due_at - now()))/60 AS minutes_left,
                                    l.display_name, l.channel, l.channel_user_id, l.market_code, l.language
                             FROM proposal_requests p JOIN leads l ON l.id = p.lead_id
                             WHERE p.status IN ('requested','interim_sent') ORDER BY p.due_at""")
    return ok(rows)


@tool("mark_proposal", "Atualiza a proposta prometida: status sent (com quote_id opcional) | escalated | late, e notas.", {"proposal_request_id": str, "status": str, "quote_id": str, "notes": str})
async def mark_proposal(args: dict[str, Any]) -> dict[str, Any]:
    await db.execute("""UPDATE proposal_requests SET status = $2, quote_id = COALESCE($3, quote_id), notes = COALESCE($4, notes),
                        sent_at = CASE WHEN $2 = 'sent' THEN now() ELSE sent_at END, escalated_at = CASE WHEN $2 = 'escalated' THEN now() ELSE escalated_at END
                        WHERE id = $1""", args["proposal_request_id"], args["status"], args.get("quote_id"), args.get("notes"))
    return ok({"updated": True})


def server():
    return create_sdk_mcp_server(SERVER, "1.0.0", [find_lead, update_lead, record_consent, conversation_history, lead_bookings, schedule_followup, promise_proposal, proposal_queue, mark_proposal])
