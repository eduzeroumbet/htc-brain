"""Cenário 6.5 — balcão de propostas com lease: worker morto, dois workers, uma única proposta e um único PDF.

Precisa de Postgres de verdade (FOR UPDATE SKIP LOCKED e restrição única não se simulam):

    docker run --rm -d --name htc-test-pg -e POSTGRES_PASSWORD=test -p 55432:5432 pgvector/pgvector:pg16
    HTC_TEST_DATABASE_URL=postgresql://postgres:test@localhost:55432/postgres pytest tests/test_proposal_lease_db.py

O banco é zerado (DROP SCHEMA public) e recebe db/migrations/*.sql em ordem — por isso só roda com a variável definida.
O modelo (LLM) não entra: os dois "workers" chamam direto as ferramentas que o balcão manda usar (build_quote e
render_quote_pdf). O PDF é simulado (sem WeasyPrint nem object store) e o câmbio é fixo (sem rede).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any, AsyncIterator

import asyncpg
import pytest

from brain.core import db, lease
from brain.tools import pdf, quotes

URL = os.environ.get("HTC_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="HTC_TEST_DATABASE_URL não definido (Postgres descartável)")
ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "db" / "migrations" / "013_proposal_idempotency.sql"


async def _reset_and_migrate(con: asyncpg.Connection) -> None:
    await con.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    for f in sorted((ROOT / "db" / "migrations").glob("*.sql")):
        await con.execute(f.read_text())


@pytest.fixture
async def pg() -> AsyncIterator[asyncpg.Connection]:
    con = await asyncpg.connect(URL)
    await _reset_and_migrate(con)
    await db.pool()   # cria o pool antes: dois workers em gather não podem criar dois pools
    yield con
    await db.close()  # o pool do módulo é preso ao event loop de cada teste
    await con.close()


@pytest.fixture
def renders(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """PDF simulado: conta cada geração; demora um pouco para os dois workers se cruzarem."""
    done: list[str] = []

    async def fake_render(q: dict[str, Any]) -> str:
        await asyncio.sleep(0.05)
        done.append(str(q["id"]))
        return f"https://teste.invalid/docs/quotes/{q['id']}.pdf"

    async def fixed_fx(currency: str) -> float:
        return 5.0

    monkeypatch.setattr(pdf, "render_quote", fake_render)
    monkeypatch.setattr(quotes, "fx", fixed_fx)
    return done


async def _request(con: asyncpg.Connection) -> tuple[str, str, str]:
    """(lead_id, proposal_request_id, catalog_item_id) de uma solicitação aberta."""
    lead = await con.fetchval("INSERT INTO leads (channel, channel_user_id, market_code) VALUES ('whatsapp', '5511900000001', 'BR') RETURNING id")
    rid = await con.fetchval("""INSERT INTO proposal_requests (lead_id, summary, due_at)
                                VALUES ($1, 'Dubai em março, 2 adultos, safári no deserto', now() + interval '30 minutes') RETURNING id""", lead)
    item = await con.fetchval("INSERT INTO catalog_items (kind, name, net_price_usd, markup_pct) VALUES ('experience', 'Safári no deserto', 100, 20) RETURNING id")
    return str(lead), str(rid), str(item)


def _payload(res: dict[str, Any]) -> dict[str, Any]:
    return json.loads(res["content"][0]["text"])


async def _build(lead: str, rid: str, item: str) -> dict[str, Any]:
    fn = getattr(quotes.build_quote, "handler", quotes.build_quote)
    return _payload(await fn({"lead_id": lead, "market_code": "BR", "title": "Dubai em março", "proposal_request_id": rid,
                              "items": [{"catalog_item_id": item, "qty": 2, "date": "2027-03-10"}]}))


async def _pdf(quote_id: str) -> dict[str, Any]:
    fn = getattr(quotes.render_quote_pdf, "handler", quotes.render_quote_pdf)
    return _payload(await fn({"quote_id": quote_id}))


async def _counts(con: asyncpg.Connection, rid: str) -> tuple[int, int]:
    n_quotes = await con.fetchval("SELECT count(*) FROM quotes WHERE proposal_request_id = $1", rid)
    n_pdfs = await con.fetchval("SELECT count(*) FROM quote_pdfs p JOIN quotes q ON q.id = p.quote_id WHERE q.proposal_request_id = $1", rid)
    return n_quotes, n_pdfs


# T-6.5.1 ─ worker morre com o lease; o lease vence e outro worker reprocessa
async def test_worker_morto_lease_expira_e_outro_reprocessa(pg: asyncpg.Connection, renders: list[str]) -> None:
    lead, rid, item = await _request(pg)
    a = await lease.claim(db, "worker-a", 60)
    assert a is not None and a.request_id == rid
    assert await lease.claim(db, "worker-b", 60) is None            # lease vivo: ninguém mais pega

    # worker A morre: não renova nem libera. O tempo passa no relógio do banco até o lease vencer.
    await pg.execute("UPDATE proposal_requests SET locked_until = now() - interval '1 second' WHERE id = $1", rid)
    b = await lease.claim(db, "worker-b", 60)
    assert b is not None and b.request_id == rid and b.token > a.token
    assert await lease.renew(db, a, 60) is False                    # o zumbi perdeu o lease

    quote = await _build(lead, rid, item)
    assert _pdf_url(await _pdf(quote["quote_id"]))
    assert await lease.finish(db, b, "sent", quote["quote_id"]) is True
    assert await lease.finish(db, a, "sent", quote["quote_id"]) is False   # fencing: o zumbi não registra nem envia

    row = await pg.fetchrow("SELECT status, quote_id, attempts, locked_by FROM proposal_requests WHERE id = $1", rid)
    assert (row["status"], str(row["quote_id"]), row["attempts"], row["locked_by"]) == ("sent", quote["quote_id"], 2, None)
    assert await _counts(pg, rid) == (1, 1) and len(renders) == 1


def _pdf_url(res: dict[str, Any]) -> str:
    return res.get("pdf_url") or ""


# T-6.5.2 ─ dois workers ao mesmo tempo: um único lease, uma única proposta e um único PDF
async def test_dois_workers_uma_proposta_um_pdf(pg: asyncpg.Connection, renders: list[str]) -> None:
    lead, rid, item = await _request(pg)
    claims = await asyncio.gather(lease.claim(db, "worker-a", 60), lease.claim(db, "worker-b", 60))
    assert sum(c is not None for c in claims) == 1                  # SKIP LOCKED: só um pega a solicitação

    # pior caso: o outro worker também chega às ferramentas (zumbi com lease vencido) no mesmo instante
    q1, q2 = await asyncio.gather(_build(lead, rid, item), _build(lead, rid, item))
    assert q1["quote_id"] == q2["quote_id"] and {q1.get("reused"), q2.get("reused")} == {None, True}
    p1, p2 = await asyncio.gather(_pdf(q1["quote_id"]), _pdf(q1["quote_id"]))
    assert sorted(bool(_pdf_url(p)) for p in (p1, p2)) == [False, True]   # um gera; o outro não gera outro
    assert await _counts(pg, rid) == (1, 1) and len(renders) == 1

    again = await _pdf(q1["quote_id"])                               # depois de pronto, todos recebem a mesma URL
    assert again["reused"] is True and again["pdf_url"] == _pdf_url(p1) + _pdf_url(p2)
    assert len(renders) == 1


# T-6.5.3 ─ renovação mantém a posse; release devolve na hora
async def test_renovacao_mantem_posse_e_release_devolve(pg: asyncpg.Connection) -> None:
    _, rid, _ = await _request(pg)
    a = await lease.claim(db, "worker-a", 2)
    before = await pg.fetchval("SELECT locked_until FROM proposal_requests WHERE id = $1", rid)
    assert await lease.renew(db, a, 60) is True
    after = await pg.fetchval("SELECT locked_until FROM proposal_requests WHERE id = $1", rid)
    assert after > before
    assert await lease.claim(db, "worker-b", 60) is None
    assert await lease.release(db, a) is True
    b = await lease.claim(db, "worker-b", 60)
    assert b is not None and b.request_id == rid


# worker morreu no meio do PDF: a reivindicação parada vence e outro worker gera o (único) PDF
async def test_pdf_reivindicacao_parada_e_assumida(pg: asyncpg.Connection, renders: list[str]) -> None:
    lead, rid, item = await _request(pg)
    quote = await _build(lead, rid, item)
    await pg.execute("INSERT INTO quote_pdfs (quote_id, claimed_by, claimed_at) VALUES ($1, 'morto', now() - interval '1 hour')", quote["quote_id"])
    res = await _pdf(quote["quote_id"])
    assert res["pdf_url"].endswith(f"{quote['quote_id']}.pdf") and len(renders) == 1
    assert await _counts(pg, rid) == (1, 1)


# migração 013: reaplica sem erro, restrição única no banco e reversão pelo down comentado
async def test_migracao_013_unica_e_reversivel(pg: asyncpg.Connection) -> None:
    await pg.execute(MIGRATION.read_text())                          # segunda passada, como o `make migrate`
    lead, rid, _ = await _request(pg)
    insert = """INSERT INTO quotes (lead_id, items, subtotal_usd, total_usd, proposal_request_id) VALUES ($1, '[]'::jsonb, 1, 1, $2)"""
    await pg.execute(insert, lead, rid)
    with pytest.raises(asyncpg.UniqueViolationError):
        await pg.execute(insert, lead, rid)
    await pg.execute(insert, lead, None)                             # cotação fora do balcão continua livre
    await pg.execute(insert, lead, None)

    down = re.findall(r"^--\s+((?:DROP|ALTER) .*;)$", MIGRATION.read_text(), re.M)
    assert len(down) == 3
    for stmt in down:
        await pg.execute(stmt)
    assert await pg.fetchval("SELECT to_regclass('quote_pdfs') IS NULL")
    assert not await pg.fetchval("SELECT count(*) FROM information_schema.columns WHERE table_name = 'quotes' AND column_name = 'proposal_request_id'")
    await pg.execute(MIGRATION.read_text())
    assert await pg.fetchval("SELECT to_regclass('quote_pdfs') IS NOT NULL")
