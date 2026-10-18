"""Cotações: monta, aplica desconto dentro da autonomia, gera PDF, registra."""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

import httpx

from brain.core import db
from brain.settings import agency_config, get_settings, market
from brain.tools import create_sdk_mcp_server, err, ok, tool

SERVER = "quotes"

FX_FALLBACK = {"USD": 1.0, "AED": 3.6725, "BRL": 5.4, "INR": 84.0, "SAR": 3.75, "GBP": 0.78, "EUR": 0.92, "RUB": 95.0}


async def fx(currency: str) -> float:
    """Taxa USD→moeda. Tenta uma API pública; cai no fallback estático."""
    if currency == "USD":
        return 1.0
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get("https://open.er-api.com/v6/latest/USD")
            return float(r.json()["rates"][currency])
    except Exception:  # noqa: BLE001
        return FX_FALLBACK.get(currency, 1.0)


@tool("build_quote", "Cria uma cotação a partir de itens do catálogo. items = [{catalog_item_id, qty, date}]. discount_pct até o limite autônomo; acima disso a cotação fica 'draft' aguardando aprovação. Retorna totais em USD e na moeda do mercado, margem e id.", {"lead_id": str, "market_code": str, "title": str, "items": list, "discount_pct": float})
async def build_quote(args: dict[str, Any]) -> dict[str, Any]:
    items_in = args.get("items") or []
    if not items_in:
        return err("cotação sem itens")
    ids = [i["catalog_item_id"] for i in items_in]
    rows = await db.fetch("SELECT id, name, sell_price_usd, net_price_usd, seasonality, price_basis FROM catalog_items WHERE id = ANY($1::uuid[]) AND active", ids)
    by_id = {str(r["id"]): r for r in rows}
    if len(by_id) != len(set(ids)):
        return err("um ou mais itens não existem no catálogo ativo — nunca invente preço")

    lines, subtotal, net_total = [], 0.0, 0.0
    for it in items_in:
        r = by_id[str(it["catalog_item_id"])]
        qty = int(it.get("qty") or 1)
        mult = 1.0
        for rng, m in (r["seasonality"] or {}).items():
            a, b = rng.split("/")
            if it.get("date") and a <= it["date"] <= b:
                mult = float(m)
        unit_sell = round(float(r["sell_price_usd"]) * mult, 2)
        unit_net = round(float(r["net_price_usd"]) * mult, 2)
        subtotal += unit_sell * qty
        net_total += unit_net * qty
        lines.append({"catalog_item_id": str(r["id"]), "name": r["name"], "qty": qty, "date": it.get("date"),
                      "unit_sell_usd": unit_sell, "unit_net_usd": unit_net, "price_basis": r["price_basis"]})

    disc = float(args.get("discount_pct") or 0)
    autonomy = agency_config()["autonomy"]
    status, approved_by = "sent", "ai"
    if disc > float(autonomy["discount_max_pct_ceo_agent"]):
        status, approved_by = "draft", None
    elif disc > float(autonomy["discount_max_pct_autonomous"]):
        status, approved_by = "draft", None  # CEO-agente decide por regra (margem > 12%)

    total = round(subtotal * (1 - disc / 100), 2)
    margin = round(total - net_total, 2)
    margin_pct = round(margin / total * 100, 2) if total else 0.0
    mk = market(args["market_code"])
    cur = mk["currency"]
    rate = await fx(cur)
    total_local = round(total * rate, 2)
    valid_until = date.today() + timedelta(days=7)

    row = await db.fetchrow(
        """INSERT INTO quotes (lead_id, market_code, title, items, subtotal_usd, discount_pct, total_usd, total_local, local_currency,
                               margin_usd, margin_pct, valid_until, status, approved_by)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14) RETURNING id""",
        args["lead_id"], args["market_code"], args.get("title") or "Sua viagem a Dubai", lines, round(subtotal, 2), disc,
        total, total_local, cur, margin, margin_pct, valid_until, status, approved_by,
    )
    quote_id = str(row["id"])  # type: ignore[index]
    if status == "draft":
        await db.execute(
            """INSERT INTO decisions (kind, context, recommendation, requested_by, amount_usd, market_code)
               VALUES ('discount', $1, $2, 'ai:consultant', $3, $4)""",
            f"Cotação {quote_id} com desconto de {disc}% (margem {margin_pct}%)",
            "Aprovar se margem >= 12% e lead com datas confirmadas", total, args["market_code"],
        )
    await db.execute("UPDATE leads SET stage = 'quoted' WHERE id = $1 AND stage IN ('new','qualifying','qualified')", args["lead_id"])
    return ok({"quote_id": quote_id, "status": status, "lines": lines, "subtotal_usd": round(subtotal, 2), "discount_pct": disc,
               "total_usd": total, "total_local": total_local, "currency": cur, "fx_rate": rate, "margin_pct": margin_pct,
               "valid_until": str(valid_until),
               "note": None if status == "sent" else "Desconto acima do limite autônomo: aguarde aprovação antes de enviar o valor."})


@tool("render_quote_pdf", "Gera o PDF da cotação (idioma do mercado, licença DET, política de cancelamento, preço total) e devolve a URL.", {"quote_id": str})
async def render_quote_pdf(args: dict[str, Any]) -> dict[str, Any]:
    q = await db.fetchrow("SELECT q.*, l.display_name FROM quotes q JOIN leads l ON l.id = q.lead_id WHERE q.id = $1", args["quote_id"])
    if not q:
        return err("cotação não encontrada")
    if q["status"] == "draft":
        return err("cotação aguardando aprovação de desconto")
    from brain.tools.pdf import render_quote  # import tardio (weasyprint)
    url = await render_quote(q)
    await db.execute("UPDATE quotes SET pdf_url = $2, pdf_rendered_at = now() WHERE id = $1", args["quote_id"], url)
    return ok({"pdf_url": url})


@tool("accept_quote", "Marca a cotação como aceita e cria a reserva em 'confirming'. Retorna booking ref.", {"quote_id": str})
async def accept_quote(args: dict[str, Any]) -> dict[str, Any]:
    q = await db.fetchrow("SELECT * FROM quotes WHERE id = $1", args["quote_id"])
    if not q or q["status"] not in ("sent", "accepted"):
        return err("cotação inválida para aceite")
    dates = [i["date"] for i in q["items"] if i.get("date")]
    start, end = (min(dates), max(dates)) if dates else (None, None)
    ref = f"DXB-{date.today().year}-{uuid.uuid4().hex[:6].upper()}"
    net = sum(float(i["unit_net_usd"]) * int(i["qty"]) for i in q["items"])
    autonomy = agency_config()["autonomy"]
    row = await db.fetchrow(
        """INSERT INTO bookings (ref, lead_id, quote_id, market_code, travel_start, travel_end, items, total_usd, net_cost_usd, margin_usd, pii_purge_after)
           VALUES ($1,$2,$3,$4,$5::text::date,$6::text::date,$7,$8,$9,$10, ($6::text::date + $11::int)) RETURNING id, ref""",
        ref, q["lead_id"], q["id"], q["market_code"], start, end, q["items"], q["total_usd"], round(net, 2),
        round(float(q["total_usd"]) - net, 2), get_settings().pii_retention_days_after_trip,
    )
    await db.execute("UPDATE quotes SET status = 'accepted', accepted_at = now() WHERE id = $1", q["id"])
    await db.execute("UPDATE leads SET stage = 'won' WHERE id = $1", q["lead_id"])
    needs_ceo = float(q["total_usd"]) >= float(autonomy["booking_value_usd_requires_ceo"])
    if needs_ceo:
        await db.execute(
            """INSERT INTO decisions (kind, context, recommendation, requested_by, amount_usd, market_code)
               VALUES ('booking_high_value', $1, 'Revisar itens e fornecedor antes de confirmar', 'ai:consultant', $2, $3)""",
            f"Reserva {ref} acima do limite", q["total_usd"], q["market_code"],
        )
    return ok({"booking_id": str(row["id"]), "ref": row["ref"], "requires_ceo_review": needs_ceo})  # type: ignore[index]


def server():
    return create_sdk_mcp_server(SERVER, "1.0.0", [build_quote, render_quote_pdf, accept_quote])
