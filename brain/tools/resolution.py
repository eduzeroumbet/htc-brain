"""Operacional: problemas (issues) com ingressos, atrações, hotéis e transfers; emissões; programação para o pessoal de resolução.

Regra: todo problema abre um issue. A máquina resolve o que dá por fornecedor/plataforma; quando precisa de alguém
presencial (ir ao balcão da atração, acompanhar cliente no hospital, levar documento), cria um field_assignment
kind=issue_resolution para o funcionário de resolução (config/humans.yaml → resolution_staff / advanced_support) e
envia a programação pelo WhatsApp de campo. O Jev calibra a severidade.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Any

import yaml

from brain.core import bus, db, jev
from brain.tools import create_sdk_mcp_server, err, ok, tool

SERVER = "resolution"
HUMANS = yaml.safe_load(open(os.path.join(os.path.dirname(__file__), "..", "..", "config", "humans.yaml"), encoding="utf-8"))


def _staff() -> list[dict[str, Any]]:
    return HUMANS.get("resolution_staff") or HUMANS.get("advanced_support", {}).get("roster", [])


@tool("open_issue", "Abre um problema operacional. kind: ticket|attraction|hotel|transfer|flight|payment|document|other. O Jev calibra a severidade e o prazo (critical=agora, high=2h, medium=24h, low=72h).", {"booking_id": str, "lead_id": str, "kind": str, "title": str, "detail": str, "owner_agent": str})
async def open_issue(args: dict[str, Any]) -> dict[str, Any]:
    sev = "medium"
    ans = await jev.decide({"kind": args["kind"], "title": args["title"], "detail": args.get("detail", "")[:2000]}, {
        "severity": {"type": "choice", "instructions": "Gravidade para o cliente", "criteria": {
            "low": "inconveniente, sem impacto no dia", "medium": "afeta um serviço do dia, há alternativa", "high": "cliente parado, serviço perdido ou pagamento travado", "critical": "segurança, saúde, documento, cliente sem hotel/transfer agora"}},
        "needs_onsite_human": {"type": "noul", "instructions": "Exige presença física de alguém da agência (balcão, hospital, delegacia, entrega)?"}})
    if ans:
        sev = ans.choice("severity", "medium") or "medium"
    due = datetime.now() + {"critical": timedelta(0), "high": timedelta(hours=2), "medium": timedelta(hours=24), "low": timedelta(hours=72)}[sev]
    row = await db.fetchrow(
        """INSERT INTO issues (booking_id, lead_id, kind, severity, title, detail, owner_agent, due_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING id, severity, due_at""",
        args.get("booking_id"), args.get("lead_id"), args["kind"], sev, args["title"], args.get("detail"), args.get("owner_agent") or "booking_payments", due)
    if sev == "critical":
        await bus.publish(bus.ALERTS, {"kind": "issue", "severity": "critical", "text": f"Problema crítico: {args['title']} — {args.get('detail', '')[:300]}"})
    return ok({**row, "needs_onsite_human": bool(ans and ans.noul("needs_onsite_human") >= 0.5)})  # type: ignore[arg-type]


@tool("open_issues", "Problemas abertos (não resolvidos), ordenados por severidade e prazo, com reserva e cliente.", {"status": str})
async def open_issues(args: dict[str, Any]) -> dict[str, Any]:
    rows = await db.fetch(
        """SELECT i.*, b.ref AS booking_ref, l.display_name, l.market_code, l.channel, l.channel_user_id,
                  extract(epoch from (i.due_at - now()))/60 AS minutes_to_due
           FROM issues i LEFT JOIN bookings b ON b.id = i.booking_id LEFT JOIN leads l ON l.id = i.lead_id
           WHERE ($1::text IS NULL AND i.status NOT IN ('resolved','cancelled')) OR i.status = $1
           ORDER BY array_position(ARRAY['critical','high','medium','low'], i.severity), i.due_at""", args.get("status"))
    return ok(rows)


@tool("update_issue", "Atualiza um problema: status (in_progress|waiting_supplier|assigned_human|resolved|cancelled), resolução e se o cliente foi informado.", {"issue_id": str, "status": str, "resolution": str, "client_informed": bool})
async def update_issue(args: dict[str, Any]) -> dict[str, Any]:
    await db.execute(
        """UPDATE issues SET status = COALESCE($2, status), resolution = COALESCE($3, resolution), client_informed = COALESCE($4, client_informed),
           resolved_at = CASE WHEN $2 = 'resolved' THEN now() ELSE resolved_at END WHERE id = $1""",
        args["issue_id"], args.get("status"), args.get("resolution"), args.get("client_informed"))
    return ok({"updated": True})


@tool("assign_issue_to_staff", "Designa um funcionário de resolução (presencial) para um problema: cria o serviço de campo kind=issue_resolution e envia a programação no WhatsApp dele com o briefing. staff_id de config/humans.yaml; vazio = plantão da semana.", {"issue_id": str, "staff_id": str, "service_date": str, "start_time": str, "location": str, "briefing": str})
async def assign_issue_to_staff(args: dict[str, Any]) -> dict[str, Any]:
    staff = _staff()
    person = next((s for s in staff if s.get("id") == args.get("staff_id")), None) or (staff[0] if staff else None)
    if not person:
        return err("nenhum funcionário de resolução em config/humans.yaml")
    wa = os.getenv(person.get("whatsapp_env", ""), "")
    issue = await db.fetchrow("SELECT i.*, b.ref AS booking_ref, l.display_name FROM issues i LEFT JOIN bookings b ON b.id = i.booking_id LEFT JOIN leads l ON l.id = i.lead_id WHERE i.id = $1", args["issue_id"])
    if not issue:
        return err("issue não encontrado")
    d = args.get("service_date") or str(date.today())
    t = args.get("start_time") or datetime.now().strftime("%H:%M")
    row = await db.fetchrow(
        """INSERT INTO field_assignments (booking_id, lead_id, service_date, start_time, kind, pickup, client_name, vip, briefing, staff_id, issue_id, status)
           VALUES ($1,$2,$3::text::date,$4::text::time,'issue_resolution',$5,$6,false,$7,$8,$9,'sent') RETURNING id""",
        issue["booking_id"], issue["lead_id"], d, t, args.get("location"), issue.get("display_name"), args.get("briefing") or issue.get("detail"), person["id"], issue["id"])
    await db.execute("UPDATE issues SET status = 'assigned_human', assigned_human = $2 WHERE id = $1", issue["id"], person["id"])
    text = (f"Resolução — {d} {t}\n• {issue['severity'].upper()} · {issue['title']}\n• Reserva {issue.get('booking_ref') or '-'} · cliente {issue.get('display_name') or '-'}\n"
            f"• Local: {args.get('location') or 'a confirmar'}\n• O que fazer: {args.get('briefing') or issue.get('detail') or ''}\n"
            "Responda OK ao receber; 'resolvido' + 1 linha ao terminar. Qualquer bloqueio, escreva aqui — a máquina acompanha.")
    if wa:
        await bus.publish(bus.OUTBOUND, {"channel": "whatsapp", "channel_user_id": wa.lstrip("+"), "text": text, "field": True})
    return ok({"assignment_id": str(row["id"]), "staff": person.get("name"), "notified": bool(wa)})  # type: ignore[index]


@tool("staff_schedule_for_date", "Programação do pessoal de resolução para uma data (serviços kind=issue_resolution) — para montar e reenviar a agenda do dia junto com a dos motoristas.", {"date": str})
async def staff_schedule_for_date(args: dict[str, Any]) -> dict[str, Any]:
    d = args.get("date") or str(date.today())
    rows = await db.fetch("SELECT f.*, i.title, i.severity, i.status AS issue_status FROM field_assignments f LEFT JOIN issues i ON i.id = f.issue_id WHERE f.kind = 'issue_resolution' AND f.service_date = $1::text::date ORDER BY f.start_time", d)
    return ok({"date": d, "staff": [{k: s.get(k) for k in ("id", "name")} for s in _staff()], "assignments": rows})


# ───────────── Emissões ─────────────

@tool("request_issuance", "Registra pedido de emissão (ticket|voucher|air|insurance|esim|visa) para um item da reserva no provedor da prioridade HCTE (emaar_portal → turning_point/connect_world → elevate → gds). Sem API ligada, devolve o passo manual/e-mail a executar e deixa 'requested'.", {"booking_id": str, "catalog_item_id": str, "kind": str, "provider": str, "pax_count": int, "service_date": str})
async def request_issuance(args: dict[str, Any]) -> dict[str, Any]:
    row = await db.fetchrow(
        """INSERT INTO issuances (booking_id, catalog_item_id, kind, provider, pax_count, service_date) VALUES ($1,$2,$3,$4,$5,$6) RETURNING id""",
        args["booking_id"], args.get("catalog_item_id"), args["kind"], args.get("provider"), args.get("pax_count"), date.fromisoformat(args["service_date"]) if args.get("service_date") else None)
    api_env = {"emaar_portal": "SUPPLIER_EMAAR_USER", "turning_point": "SUPPLIER_TURNINGPOINT_USER", "connect_world": "SUPPLIER_CONNECTWORLD_USER", "elevate": "SUPPLIER_ELEVATE_USER"}.get(args.get("provider") or "")
    automated = bool(api_env and os.getenv(api_env))
    return ok({"issuance_id": str(row["id"]), "status": "requested", "automated": automated,  # type: ignore[index]
               "next_step": "emissão automática na fila" if automated else f"emitir manualmente no portal {args.get('provider') or 'do fornecedor'} e registrar com record_issuance"})


@tool("record_issuance", "Registra resultado da emissão: issued (provider_ref, document_url) | failed (error) | reissued | cancelled. Falha abre issue automaticamente.", {"issuance_id": str, "status": str, "provider_ref": str, "document_url": str, "error": str})
async def record_issuance(args: dict[str, Any]) -> dict[str, Any]:
    row = await db.fetchrow(
        """UPDATE issuances SET status = $2, provider_ref = COALESCE($3, provider_ref), document_url = COALESCE($4, document_url), error = $5,
           issued_at = CASE WHEN $2 IN ('issued','reissued') THEN now() ELSE issued_at END WHERE id = $1 RETURNING booking_id, kind, provider""",
        args["issuance_id"], args["status"], args.get("provider_ref"), args.get("document_url"), args.get("error"))
    if not row:
        return err("emissão não encontrada")
    if args["status"] == "failed":
        await open_issue({"booking_id": str(row["booking_id"]), "kind": "ticket", "title": f"Falha na emissão {row['kind']} ({row['provider']})", "detail": args.get("error") or "", "owner_agent": "booking_payments"})
    return ok({"status": args["status"]})


@tool("pending_issuances", "Emissões em 'requested'/'failed' com data de serviço em ≤ N dias (padrão 7) — o que precisa sair hoje.", {"days_ahead": int})
async def pending_issuances(args: dict[str, Any]) -> dict[str, Any]:
    rows = await db.fetch("""SELECT i.*, b.ref AS booking_ref FROM issuances i JOIN bookings b ON b.id = i.booking_id
                             WHERE i.status IN ('requested','failed') AND (i.service_date IS NULL OR i.service_date <= current_date + $1::int)
                             ORDER BY i.service_date NULLS LAST, i.created_at""", int(args.get("days_ahead") or 7))
    return ok(rows)


@tool("classify_supplier_email", "Jev classifica um e-mail de fornecedor: confirmed|declined|question|price_change|unrelated e se exige ação em 2h.", {"email_text": str})
async def classify_supplier_email(args: dict[str, Any]) -> dict[str, Any]:
    ans = await jev.classify_supplier_reply(args["email_text"])
    if not ans:
        return ok({"status": "unknown", "needs_action_now": None, "note": "Jev indisponível — leia o e-mail e decida"})
    return ok({"status": ans.choice("status"), "needs_action_now": ans.noul("needs_action_now") >= 0.5, "confidence": ans.confidence("status")})


def server():
    return create_sdk_mcp_server(SERVER, "1.0.0", [open_issue, open_issues, update_issue, assign_issue_to_staff, staff_schedule_for_date,
                                                   request_issuance, record_issuance, pending_issuances, classify_supplier_email])
