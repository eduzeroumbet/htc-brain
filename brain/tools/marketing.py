"""Marketing: conteúdo (fila de compliance, agendamento) e mídia paga (métricas, orçamento, pausa).

As chamadas às plataformas ficam em `_platform_*`; estão como stubs com o endpoint documentado para o
Edu ligar credenciais. O restante (banco, regras de teto, decisões) já funciona.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from brain.core import db
from brain.settings import budgets_config
from brain.tools import create_sdk_mcp_server, err, ok, tool

SERVER = "marketing"


# ───────────────────────── conteúdo ─────────────────────────

@tool("save_content", "Salva uma peça de conteúdo em 'compliance_review'. format: post|reel_script|blog|email|landing|ad_creative. scheduled_for em ISO (fuso do mercado).", {"market_code": str, "pillar": str, "format": str, "channel": str, "language": str, "title": str, "body": str, "scheduled_for": str})
async def save_content(args: dict[str, Any]) -> dict[str, Any]:
    row = await db.fetchrow(
        """INSERT INTO content_items (market_code, pillar, format, channel, language, title, body, scheduled_for, status)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8::text::timestamptz,'compliance_review') RETURNING id""",
        args["market_code"], args.get("pillar"), args["format"], args.get("channel"), args.get("language"),
        args.get("title"), args["body"], args.get("scheduled_for"),
    )
    return ok({"content_id": str(row["id"]), "status": "compliance_review"})  # type: ignore[index]


@tool("pending_compliance", "Lista peças aguardando revisão de compliance.", {"market_code": str, "limit": int})
async def pending_compliance(args: dict[str, Any]) -> dict[str, Any]:
    rows = await db.fetch(
        """SELECT id, market_code, pillar, format, channel, language, title, body, scheduled_for FROM content_items
           WHERE status = 'compliance_review' AND ($1::text IS NULL OR market_code = $1) ORDER BY scheduled_for NULLS LAST LIMIT $2""",
        args.get("market_code"), int(args.get("limit") or 20),
    )
    return ok(rows)


@tool("review_content", "Decisão de compliance: approve|reject, com notas. Aprovado vai para 'scheduled'.", {"content_id": str, "decision": str, "notes": str, "revised_body": str})
async def review_content(args: dict[str, Any]) -> dict[str, Any]:
    status = "scheduled" if args["decision"] == "approve" else "rejected"
    await db.execute(
        "UPDATE content_items SET status = $2, compliance_notes = $3, body = coalesce($4, body) WHERE id = $1",
        args["content_id"], status, args.get("notes"), args.get("revised_body"),
    )
    return ok({"content_id": args["content_id"], "status": status})


@tool("due_for_publishing", "Peças aprovadas cujo horário chegou.", {"limit": int})
async def due_for_publishing(args: dict[str, Any]) -> dict[str, Any]:
    rows = await db.fetch(
        "SELECT * FROM content_items WHERE status = 'scheduled' AND scheduled_for <= now() ORDER BY scheduled_for LIMIT $1",
        int(args.get("limit") or 20),
    )
    return ok(rows)


@tool("mark_published", "Marca a peça como publicada com o id externo.", {"content_id": str, "external_id": str})
async def mark_published(args: dict[str, Any]) -> dict[str, Any]:
    await db.execute("UPDATE content_items SET status = 'published', published_at = now(), external_id = $2 WHERE id = $1",
                     args["content_id"], args.get("external_id"))
    return ok({"published": True})


@tool("top_performing_content", "Conteúdo com melhor engajamento nos últimos N dias por mercado (para virar criativo de anúncio).", {"market_code": str, "days": int, "limit": int})
async def top_performing_content(args: dict[str, Any]) -> dict[str, Any]:
    rows = await db.fetch(
        """SELECT id, format, channel, title, body, metrics FROM content_items
           WHERE market_code = $1 AND status = 'published' AND published_at > now() - ($2::int || ' days')::interval
           ORDER BY coalesce((metrics->>'leads')::int,0) DESC, coalesce((metrics->>'saves')::int,0) DESC LIMIT $3""",
        args["market_code"], int(args.get("days") or 14), int(args.get("limit") or 5),
    )
    return ok(rows)


# ───────────────────────── mídia paga ─────────────────────────

@tool("campaign_performance", "Métricas por campanha nos últimos N dias: gasto, leads, CPL, reservas, CAC, ROAS. Inclui metas de config/budgets.yaml.", {"days": int, "market_code": str})
async def campaign_performance(args: dict[str, Any]) -> dict[str, Any]:
    days = int(args.get("days") or 7)
    rows = await db.fetch(
        """SELECT c.id, c.name, c.platform, c.market_code, c.daily_budget_usd, c.status,
                  coalesce(sum(a.spend_usd),0) AS spend_usd, coalesce(sum(a.leads),0) AS leads, coalesce(sum(a.bookings),0) AS bookings,
                  coalesce(sum(a.revenue_usd),0) AS revenue_usd
           FROM campaigns c LEFT JOIN ad_spend_daily a ON a.campaign_id = c.id AND a.day > current_date - $1::int
           WHERE ($2::text IS NULL OR c.market_code = $2) AND c.status <> 'ended'
           GROUP BY c.id ORDER BY c.market_code, spend_usd DESC""",
        days, args.get("market_code"),
    )
    targets = budgets_config()["media"]["targets_usd"]
    for r in rows:
        spend, leads, bookings = float(r["spend_usd"]), int(r["leads"]), int(r["bookings"])
        r["cpl_usd"] = round(spend / leads, 2) if leads else None
        r["cac_usd"] = round(spend / bookings, 2) if bookings else None
        r["roas"] = round(float(r["revenue_usd"]) / spend, 2) if spend else None
        r["cpl_target"] = targets["cpl"].get(r["market_code"])
        r["cac_target"] = targets["cac"].get(r["market_code"])
    return ok(rows)


@tool("spend_today", "Gasto total de mídia hoje vs teto diário.", {})
async def spend_today(args: dict[str, Any]) -> dict[str, Any]:
    row = await db.fetchrow("SELECT coalesce(sum(spend_usd),0) AS s FROM ad_spend_daily WHERE day = current_date")
    cap = budgets_config()["media"]["daily_cap_usd"]
    return ok({"spent_usd": float(row["s"]), "daily_cap_usd": cap, "remaining_usd": round(cap - float(row["s"]), 2)})  # type: ignore[index]


@tool("set_campaign_budget", "Ajusta o orçamento diário de uma campanha. Respeita o teto diário total; acima disso, recusa e sugere decisão do CEO.", {"campaign_id": str, "daily_budget_usd": float, "reason": str})
async def set_campaign_budget(args: dict[str, Any]) -> dict[str, Any]:
    cap = float(budgets_config()["media"]["daily_cap_usd"])
    row = await db.fetchrow("SELECT coalesce(sum(daily_budget_usd),0) AS total FROM campaigns WHERE status = 'active' AND id <> $1", args["campaign_id"])
    new_total = float(row["total"]) + float(args["daily_budget_usd"])  # type: ignore[index]
    if new_total > cap:
        return err(f"teto diário (USD {cap}) seria excedido: total ficaria USD {new_total:.2f}. Use request_ceo_decision.")
    c = await db.fetchrow("UPDATE campaigns SET daily_budget_usd = $2 WHERE id = $1 RETURNING platform, external_id", args["campaign_id"], float(args["daily_budget_usd"]))
    if c:
        await _platform_set_budget(c["platform"], c["external_id"], float(args["daily_budget_usd"]))
    return ok({"campaign_id": args["campaign_id"], "daily_budget_usd": float(args["daily_budget_usd"]), "reason": args.get("reason")})


@tool("pause_campaign", "Pausa (ou reativa) uma campanha.", {"campaign_id": str, "paused": bool, "reason": str})
async def pause_campaign(args: dict[str, Any]) -> dict[str, Any]:
    status = "paused" if args.get("paused", True) else "active"
    c = await db.fetchrow("UPDATE campaigns SET status = $2 WHERE id = $1 RETURNING platform, external_id", args["campaign_id"], status)
    if c:
        await _platform_set_status(c["platform"], c["external_id"], status)
    return ok({"campaign_id": args["campaign_id"], "status": status})


@tool("record_spend", "Registra (ou atualiza) o gasto/resultados do dia de uma campanha — usado ao sincronizar com as plataformas.", {"campaign_id": str, "day": str, "spend_usd": float, "impressions": int, "clicks": int, "leads": int, "bookings": int, "revenue_usd": float})
async def record_spend(args: dict[str, Any]) -> dict[str, Any]:
    c = await db.fetchrow("SELECT market_code, platform FROM campaigns WHERE id = $1", args["campaign_id"])
    if not c:
        return err("campanha não encontrada")
    await db.execute(
        """INSERT INTO ad_spend_daily (day, campaign_id, market_code, platform, spend_usd, impressions, clicks, leads, bookings, revenue_usd)
           VALUES ($1::text::date,$2,$3,$4,$5,$6,$7,$8,$9,$10)
           ON CONFLICT (day, campaign_id) DO UPDATE SET spend_usd = EXCLUDED.spend_usd, impressions = EXCLUDED.impressions,
             clicks = EXCLUDED.clicks, leads = EXCLUDED.leads, bookings = EXCLUDED.bookings, revenue_usd = EXCLUDED.revenue_usd""",
        args.get("day") or str(date.today()), args["campaign_id"], c["market_code"], c["platform"], float(args.get("spend_usd") or 0),
        int(args.get("impressions") or 0), int(args.get("clicks") or 0), int(args.get("leads") or 0), int(args.get("bookings") or 0),
        float(args.get("revenue_usd") or 0),
    )
    return ok({"recorded": True})


# ───────────────────────── stubs de plataforma ─────────────────────────
# TODO(Edu): ligar as APIs. Documentação:
#   Meta Marketing API — POST /{campaign_id} {daily_budget, status}
#   Google Ads API     — CampaignBudgetService.MutateCampaignBudgets / CampaignService (status)
#   TikTok Ads         — /campaign/update/ ; Snapchat — PUT /campaigns/{id} ; Yandex Direct — campaigns.update

async def _platform_set_budget(platform: str, external_id: str | None, daily_budget_usd: float) -> None:
    return None


async def _platform_set_status(platform: str, external_id: str | None, status: str) -> None:
    return None


def server():
    return create_sdk_mcp_server(SERVER, "1.0.0", [
        save_content, pending_compliance, review_content, due_for_publishing, mark_published, top_performing_content,
        campaign_performance, spend_today, set_campaign_budget, pause_campaign, record_spend,
    ])
