"""Catálogo: a ÚNICA fonte de preço e disponibilidade que um agente pode citar."""
from __future__ import annotations

from typing import Any

from brain.core import db
from brain.tools import create_sdk_mcp_server, ok, tool

SERVER = "catalog"


@tool("search_catalog", "Busca produtos ativos por tipo (hotel, experience, transfer, package, visa, insurance, esim), texto, adequação (family, honeymoon, luxury, budget, halal, vegetarian) e mercado. Preços já com markup em USD.", {"kind": str, "query": str, "suitable_for": str, "market_code": str, "max_price_usd": float, "limit": int})
async def search_catalog(args: dict[str, Any]) -> dict[str, Any]:
    conds, params = ["c.active"], []
    if args.get("kind"):
        params.append(args["kind"]); conds.append(f"c.kind = ${len(params)}")
    if args.get("query"):
        params.append(f"%{args['query']}%"); conds.append(f"(c.name ILIKE ${len(params)} OR c.location ILIKE ${len(params)})")
    if args.get("suitable_for"):
        params.append(args["suitable_for"]); conds.append(f"${len(params)} = ANY(c.suitable_for)")
    if args.get("market_code"):
        params.append(args["market_code"]); conds.append(f"(c.markets = '{{}}' OR ${len(params)} = ANY(c.markets))")
    if args.get("max_price_usd"):
        params.append(float(args["max_price_usd"])); conds.append(f"c.sell_price_usd <= ${len(params)}")
    params.append(int(args.get("limit") or 12))
    rows = await db.fetch(
        f"""SELECT c.id, c.sku, c.kind, c.name, c.description, c.location, c.duration_hours, c.nights, c.star_rating,
                   c.sell_price_usd, c.price_basis, c.seasonality, c.availability_note, c.suitable_for, c.cancellation_hours,
                   s.name AS supplier, s.det_license
            FROM catalog_items c LEFT JOIN suppliers s ON s.id = c.supplier_id
            WHERE {' AND '.join(conds)} ORDER BY c.kind, c.sell_price_usd LIMIT ${len(params)}""",
        *params,
    )
    return ok(rows)


@tool("get_item", "Detalhe completo de um item do catálogo pelo id ou sku.", {"id": str, "sku": str})
async def get_item(args: dict[str, Any]) -> dict[str, Any]:
    if args.get("id"):
        row = await db.fetchrow("SELECT * FROM catalog_items WHERE id = $1", args["id"])
    else:
        row = await db.fetchrow("SELECT * FROM catalog_items WHERE sku = $1", args.get("sku"))
    return ok(row or {"found": False})


@tool("seasonal_price", "Preço de venda de um item para uma data (aplica multiplicadores de temporada). Retorna USD.", {"id": str, "date": str})
async def seasonal_price(args: dict[str, Any]) -> dict[str, Any]:
    row = await db.fetchrow("SELECT sell_price_usd, seasonality FROM catalog_items WHERE id = $1", args["id"])
    if not row:
        return ok({"found": False})
    price = float(row["sell_price_usd"])
    mult = 1.0
    for rng, m in (row["seasonality"] or {}).items():
        a, b = rng.split("/")
        if a <= args["date"] <= b:
            mult = float(m)
    return ok({"date": args["date"], "price_usd": round(price * mult, 2), "multiplier": mult})


@tool("low_occupancy_hotels", "Hotéis marcados pelo agente de Fornecedores como ocupação baixa (< 60%) esta semana — candidatos a upgrade grátis.", {"limit": int})
async def low_occupancy_hotels(args: dict[str, Any]) -> dict[str, Any]:
    rows = await db.fetch(
        """SELECT id, name, star_rating, location, sell_price_usd, availability_note FROM catalog_items
           WHERE active AND kind = 'hotel' AND availability_note ILIKE '%low_occupancy%' LIMIT $1""",
        int(args.get("limit") or 10),
    )
    return ok(rows)


def server():
    return create_sdk_mcp_server(SERVER, "1.0.0", [search_catalog, get_item, seasonal_price, low_occupancy_hotels])
