"""Pool asyncpg + helpers usados por agentes, ferramentas e dashboard."""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

import asyncpg
import structlog

from brain.settings import get_settings

log = structlog.get_logger(__name__)
_pool: asyncpg.Pool | None = None


async def _init_conn(con: asyncpg.Connection) -> None:
    """Roda em TODA conexão do pool: jsonb entra/sai como objeto Python (listas e dicts), não como string."""
    await con.set_type_codec("jsonb", encoder=lambda v: json.dumps(v, default=str), decoder=json.loads, schema="pg_catalog")
    await con.set_type_codec("json", encoder=lambda v: json.dumps(v, default=str), decoder=json.loads, schema="pg_catalog")


async def pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(get_settings().database_url, min_size=2, max_size=12, command_timeout=30, init=_init_conn)
    return _pool


async def close() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def fetch(sql: str, *args: Any) -> list[dict[str, Any]]:
    p = await pool()
    rows = await p.fetch(sql, *args)
    return [dict(r) for r in rows]


async def fetchrow(sql: str, *args: Any) -> dict[str, Any] | None:
    p = await pool()
    row = await p.fetchrow(sql, *args)
    return dict(row) if row else None


async def execute(sql: str, *args: Any) -> str:
    p = await pool()
    return await p.execute(sql, *args)


# ───────────────────────── operações de domínio usadas em vários lugares ─────────────────────────

async def upsert_lead(channel: str, channel_user_id: str, **fields: Any) -> dict[str, Any]:
    """Cria ou atualiza o lead pelo identificador do canal. Retorna a linha completa."""
    cols = {k: v for k, v in fields.items() if v is not None}
    set_clause = ", ".join(f"{k} = EXCLUDED.{k}" for k in cols) or "updated_at = now()"
    names = ", ".join(["channel", "channel_user_id", *cols])
    placeholders = ", ".join(f"${i}" for i in range(1, len(cols) + 3))
    sql = f"""
        INSERT INTO leads ({names}) VALUES ({placeholders})
        ON CONFLICT (channel, channel_user_id) DO UPDATE SET {set_clause}
        RETURNING *"""
    row = await fetchrow(sql, channel, channel_user_id, *cols.values())
    assert row is not None
    return row


async def open_conversation(lead_id: str, channel: str) -> dict[str, Any]:
    row = await fetchrow(
        """SELECT * FROM conversations WHERE lead_id = $1 AND status <> 'closed'
           ORDER BY last_message_at DESC LIMIT 1""",
        lead_id,
    )
    if row:
        return row
    row = await fetchrow(
        "INSERT INTO conversations (lead_id, channel) VALUES ($1, $2) RETURNING *", lead_id, channel
    )
    assert row is not None
    return row


async def log_message(conversation_id: str, direction: str, author: str, body: str, **extra: Any) -> None:
    cols = {k: v for k, v in extra.items() if v is not None}
    names = ", ".join(["conversation_id", "direction", "author", "body", *cols])
    placeholders = ", ".join(f"${i}" for i in range(1, len(cols) + 5))
    await execute(
        f"INSERT INTO messages ({names}) VALUES ({placeholders})",
        conversation_id, direction, author, body, *cols.values(),
    )
    await execute("UPDATE conversations SET last_message_at = now() WHERE id = $1", conversation_id)


async def log_agent_run(**fields: Any) -> None:
    cols = {k: v for k, v in fields.items() if v is not None}
    names = ", ".join(cols)
    placeholders = ", ".join(f"${i}" for i in range(1, len(cols) + 1))
    await execute(f"INSERT INTO agent_runs ({names}) VALUES ({placeholders})", *cols.values())


async def spent_today_usd(agent: str | None = None) -> float:
    if agent:
        row = await fetchrow(
            "SELECT coalesce(sum(cost_usd),0) AS c FROM agent_runs WHERE agent = $1 AND started_at::date = current_date",
            agent,
        )
    else:
        row = await fetchrow(
            "SELECT coalesce(sum(cost_usd),0) AS c FROM agent_runs WHERE started_at::date = current_date"
        )
    return float(row["c"]) if row else 0.0


async def purge_expired_pii() -> int:
    """Apaga dados de passageiros de reservas cujo prazo de retenção venceu. Roda diariamente."""
    res = await execute(
        """UPDATE bookings SET pax = '[]'::jsonb
           WHERE pii_purge_after IS NOT NULL AND pii_purge_after < $1 AND pax <> '[]'::jsonb""",
        date.today(),
    )
    n = int(res.split()[-1]) if res else 0
    log.info("pii_purged", bookings=n)
    return n


async def rollup_kpis(day: date | None = None) -> None:
    """Consolida kpis_daily para o dia (por mercado e total). Chamado pelo Financeiro à noite e pelo dashboard sob demanda."""
    d = day or (date.today() - timedelta(days=0))
    await execute(
        """
        INSERT INTO kpis_daily (day, market_code, leads_new, leads_qualified, quotes_sent, bookings, revenue_usd, margin_usd,
                                ad_spend_usd, token_cost_usd, conversations, escalations, first_response_p50_s, csat_avg, content_published)
        SELECT $1, m.code,
          (SELECT count(*) FROM leads l WHERE l.market_code = m.code AND l.created_at::date = $1),
          (SELECT count(*) FROM leads l WHERE l.market_code = m.code AND l.stage IN ('qualified','quoted','negotiating','won') AND l.updated_at::date = $1),
          (SELECT count(*) FROM quotes q WHERE q.market_code = m.code AND q.created_at::date = $1),
          (SELECT count(*) FROM bookings b WHERE b.market_code = m.code AND b.created_at::date = $1 AND b.status <> 'cancelled'),
          (SELECT coalesce(sum(total_usd),0) FROM bookings b WHERE b.market_code = m.code AND b.created_at::date = $1 AND b.status <> 'cancelled'),
          (SELECT coalesce(sum(margin_usd),0) FROM bookings b WHERE b.market_code = m.code AND b.created_at::date = $1 AND b.status <> 'cancelled'),
          (SELECT coalesce(sum(spend_usd),0) FROM ad_spend_daily a WHERE a.market_code = m.code AND a.day = $1),
          (SELECT coalesce(sum(cost_usd),0) FROM agent_runs r WHERE r.market_code = m.code AND r.started_at::date = $1),
          (SELECT count(*) FROM conversations c JOIN leads l ON l.id = c.lead_id WHERE l.market_code = m.code AND c.started_at::date = $1),
          (SELECT count(*) FROM escalations e JOIN leads l ON l.id = e.lead_id WHERE l.market_code = m.code AND e.opened_at::date = $1),
          (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY c.first_response_ms)/1000.0 FROM conversations c JOIN leads l ON l.id = c.lead_id WHERE l.market_code = m.code AND c.started_at::date = $1),
          (SELECT avg(c.csat) FROM conversations c JOIN leads l ON l.id = c.lead_id WHERE l.market_code = m.code AND c.closed_at::date = $1),
          (SELECT count(*) FROM content_items ci WHERE ci.market_code = m.code AND ci.published_at::date = $1)
        FROM markets m
        ON CONFLICT (day, market_code) DO UPDATE SET
          leads_new = EXCLUDED.leads_new, leads_qualified = EXCLUDED.leads_qualified, quotes_sent = EXCLUDED.quotes_sent,
          bookings = EXCLUDED.bookings, revenue_usd = EXCLUDED.revenue_usd, margin_usd = EXCLUDED.margin_usd,
          ad_spend_usd = EXCLUDED.ad_spend_usd, token_cost_usd = EXCLUDED.token_cost_usd, conversations = EXCLUDED.conversations,
          escalations = EXCLUDED.escalations, first_response_p50_s = EXCLUDED.first_response_p50_s, csat_avg = EXCLUDED.csat_avg,
          content_published = EXCLUDED.content_published
        """,
        d,
    )
    await execute(
        """
        INSERT INTO kpis_daily (day, market_code, leads_new, leads_qualified, quotes_sent, bookings, revenue_usd, margin_usd,
                                ad_spend_usd, token_cost_usd, conversations, escalations, first_response_p50_s, csat_avg, content_published)
        SELECT day, 'ALL', sum(leads_new), sum(leads_qualified), sum(quotes_sent), sum(bookings), sum(revenue_usd), sum(margin_usd),
               sum(ad_spend_usd), sum(token_cost_usd), sum(conversations), sum(escalations), avg(first_response_p50_s), avg(csat_avg), sum(content_published)
        FROM kpis_daily WHERE day = $1 AND market_code <> 'ALL' GROUP BY day
        ON CONFLICT (day, market_code) DO UPDATE SET
          leads_new = EXCLUDED.leads_new, leads_qualified = EXCLUDED.leads_qualified, quotes_sent = EXCLUDED.quotes_sent,
          bookings = EXCLUDED.bookings, revenue_usd = EXCLUDED.revenue_usd, margin_usd = EXCLUDED.margin_usd,
          ad_spend_usd = EXCLUDED.ad_spend_usd, token_cost_usd = EXCLUDED.token_cost_usd, conversations = EXCLUDED.conversations,
          escalations = EXCLUDED.escalations, first_response_p50_s = EXCLUDED.first_response_p50_s, csat_avg = EXCLUDED.csat_avg,
          content_published = EXCLUDED.content_published
        """,
        d,
    )
