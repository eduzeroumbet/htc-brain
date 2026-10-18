"""Gestão de parceiras B2B depois que a Prospecção fecha: onboarding, cotação com net rate, reservas da parceira,
extrato mensal de comissão (vira conta a pagar), saúde da parceria (Jev). O prospector abre a porta; aqui a relação rende."""
from __future__ import annotations

from datetime import date
from typing import Any

from brain.core import bus, db, jev
from brain.settings import agency_config
from brain.tools import create_sdk_mcp_server, err, ok, tool

SERVER = "partners"


@tool("active_partners", "Parceiras ativas com termos (comissão, modo de preço, prazo), última reserva, reservas/receita 90 d e health_score.", {"market_code": str})
async def active_partners(args: dict[str, Any]) -> dict[str, Any]:
    rows = await db.fetch("""SELECT p.id, p.name, p.country, p.market_code, p.contact_name, p.contact_email, p.commission_pct, p.pricing_mode, p.payment_terms, p.health_score, p.last_booking_at,
                                    count(b.id) FILTER (WHERE b.created_at > now() - interval '90 days') AS bookings_90d,
                                    coalesce(sum(b.total_usd) FILTER (WHERE b.created_at > now() - interval '90 days'),0) AS revenue_90d
                             FROM partner_agencies p LEFT JOIN bookings b ON b.partner_id = p.id
                             WHERE p.stage = 'partner' AND ($1::text IS NULL OR p.market_code = $1) GROUP BY p.id ORDER BY revenue_90d DESC""", args.get("market_code"))
    return ok(rows)


@tool("onboard_partner", "Define termos da parceira recém-fechada: comissão (≤ padrão sem decisão), modo (commissionable|net), prazo de pagamento, usuário do portal. Gera o checklist de onboarding (kit, contrato via Jurídico, contatos, canal B2B).", {"partner_id": str, "commission_pct": float, "pricing_mode": str, "payment_terms": str, "portal_user": str})
async def onboard_partner(args: dict[str, Any]) -> dict[str, Any]:
    default = float(agency_config().get("finance", {}).get("b2b_commission_default_pct", 10))
    pct = float(args.get("commission_pct") or default)
    if pct > default:
        return err(f"comissão {pct}% acima do padrão {default}% — use request_ceo_decision(kind='partner_terms')")
    await db.execute("""UPDATE partner_agencies SET commission_pct = $2, pricing_mode = coalesce($3,'commissionable'), payment_terms = coalesce($4,'prepaid'), portal_user = $5, stage = 'partner', updated_at = now() WHERE id = $1""",
                     args["partner_id"], pct, args.get("pricing_mode"), args.get("payment_terms"), args.get("portal_user"))
    checklist = ["contrato de parceria → Jurídico (draft_contract kind=partner_agency)", "kit do parceiro (apresentação, tarifário net/comissionável, fotos da frota, política de cancelamento) no idioma",
                 "canal B2B (WhatsApp/Telegram/e-mail) com SLA de cotação 15 min", "primeira cotação-teste em 48 h", "cadastro no portal B2B quando existir", "revisão de 30 dias: reservas, dúvidas, NPS da parceira"]
    return ok({"partner_id": args["partner_id"], "commission_pct": pct, "checklist": checklist})


@tool("partner_quote_context", "Contexto para cotar para uma parceira: termos, modo de preço (net = tirar comissão do sell; commissionable = sell cheio + comissão depois), idioma, reservas anteriores. Depois use quotes.build_quote e marque com tag_quote_partner.", {"partner_id": str})
async def partner_quote_context(args: dict[str, Any]) -> dict[str, Any]:
    p = await db.fetchrow("SELECT id, name, country, market_code, commission_pct, pricing_mode, payment_terms, contact_name, notes FROM partner_agencies WHERE id = $1", args["partner_id"])
    if not p:
        return err("parceira não encontrada")
    recent = await db.fetch("SELECT ref, travel_start, total_usd, status FROM bookings WHERE partner_id = $1 ORDER BY created_at DESC LIMIT 5", args["partner_id"])
    return ok({**p, "recent_bookings": recent, "rule": "net: preço líquido = sell × (1 − comissão); commissionable: preço cheio ao passageiro, comissão paga no extrato mensal"})


@tool("tag_quote_partner", "Marca uma cotação como B2B da parceira (pricing_mode) para a reserva herdar partner_id e calcular comissão no aceite.", {"quote_id": str, "partner_id": str, "pricing_mode": str})
async def tag_quote_partner(args: dict[str, Any]) -> dict[str, Any]:
    await db.execute("UPDATE quotes SET partner_id = $2, pricing_mode = coalesce($3,'commissionable') WHERE id = $1", args["quote_id"], args["partner_id"], args.get("pricing_mode"))
    return ok({"tagged": True})


@tool("sync_partner_bookings", "Propaga partner_id e comissão para reservas criadas a partir de cotações B2B (idempotente) e atualiza last_booking_at.", {})
async def sync_partner_bookings(args: dict[str, Any]) -> dict[str, Any]:
    n = await db.execute("""UPDATE bookings b SET partner_id = q.partner_id,
                              commission_usd = CASE WHEN q.pricing_mode = 'commissionable' THEN round(b.total_usd * coalesce(p.commission_pct,0)/100, 2) ELSE 0 END
                            FROM quotes q JOIN partner_agencies p ON p.id = q.partner_id
                            WHERE b.quote_id = q.id AND q.partner_id IS NOT NULL AND b.partner_id IS NULL""")
    await db.execute("UPDATE partner_agencies p SET last_booking_at = s.m FROM (SELECT partner_id, max(created_at) m FROM bookings WHERE partner_id IS NOT NULL GROUP BY 1) s WHERE s.partner_id = p.id")
    return ok({"updated": n})


@tool("commission_statement", "Gera (ou regenera) o extrato de comissão de uma parceira para um período YYYY-MM com as reservas viajadas e pagas; cria a conta a pagar (payables, category='supplier', description='comissão'). Devolve o texto pronto para envio.", {"partner_id": str, "period": str})
async def commission_statement(args: dict[str, Any]) -> dict[str, Any]:
    period = args.get("period") or date.today().strftime("%Y-%m")
    p = await db.fetchrow("SELECT name, commission_pct, payment_terms, contact_email FROM partner_agencies WHERE id = $1", args["partner_id"])
    if not p:
        return err("parceira não encontrada")
    rows = await db.fetch("""SELECT ref, travel_start, total_usd, coalesce(commission_usd,0) AS commission_usd FROM bookings
                             WHERE partner_id = $1 AND to_char(travel_end, 'YYYY-MM') = $2 AND status IN ('completed','in_trip') AND payment_status = 'paid' ORDER BY travel_start""", args["partner_id"], period)
    total = round(sum(float(r["commission_usd"]) for r in rows), 2)
    if not rows:
        return ok({"period": period, "bookings": [], "total_commission_usd": 0, "note": "nenhuma reserva paga e viajada no período"})
    pay = await db.fetchrow("INSERT INTO payables (category, description, amount_usd, currency, due_at) VALUES ('supplier', $1, $2, 'USD', $3) RETURNING id",
                            f"Comissão {p['name']} {period}", total, date.today().replace(day=1))
    st = await db.fetchrow("""INSERT INTO commission_statements (partner_id, period, bookings, total_commission_usd, payable_id) VALUES ($1,$2,$3,$4,$5)
                              ON CONFLICT (partner_id, period) DO UPDATE SET bookings = EXCLUDED.bookings, total_commission_usd = EXCLUDED.total_commission_usd, payable_id = EXCLUDED.payable_id RETURNING id""",
                           args["partner_id"], period, [dict(r) for r in rows], total, pay["id"])  # type: ignore[index]
    lines = [f"Extrato de comissão — {p['name']} — {period}", f"Comissão: {p['commission_pct']}% · Pagamento: {p['payment_terms']}", ""]
    lines += [f"• {r['ref']} · viagem {r['travel_start']} · USD {float(r['total_usd']):,.2f} → comissão USD {float(r['commission_usd']):,.2f}" for r in rows]
    lines += ["", f"Total: USD {total:,.2f}"]
    return ok({"statement_id": str(st["id"]), "period": period, "total_commission_usd": total, "text": "\n".join(lines), "send_to": p["contact_email"]})  # type: ignore[index]


@tool("partner_health", "Jev avalia a saúde de cada parceira (reservas, última reserva, respostas, reclamações) e grava health_score; devolve as que precisam de atenção (sem reserva em 60 d, queda, reclamação).", {})
async def partner_health(args: dict[str, Any]) -> dict[str, Any]:
    rows = await db.fetch("""SELECT p.id, p.name, p.market_code, p.last_booking_at, p.commission_pct,
                                    count(b.id) FILTER (WHERE b.created_at > now() - interval '90 days') b90,
                                    count(b.id) FILTER (WHERE b.created_at BETWEEN now() - interval '180 days' AND now() - interval '90 days') b_prev,
                                    (SELECT count(*) FROM outreach o WHERE o.partner_id = p.id AND o.direction = 'in' AND o.sent_at > now() - interval '90 days') replies_90d,
                                    (SELECT count(*) FROM issues i JOIN bookings bb ON bb.id = i.booking_id WHERE bb.partner_id = p.id AND i.opened_at > now() - interval '90 days') issues_90d
                             FROM partner_agencies p LEFT JOIN bookings b ON b.partner_id = p.id WHERE p.stage = 'partner' GROUP BY p.id""")
    attention = []
    for r in rows:
        ans = await jev.decide({k: (str(v) if k == "last_booking_at" else v) for k, v in r.items() if k not in ("id", "name")}, {
            "health": {"type": "score", "instructions": "Saúde da parceria B2B", "criteria": ["em risco", "fraca", "saudável", "excelente"]},
            "needs_attention": {"type": "noul", "instructions": "Precisa de ação do gestor esta semana (reativar, visitar, resolver problema)?"}})
        if ans:
            r["health_score"] = round(ans.score("health"), 3)
            await db.execute("UPDATE partner_agencies SET health_score = $2 WHERE id = $1", r["id"], r["health_score"])
            if ans.noul("needs_attention") >= 0.5:
                attention.append(r)
    return ok({"partners": rows, "attention": attention})


@tool("message_partner", "Envia mensagem à parceira pelo e-mail cadastrado (ou WhatsApp quando houver) e registra em outreach. Máx. 2 por semana por parceira fora de cotações.", {"partner_id": str, "subject": str, "body": str, "channel": str})
async def message_partner(args: dict[str, Any]) -> dict[str, Any]:
    p = await db.fetchrow("SELECT contact_email, contact_phone, name FROM partner_agencies WHERE id = $1", args["partner_id"])
    if not p:
        return err("parceira não encontrada")
    if not await bus.rate_limit(f"partner_msg:{args['partner_id']}", limit=2, window_s=7 * 24 * 3600):
        return ok({"sent": False, "reason": "limite semanal de mensagens não comerciais"})
    ch = args.get("channel") or ("whatsapp" if p["contact_phone"] else "email")
    to = p["contact_phone"].lstrip("+") if ch == "whatsapp" and p["contact_phone"] else p["contact_email"]
    if not to:
        return err("parceira sem contato")
    await bus.publish(bus.OUTBOUND, {"channel": ch, "channel_user_id": to, "subject": args.get("subject") or "", "text": args["body"], "author": "ai:partner_manager"})
    await db.execute("INSERT INTO outreach (partner_id, direction, channel, subject, body) VALUES ($1,'out',$2,$3,$4)", args["partner_id"], ch, args.get("subject"), args["body"])
    return ok({"sent": True, "channel": ch})


def server():
    return create_sdk_mcp_server(SERVER, "1.0.0", [active_partners, onboard_partner, partner_quote_context, tag_quote_partner, sync_partner_bookings, commission_statement, partner_health, message_partner])
