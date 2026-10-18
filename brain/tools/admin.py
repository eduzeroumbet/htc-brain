"""Administração sem equipe: calendário de renovações e inventário (presentes, abayas, uniformes)."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import yaml

from brain.core import bus, db
from brain.settings import CONFIG_DIR
from brain.tools import create_sdk_mcp_server, err, ok, tool

SERVER = "admin"


@tool("sync_renewals_from_config", "Carrega/atualiza a tabela renewals a partir de config/renewals_hcte.yaml (não apaga status já renovado).", {})
async def sync_renewals_from_config(args: dict[str, Any]) -> dict[str, Any]:
    cfg = yaml.safe_load((CONFIG_DIR / "renewals_hcte.yaml").read_text(encoding="utf-8"))
    n = 0
    for it in cfg["items"]:
        due = it["due"] if isinstance(it["due"], str) and it["due"][:4].isdigit() and len(it["due"]) == 10 else None
        await db.execute(
            """INSERT INTO renewals (id, name, due, recurrence, owner, action, note)
               VALUES ($1,$2,$3::text::date,$4,$5,$6,$7)
               ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, recurrence = EXCLUDED.recurrence, owner = EXCLUDED.owner, action = EXCLUDED.action,
                 due = coalesce(renewals.due, EXCLUDED.due), note = coalesce(EXCLUDED.note, renewals.note)""",
            it["id"], it["name"], due, str(it.get("recurrence")), it.get("owner"), it.get("action"), it.get("note"),
        )
        n += 1
    return ok({"synced": n})


@tool("upcoming_renewals", "Renovações que vencem nos próximos N dias (padrão 90) ou já vencidas, com dias restantes.", {"days": int})
async def upcoming_renewals(args: dict[str, Any]) -> dict[str, Any]:
    rows = await db.fetch(
        """SELECT id, name, due, recurrence, owner, action, status, note, (due - current_date) AS days_left
           FROM renewals WHERE status <> 'cancelled' AND due IS NOT NULL AND due <= current_date + $1::int ORDER BY due""",
        int(args.get("days") or 90),
    )
    return ok(rows)


@tool("set_renewal_status", "Marca renovação como quoted|renewed|cancelled e, se renovada com recorrência anual, empurra a data 1 ano.", {"id": str, "status": str, "new_due": str, "note": str})
async def set_renewal_status(args: dict[str, Any]) -> dict[str, Any]:
    r = await db.fetchrow("SELECT * FROM renewals WHERE id = $1", args["id"])
    if not r:
        return err("renovação não encontrada")
    new_due = args.get("new_due")
    if args["status"] == "renewed" and not new_due and r["due"] and r["recurrence"] == "yearly":
        new_due = str(r["due"] + timedelta(days=365))
    await db.execute("UPDATE renewals SET status = $2, note = coalesce($3, note), renewed_at = CASE WHEN $2 = 'renewed' THEN current_date ELSE renewed_at END, due = coalesce($4::text::date, due) WHERE id = $1",
                     args["id"], args["status"], args.get("note"), new_due)
    if args["status"] == "renewed" and new_due:
        await db.execute("UPDATE renewals SET status = 'pending' WHERE id = $1", args["id"])
    return ok({"id": args["id"], "status": args["status"], "due": new_due or str(r["due"])})


@tool("inventory_levels", "Estoque por categoria (gifts_adult, gifts_kids, gifts_vip, packaging, abaya, uniform, office) e itens abaixo do mínimo.", {"category": str})
async def inventory_levels(args: dict[str, Any]) -> dict[str, Any]:
    rows = await db.fetch("SELECT * FROM inventory WHERE ($1::text IS NULL OR category = $1) ORDER BY category, item", args.get("category"))
    low = [r for r in rows if int(r["qty"]) < int(r["min_qty"] or 0)]
    return ok({"items": rows, "below_minimum": low})


@tool("inventory_move", "Movimenta estoque: qty_delta negativo = saída (presente para reserva, abaya para guia), positivo = entrada/compra.", {"inventory_id": str, "qty_delta": int, "reason": str, "booking_id": str, "new_location": str})
async def inventory_move(args: dict[str, Any]) -> dict[str, Any]:
    await db.execute("INSERT INTO inventory_moves (inventory_id, qty_delta, reason, booking_id) VALUES ($1,$2,$3,$4)",
                     args["inventory_id"], int(args["qty_delta"]), args.get("reason"), args.get("booking_id"))
    await db.execute("UPDATE inventory SET qty = qty + $2, location = coalesce($3, location), updated_at = now() WHERE id = $1",
                     args["inventory_id"], int(args["qty_delta"]), args.get("new_location"))
    return ok({"moved": True})


@tool("gift_plan_for_booking", "Sugere presentes por perfil dos passageiros (adulto/teen/criança/VIP) e abaya se houver mesquita, com base no estoque.", {"booking_id": str})
async def gift_plan_for_booking(args: dict[str, Any]) -> dict[str, Any]:
    b = await db.fetchrow("SELECT b.items, b.pax, l.score, l.pax_adults, l.pax_children FROM bookings b JOIN leads l ON l.id = b.lead_id WHERE b.id = $1", args["booking_id"])
    if not b:
        return err("reserva não encontrada")
    vip = int(b["score"] or 0) >= 90
    needs_abaya = any("mosque" in (i.get("name") or "").lower() or "mesquita" in (i.get("name") or "").lower() for i in (b["items"] or []))
    plan = {"adults": int(b["pax_adults"] or 1), "children": int(b["pax_children"] or 0), "vip": vip, "abaya": needs_abaya,
            "gift_categories": (["gifts_vip"] if vip else ["gifts_adult"]) + (["gifts_kids"] if int(b["pax_children"] or 0) else [])}
    stock = await db.fetch("SELECT id, category, item, qty FROM inventory WHERE category = ANY($1::text[]) AND qty > 0 ORDER BY category, qty DESC", plan["gift_categories"] + (["abaya"] if needs_abaya else []))
    return ok({"plan": plan, "available": stock})


@tool("request_quotes_by_email", "Gera e-mails de pedido de cotação (renovação de seguro, contrato, serviço) para até 3 fornecedores e os envia pelo canal de e-mail.", {"subject": str, "body": str, "recipients": list})
async def request_quotes_by_email(args: dict[str, Any]) -> dict[str, Any]:
    n = 0
    for to in (args.get("recipients") or [])[:3]:
        await bus.publish(bus.OUTBOUND, {"channel": "email", "channel_user_id": to, "subject": args["subject"], "text": args["body"]})
        n += 1
    return ok({"sent": n})


def server():
    return create_sdk_mcp_server(SERVER, "1.0.0", [
        sync_renewals_from_config, upcoming_renewals, set_renewal_status, inventory_levels, inventory_move, gift_plan_for_booking, request_quotes_by_email,
    ])
