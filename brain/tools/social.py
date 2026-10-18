"""Redes sociais: contas, calendário, publicação por plataforma, métricas por post, repurposing. O Jev avalia a peça antes de agendar.

Publicação real por plataforma usa a API correspondente quando o token existe (variável indicada em social_accounts.token_env):
Meta Graph (Instagram/Facebook), Telegram Bot (canal), VK API (wall.post), YouTube Data (descrição/comunidade). Sem token,
a ferramenta devolve o pacote pronto para publicação manual e marca 'ready_manual' — nada fica travado.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Any

import httpx

from brain.core import db, jev
from brain.tools import create_sdk_mcp_server, err, ok, tool

SERVER = "social"

PLATFORM_LIMITS = {"instagram": 2200, "facebook": 63206, "telegram": 4096, "vk": 15000, "youtube": 5000, "tiktok": 2200, "snapchat": 250, "linkedin": 3000, "x": 280, "dzen": 5000}


@tool("social_accounts", "Contas sociais da agência por mercado/plataforma (handle, seguidores, se há token para publicar).", {"market_code": str})
async def social_accounts(args: dict[str, Any]) -> dict[str, Any]:
    rows = await db.fetch("SELECT id, platform, handle, market_codes, language, followers, active, token_env FROM social_accounts WHERE active AND ($1::text IS NULL OR $1 = ANY(market_codes)) ORDER BY platform", args.get("market_code"))
    for r in rows:
        r["can_publish"] = bool(r.get("token_env") and os.getenv(r["token_env"]))
        r.pop("token_env", None)
    return ok(rows)


@tool("editorial_calendar", "Calendário dos próximos N dias por mercado: peças agendadas/publicadas por plataforma e dia, buracos (dias sem post no canal primário) e pilares já cobertos.", {"market_code": str, "days": int})
async def editorial_calendar(args: dict[str, Any]) -> dict[str, Any]:
    days = int(args.get("days") or 7)
    rows = await db.fetch("""SELECT id, platform, format, pillar, title, status, scheduled_for, published_at FROM content_items
                             WHERE ($1::text IS NULL OR market_code = $1) AND coalesce(scheduled_for, published_at) BETWEEN now() - interval '1 day' AND now() + ($2 || ' days')::interval
                             ORDER BY coalesce(scheduled_for, published_at)""", args.get("market_code"), str(days))
    covered = {}
    for r in rows:
        d = str((r["scheduled_for"] or r["published_at"]).date())
        covered.setdefault(d, set()).add(r["platform"] or "?")
    gaps = [str(date.today() + timedelta(days=i)) for i in range(days) if str(date.today() + timedelta(days=i)) not in covered]
    pillars = await db.fetch("SELECT pillar, count(*) n FROM content_items WHERE ($1::text IS NULL OR market_code = $1) AND created_at > now() - interval '14 days' GROUP BY 1 ORDER BY 2 DESC", args.get("market_code"))
    return ok({"items": rows, "days_without_posts": gaps, "pillars_last_14d": pillars})


@tool("plan_post", "Cria uma peça social já com plataforma, horário, hashtags e brief de mídia; o Jev avalia o potencial (jev_quality) e a peça vai para compliance_review (ou direto a 'scheduled' se quality ≥ 0.8 e sem flags). Respeita o limite de caracteres da plataforma.", {
    "market_code": str, "platform": str, "format": str, "pillar": str, "language": str, "title": str, "body": str, "hashtags": list, "media_brief": str, "scheduled_for": str, "repurposed_from": str, "experiment_id": str})
async def plan_post(args: dict[str, Any]) -> dict[str, Any]:
    body = args["body"]
    limit = PLATFORM_LIMITS.get(args["platform"], 2200)
    if len(body) > limit:
        return err(f"texto com {len(body)} caracteres excede o limite de {limit} para {args['platform']}")
    quality, status = None, "compliance_review"
    ans = await jev.decide({"platform": args["platform"], "market": args["market_code"], "title": args.get("title"), "body": body[:3000], "hashtags": args.get("hashtags")}, {
        "quality": {"type": "score", "instructions": "Potencial de engajamento e de gerar lead para uma agência de viagens de Dubai neste mercado e plataforma (gancho na 1ª linha, detalhe concreto, CTA claro, adequação cultural)", "criteria": ["fraco", "mediano", "bom", "excelente"]},
        "hook_in_first_line": {"type": "noul", "instructions": "A primeira linha prende a atenção sem clickbait?"},
        "has_cta": {"type": "noul", "instructions": "Há um chamado claro para WhatsApp/Telegram/chat da agência?"},
        "risky": {"type": "noul", "instructions": "Há algo que o Compliance reprovaria (preço sem 'a partir de', promessa, fato sem fonte, cliente identificado, álcool/roupa inadequada ao mercado)?"}})
    if ans:
        quality = round(ans.score("quality"), 3)
        if quality >= 0.8 and ans.noul("risky") < 0.2 and ans.noul("has_cta") >= 0.5:
            status = "scheduled"
    row = await db.fetchrow(
        """INSERT INTO content_items (market_code, pillar, format, channel, platform, language, title, body, hashtags, media_brief, status, scheduled_for, repurposed_from, experiment_id, jev_quality, created_by)
           VALUES ($1,$2,$3,$4,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,'ai:social_manager') RETURNING id, status, jev_quality""",
        args["market_code"], args.get("pillar"), args.get("format") or "post", args["platform"], args.get("language"), args.get("title"), body,
        args.get("hashtags") or [], args.get("media_brief"), status, datetime.fromisoformat(args["scheduled_for"]) if args.get("scheduled_for") else None,
        args.get("repurposed_from"), args.get("experiment_id"), quality)
    out = dict(row or {})
    if ans:
        out["jev"] = {"hook": round(ans.noul("hook_in_first_line"), 2), "cta": round(ans.noul("has_cta"), 2), "risky": round(ans.noul("risky"), 2)}
    return ok(out)


async def _publish(platform: str, account: dict[str, Any], item: dict[str, Any]) -> str | None:
    token = os.getenv(account.get("token_env") or "", "")
    if not token:
        return None
    text = item["body"] + ("\n\n" + " ".join(f"#{h.lstrip('#')}" for h in (item.get("hashtags") or [])) if item.get("hashtags") else "")
    async with httpx.AsyncClient(timeout=30) as c:
        if platform == "telegram":
            r = await c.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": account["external_id"], "text": text[:4096], "disable_web_page_preview": False})
            return str(r.json().get("result", {}).get("message_id")) if r.status_code < 400 else None
        if platform == "facebook":
            r = await c.post(f"https://graph.facebook.com/v21.0/{account['external_id']}/feed", data={"message": text, "access_token": token})
            return r.json().get("id") if r.status_code < 400 else None
        if platform == "instagram":
            media = (item.get("media") or [{}])[0].get("url") if item.get("media") else None
            if not media:
                return None  # Instagram exige imagem/vídeo: fica para publicação manual com o media_brief
            r1 = await c.post(f"https://graph.facebook.com/v21.0/{account['external_id']}/media", data={"image_url": media, "caption": text[:2200], "access_token": token})
            cid = r1.json().get("id")
            if not cid:
                return None
            r2 = await c.post(f"https://graph.facebook.com/v21.0/{account['external_id']}/media_publish", data={"creation_id": cid, "access_token": token})
            return r2.json().get("id") if r2.status_code < 400 else None
        if platform == "vk":
            r = await c.post("https://api.vk.com/method/wall.post", data={"owner_id": account["external_id"], "from_group": 1, "message": text[:15000], "access_token": token, "v": "5.199"})
            return str(r.json().get("response", {}).get("post_id")) if r.status_code < 400 and "response" in r.json() else None
    return None


@tool("publish_due", "Publica as peças 'scheduled' cujo horário chegou nas plataformas com token (Telegram, Facebook, Instagram com mídia, VK). Sem token/mídia, devolve o pacote para publicação manual e marca 'ready_manual'.", {"limit": int})
async def publish_due(args: dict[str, Any]) -> dict[str, Any]:
    rows = await db.fetch("SELECT * FROM content_items WHERE status = 'scheduled' AND scheduled_for <= now() AND platform IS NOT NULL ORDER BY scheduled_for LIMIT $1", int(args.get("limit") or 20))
    accounts = await db.fetch("SELECT * FROM social_accounts WHERE active")
    published, manual = [], []
    for it in rows:
        acc = next((a for a in accounts if a["platform"] == it["platform"] and it["market_code"] in (a["market_codes"] or [])), None)
        ext = await _publish(it["platform"], acc, it) if acc else None
        if ext:
            await db.execute("UPDATE content_items SET status = 'published', published_at = now(), external_id = $2 WHERE id = $1", it["id"], ext)
            published.append({"id": str(it["id"]), "platform": it["platform"], "external_id": ext})
        else:
            await db.execute("UPDATE content_items SET status = 'ready_manual' WHERE id = $1", it["id"])
            manual.append({"id": str(it["id"]), "platform": it["platform"], "account": (acc or {}).get("handle"), "title": it.get("title"), "body": it["body"], "hashtags": it.get("hashtags"), "media_brief": it.get("media_brief")})
    return ok({"published": published, "manual_pack": manual})


@tool("record_post_metrics", "Registra métricas do dia de um post (vindas da API da plataforma ou lidas manualmente).", {"content_id": str, "day": str, "impressions": int, "reach": int, "likes": int, "comments": int, "saves": int, "shares": int, "clicks": int})
async def record_post_metrics(args: dict[str, Any]) -> dict[str, Any]:
    d = date.fromisoformat(args["day"]) if args.get("day") else date.today()
    leads = await db.fetchrow("SELECT count(*) n FROM leads WHERE source_content_id = $1", args["content_id"])
    await db.execute("""INSERT INTO post_metrics_daily (day, content_id, impressions, reach, likes, comments, saves, shares, clicks, leads)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                        ON CONFLICT (day, content_id) DO UPDATE SET impressions = EXCLUDED.impressions, reach = EXCLUDED.reach, likes = EXCLUDED.likes, comments = EXCLUDED.comments,
                          saves = EXCLUDED.saves, shares = EXCLUDED.shares, clicks = EXCLUDED.clicks, leads = EXCLUDED.leads""",
                     d, args["content_id"], *(int(args.get(k) or 0) for k in ("impressions", "reach", "likes", "comments", "saves", "shares", "clicks")), int(leads["n"]))  # type: ignore[index]
    return ok({"recorded": True})


@tool("content_performance", "Desempenho dos últimos N dias por mercado: por plataforma, formato e pilar (alcance, engajamento %, cliques, leads, leads por 1k alcance) + top 5 e bottom 5 peças.", {"market_code": str, "days": int})
async def content_performance(args: dict[str, Any]) -> dict[str, Any]:
    days = int(args.get("days") or 14)
    base = """FROM content_items c JOIN post_metrics_daily m ON m.content_id = c.id
              WHERE c.status = 'published' AND m.day > current_date - $1::int AND ($2::text IS NULL OR c.market_code = $2)"""
    agg = "sum(m.reach) reach, sum(m.likes + m.comments + m.saves + m.shares) engagement, sum(m.clicks) clicks, sum(m.leads) leads"
    by_platform = await db.fetch(f"SELECT c.platform, count(DISTINCT c.id) posts, {agg} {base} GROUP BY 1 ORDER BY leads DESC", days, args.get("market_code"))
    by_format = await db.fetch(f"SELECT c.format, count(DISTINCT c.id) posts, {agg} {base} GROUP BY 1 ORDER BY leads DESC", days, args.get("market_code"))
    by_pillar = await db.fetch(f"SELECT c.pillar, count(DISTINCT c.id) posts, {agg} {base} GROUP BY 1 ORDER BY leads DESC", days, args.get("market_code"))
    top = await db.fetch(f"SELECT c.id, c.platform, c.title, {agg} {base} GROUP BY c.id ORDER BY leads DESC, engagement DESC LIMIT 5", days, args.get("market_code"))
    bottom = await db.fetch(f"SELECT c.id, c.platform, c.title, {agg} {base} GROUP BY c.id ORDER BY reach ASC LIMIT 5", days, args.get("market_code"))
    for rows in (by_platform, by_format, by_pillar, top, bottom):
        for r in rows:
            reach = int(r["reach"] or 0)
            r["engagement_pct"] = round(100 * int(r["engagement"] or 0) / reach, 2) if reach else None
            r["leads_per_1k_reach"] = round(1000 * int(r["leads"] or 0) / reach, 2) if reach else None
    return ok({"days": days, "by_platform": by_platform, "by_format": by_format, "by_pillar": by_pillar, "top": top, "bottom": bottom})


@tool("repurpose_candidates", "Peças publicadas com melhor desempenho nos últimos N dias que ainda não foram reaproveitadas em outra plataforma/formato/mercado.", {"days": int, "limit": int})
async def repurpose_candidates(args: dict[str, Any]) -> dict[str, Any]:
    rows = await db.fetch("""SELECT c.id, c.market_code, c.platform, c.format, c.pillar, c.title, c.body, sum(m.reach) reach, sum(m.leads) leads
                             FROM content_items c JOIN post_metrics_daily m ON m.content_id = c.id
                             WHERE c.status = 'published' AND m.day > current_date - $1::int
                               AND NOT EXISTS (SELECT 1 FROM content_items r WHERE r.repurposed_from = c.id)
                             GROUP BY c.id ORDER BY leads DESC, reach DESC LIMIT $2""", int(args.get("days") or 30), int(args.get("limit") or 5))
    return ok(rows)


def server():
    return create_sdk_mcp_server(SERVER, "1.0.0", [social_accounts, editorial_calendar, plan_post, publish_due, record_post_metrics, content_performance, repurpose_candidates])
