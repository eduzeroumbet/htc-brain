"""handoff_events contra um Postgres 16 descartável (pgvector/pgvector:pg16): migração, deduplicação pelo índice único,
varredura (atendido por mensagem humana, SLA vencido) e as consultas da Camada 0.

    docker run --rm -d --name htc-test-pg -e POSTGRES_PASSWORD=test -p 55432:5432 pgvector/pgvector:pg16
    HTC_TEST_DATABASE_URL=postgresql://postgres:test@localhost:55432/postgres pytest tests/test_handoff_db.py

O banco é zerado (DROP SCHEMA public) e recebe db/migrations/*.sql em ordem — por isso só roda com a variável definida.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncIterator

import asyncpg
import pytest

from brain.core import db, handoff

URL = os.environ.get("HTC_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="HTC_TEST_DATABASE_URL não definido (Postgres descartável)")
ROOT = Path(__file__).resolve().parents[1]


async def _reset_and_migrate(con: asyncpg.Connection) -> None:
    await con.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    for f in sorted((ROOT / "db" / "migrations").glob("*.sql")):
        await con.execute(f.read_text())


@pytest.fixture
async def pg() -> AsyncIterator[asyncpg.Connection]:
    con = await asyncpg.connect(URL)
    await _reset_and_migrate(con)
    yield con
    await db.close()  # o pool do módulo é preso ao event loop de cada teste
    await con.close()


@pytest.fixture
def sem_envio(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Canais simulados: nada sai do teste."""
    sent: list[tuple[str, str]] = []

    async def fake(canal: str, destino: str, assunto: str, texto: str) -> None:
        sent.append((canal, destino))

    monkeypatch.setattr(handoff, "_enviar_canal", fake)
    s = handoff.get_settings()
    monkeypatch.setattr(s, "handoff_alert_email_to", "equipe@teste.invalid")
    monkeypatch.setattr(s, "handoff_alert_channel", "email")
    return sent


async def _conversa(con: asyncpg.Connection, cuid: str = "971500000001") -> tuple[str, str]:
    lead = await con.fetchval("INSERT INTO leads (channel, channel_user_id, display_name) VALUES ('whatsapp', $1, 'Teste') RETURNING id", cuid)
    conv = await con.fetchval("INSERT INTO conversations (lead_id, channel) VALUES ($1, 'whatsapp') RETURNING id", lead)
    return str(conv), str(lead)


def det(trigger: str) -> dict[str, Any]:
    return {"trigger": trigger, "subtype": None, "detected_by": "keyword", "language": "pt", "details": {"terms": ["x"]}}


async def test_migracao_e_idempotente(pg: asyncpg.Connection) -> None:
    await pg.execute((ROOT / "db" / "migrations" / "013_handoff_events.sql").read_text())   # segunda passada
    idx = {r["indexname"] for r in await pg.fetch("SELECT indexname FROM pg_indexes WHERE tablename = 'handoff_events'")}
    assert {"handoff_events_one_open_idx", "handoff_events_queue_idx", "handoff_events_created_idx"} <= idx
    assert await pg.fetchval("SELECT count(*) FROM rules WHERE rule LIKE 'Transbordo para humano:%'") == 1


async def test_dedup_pelo_indice_mesmo_em_paralelo(pg: asyncpg.Connection) -> None:
    conv, lead = await _conversa(pg)
    res = await asyncio.gather(*(handoff.registrar(conv, lead, det("payment")) for _ in range(5)))
    assert sum(r["novo"] for r in res) == 1 and len({r["id"] for r in res}) == 1
    assert await pg.fetchval("SELECT occurrence_count FROM handoff_events") == 5
    assert (await handoff.registrar(conv, lead, det("complaint")))["novo"] is True
    await handoff.fechar(conversation_id=conv, por="ceo")
    assert (await handoff.registrar(conv, lead, det("payment")))["novo"] is True
    assert await pg.fetchval("SELECT count(*) FROM handoff_events") == 3


async def test_alerta_varredura_e_camada0(pg: asyncpg.Connection, sem_envio: list[tuple[str, str]], monkeypatch: pytest.MonkeyPatch) -> None:
    t0 = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=3)
    relogio = {"t": t0}
    monkeypatch.setattr(handoff, "agora", lambda: relogio["t"])
    conv, lead = await _conversa(pg)
    conv2, lead2 = await _conversa(pg, "971500000002")
    a = await handoff.registrar(conv, lead, det("complaint"))      # SLA 60 min
    b = await handoff.registrar(conv2, lead2, det("payment"))      # SLA 120 min (outra conversa)
    assert await handoff.alertar(a["id"]) is True
    row = await pg.fetchrow("SELECT status, alerted_at, created_at, alert_channel FROM handoff_events WHERE id = $1", a["id"])
    assert row["status"] == "alerted" and row["alert_channel"] == "email" and row["alerted_at"] - row["created_at"] <= timedelta(seconds=60)

    # humano responde o pagamento aos 30 min; a reclamação fica sem resposta e vence
    await pg.execute("INSERT INTO messages (conversation_id, direction, author, body, created_at) VALUES ($1, 'out', 'human:mariam', 'oi', $2)",
                     conv2, t0 + timedelta(minutes=30))
    relogio["t"] = t0 + timedelta(minutes=61)
    out = await handoff.varrer()
    assert out["attended"] == 1 and out["breached"] == 1 and out["escalated"] == 1 and out["alerted"] == 0
    st = {r["id"]: r for r in await pg.fetch("SELECT id::text, status, attended_at, attended_by, breached_at FROM handoff_events")}
    assert st[b["id"]]["status"] == "attended" and st[b["id"]]["attended_by"] == "human:mariam"
    assert st[b["id"]]["attended_at"] == t0 + timedelta(minutes=30)
    assert st[a["id"]]["status"] == "breached" and st[a["id"]]["breached_at"] == relogio["t"]

    m = await handoff.metricas_camada0()
    assert m["open_queue_count"] == 1 and m["breached_open_count"] == 1
    assert m["oldest_wait_seconds"] == 61 * 60
    assert m["sla_within_pct_24h"] == 50.0      # pagamento dentro, reclamação vencida na fila
    assert m["queue"][0]["display_name"] == "Teste"

    assert await handoff.marcar_atendido(event_id=a["id"], por="painel") == 1
    assert (await handoff.metricas_camada0())["open_queue_count"] == 0
