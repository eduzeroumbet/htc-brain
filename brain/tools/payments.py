"""Pagamentos: links de pagamento (Stripe/Tap), registro de pagamentos e reembolsos dentro da política.
Nenhum dado de cartão passa por aqui."""
from __future__ import annotations

from typing import Any

import httpx

from brain.core import db
from brain.settings import agency_config, get_settings, market
from brain.tools import create_sdk_mcp_server, err, ok, tool

SERVER = "payments"


async def _stripe_payment_link(amount_cents: int, currency: str, description: str, booking_ref: str) -> str:
    s = get_settings()
    async with httpx.AsyncClient(timeout=20, auth=(s.stripe_secret_key, "")) as c:
        price = await c.post("https://api.stripe.com/v1/prices", data={
            "unit_amount": amount_cents, "currency": currency.lower(), "product_data[name]": description[:250]})
        price.raise_for_status()
        link = await c.post("https://api.stripe.com/v1/payment_links", data={
            "line_items[0][price]": price.json()["id"], "line_items[0][quantity]": 1,
            "metadata[booking_ref]": booking_ref})
        link.raise_for_status()
        return link.json()["url"]


async def _tap_charge_link(amount: float, currency: str, description: str, booking_ref: str) -> str:
    s = get_settings()
    async with httpx.AsyncClient(timeout=20, headers={"Authorization": f"Bearer {s.tap_secret_key}"}) as c:
        r = await c.post("https://api.tap.company/v2/charges", json={
            "amount": amount, "currency": currency, "description": description,
            "reference": {"order": booking_ref}, "source": {"id": "src_all"},
            "redirect": {"url": f"https://{s.domain}/pay/return"}})
        r.raise_for_status()
        return r.json()["transaction"]["url"]


@tool("create_payment_link", "Cria link de pagamento para a reserva (depósito ou total). Escolhe o gateway pelo mercado (Tap para GCC, Stripe para o resto). Retorna URL. Nunca peça dados de cartão no chat.", {"booking_id": str, "amount_usd": float, "kind": str})
async def create_payment_link(args: dict[str, Any]) -> dict[str, Any]:
    b = await db.fetchrow("SELECT b.*, l.display_name FROM bookings b JOIN leads l ON l.id = b.lead_id WHERE b.id = $1", args["booking_id"])
    if not b:
        return err("reserva não encontrada")
    mk = market(b["market_code"])
    gateway = (mk.get("payments") or {}).get("gateway", "stripe")
    amount_usd = float(args.get("amount_usd") or b["total_usd"])
    desc = f"{agency_config()['agency']['name']} · {b['ref']} · {args.get('kind') or 'pagamento'}"
    try:
        if gateway == "tap":
            from brain.tools.quotes import fx
            rate = await fx(mk["currency"])
            url = await _tap_charge_link(round(amount_usd * rate, 2), mk["currency"], desc, b["ref"])
        else:
            url = await _stripe_payment_link(int(round(amount_usd * 100)), "USD", desc, b["ref"])
    except Exception as exc:  # noqa: BLE001
        return err(f"gateway indisponível: {exc}")
    await db.execute(
        "INSERT INTO payments (booking_id, gateway, amount_usd, currency, kind, status) VALUES ($1,$2,$3,'USD','charge','link_sent')",
        b["id"], gateway, amount_usd,
    )
    return ok({"url": url, "gateway": gateway, "amount_usd": amount_usd})


@tool("payment_status", "Situação de pagamento da reserva.", {"booking_id": str})
async def payment_status(args: dict[str, Any]) -> dict[str, Any]:
    b = await db.fetchrow("SELECT ref, total_usd, paid_usd, payment_status, status FROM bookings WHERE id = $1", args["booking_id"])
    pays = await db.fetch("SELECT gateway, amount_usd, kind, status, created_at FROM payments WHERE booking_id = $1 ORDER BY created_at", args["booking_id"])
    return ok({"booking": b, "payments": pays})


@tool("request_refund", "Solicita reembolso. Dentro da política e até o limite autônomo executa; acima disso cria decisão para o CEO e responde 'pending_ceo'.", {"booking_id": str, "amount_usd": float, "reason": str})
async def request_refund(args: dict[str, Any]) -> dict[str, Any]:
    autonomy = agency_config()["autonomy"]
    amount = float(args["amount_usd"])
    b = await db.fetchrow("SELECT ref, market_code, paid_usd FROM bookings WHERE id = $1", args["booking_id"])
    if not b:
        return err("reserva não encontrada")
    if amount > float(b["paid_usd"] or 0):
        return err("valor acima do pago")
    if amount > float(autonomy["refund_usd_autonomous"]):
        await db.execute(
            """INSERT INTO decisions (kind, context, recommendation, requested_by, amount_usd, market_code)
               VALUES ('refund', $1, $2, 'ai:booking_payments', $3, $4)""",
            f"Reembolso de USD {amount:.2f} na reserva {b['ref']}: {args.get('reason','')}", "Avaliar política e histórico do cliente",
            amount, b["market_code"],
        )
        return ok({"status": "pending_ceo", "amount_usd": amount})
    await db.execute(
        "INSERT INTO payments (booking_id, gateway, amount_usd, currency, kind, status) VALUES ($1,'stripe',$2,'USD','refund','requested')",
        args["booking_id"], amount,
    )
    await db.execute("UPDATE bookings SET payment_status = 'partial_refund' WHERE id = $1", args["booking_id"])
    return ok({"status": "requested", "amount_usd": amount})


def server():
    return create_sdk_mcp_server(SERVER, "1.0.0", [create_payment_link, payment_status, request_refund])
