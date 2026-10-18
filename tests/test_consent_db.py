"""consent_log e DSAR contra um Postgres 16 descartável (pgvector/pgvector:pg16).

    docker run --rm -d --name htc-test-pg -e POSTGRES_PASSWORD=test -p 55432:5432 pgvector/pgvector:pg16
    HTC_TEST_DATABASE_URL=postgresql://postgres:test@localhost:55432/postgres pytest tests/test_consent_db.py

O banco é zerado (DROP SCHEMA public) e recebe db/migrations/*.sql em ordem — por isso só roda com a variável definida.
"""
from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path
from typing import Any, AsyncIterator

import asyncpg
import pytest

from brain.core import consent, db

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


async def _lead(con: asyncpg.Connection, cuid: str = "5511999", consent_marketing: bool = False, **extra: Any) -> str:
    return str(await con.fetchval(
        "INSERT INTO leads (channel, channel_user_id, consent_marketing, language, market_code) VALUES ('whatsapp', $1, $2, $3, $4) RETURNING id",
        cuid, consent_marketing, extra.get("language", "pt"), extra.get("market_code")))


async def test_migracao_e_idempotente_e_cria_indices(pg: asyncpg.Connection) -> None:
    for f in sorted((ROOT / "db" / "migrations").glob("*.sql")):  # segunda passada, como o `make migrate`
        await pg.execute(f.read_text())
    idx = {r["indexname"] for r in await pg.fetch("SELECT indexname FROM pg_indexes WHERE tablename IN ('consent_log', 'data_requests')")}
    assert {"consent_log_lead_idx", "consent_log_channel_idx", "consent_log_purpose_idx", "consent_log_one_active_idx",
            "data_requests_lead_idx", "data_requests_one_open_idx"} <= idx
    assert await pg.fetchval("SELECT count(*) FROM rules WHERE rule LIKE 'Descadastro: PARAR, STOP, SAIR%'") == 1


async def test_backfill_de_quem_ja_tinha_consentimento(pg: asyncpg.Connection) -> None:
    lid = await _lead(pg, consent_marketing=True)
    await pg.execute((ROOT / "db" / "migrations" / "012_consent_log.sql").read_text())
    await pg.execute((ROOT / "db" / "migrations" / "012_consent_log.sql").read_text())
    rows = await pg.fetch("SELECT source, status, purpose FROM consent_log WHERE lead_id = $1", lid)
    assert [dict(r) for r in rows] == [{"source": "backfill_leads", "status": "active", "purpose": "marketing"}]
    assert await consent.pode_enviar_marketing(lid, "whatsapp") is True


async def test_sem_consentimento_marketing_bloqueado(pg: asyncpg.Connection) -> None:
    lid = await _lead(pg)
    assert await consent.pode_enviar_marketing(lid, "whatsapp") is False
    assert await consent.pode_enviar_marketing(None, "whatsapp") is False


async def test_optin_revogacao_idempotente_e_novo_optin(pg: asyncpg.Connection) -> None:
    lid = await _lead(pg)
    assert await consent.registrar_consentimento(lid, "whatsapp", texto="Aceito receber ofertas", idioma="pt") is True
    assert await consent.registrar_consentimento(lid, "whatsapp", texto="Aceito receber ofertas", idioma="pt") is False  # não duplica
    assert await consent.pode_enviar_marketing(lid, "whatsapp") is True
    assert await pg.fetchval("SELECT consent_marketing FROM leads WHERE id = $1", lid) is True

    assert await consent.revogar_marketing(lid, "whatsapp", texto="STOP", idioma="pt") is True
    assert await consent.revogar_marketing(lid, "whatsapp", texto="STOP", idioma="pt") is False  # segunda vez: nada muda
    rows = await pg.fetch("SELECT status, revoked_at FROM consent_log WHERE lead_id = $1", lid)
    assert len(rows) == 1 and rows[0]["status"] == "revoked" and rows[0]["revoked_at"] is not None
    assert await consent.pode_enviar_marketing(lid, "whatsapp") is False
    assert await pg.fetchval("SELECT consent_marketing FROM leads WHERE id = $1", lid) is False

    assert await consent.registrar_consentimento(lid, "whatsapp", texto="Quero voltar a receber", idioma="pt") is True
    assert await pg.fetchval("SELECT count(*) FROM consent_log WHERE lead_id = $1", lid) == 2  # histórico preservado
    assert await consent.pode_enviar_marketing(lid, "whatsapp") is True


async def test_revogar_sem_consentimento_previo_grava_prova_uma_vez(pg: asyncpg.Connection) -> None:
    lid = await _lead(pg)
    assert await consent.revogar_marketing(lid, "whatsapp", texto="PARAR") is True
    assert await consent.revogar_marketing(lid, "whatsapp", texto="PARAR") is False
    row = await pg.fetchrow("SELECT status, source, consent_text, purpose FROM consent_log WHERE lead_id = $1", lid)
    assert dict(row) == {"status": "revoked", "source": "whatsapp_keyword", "consent_text": "PARAR", "purpose": "marketing"}


async def test_transacional_nao_e_afetado(pg: asyncpg.Connection) -> None:
    lid = await _lead(pg)
    await consent.registrar_consentimento(lid, "whatsapp", finalidade="transactional", texto="Atendimento da reserva")
    await consent.revogar_marketing(lid, "whatsapp", texto="STOP")
    assert await pg.fetchval("SELECT status FROM consent_log WHERE lead_id = $1 AND purpose = 'transactional'", lid) == "active"


async def test_descadastro_all_channels_revoga_todos_os_canais_e_novo_optin_reabre_so_o_canal(pg: asyncpg.Connection) -> None:
    lid = await _lead(pg)
    for canal in ("whatsapp", "email", "instagram"):
        await consent.registrar_consentimento(lid, canal, texto="Aceito receber ofertas", idioma="pt")
    assert await consent.revogar_marketing(lid, "whatsapp", texto="STOP") is True
    assert await pg.fetchval("SELECT count(*) FROM consent_log WHERE lead_id = $1 AND status = 'active' AND purpose = 'marketing'", lid) == 0
    assert await consent.motivo_bloqueio({"channel": "email", "lead_id": lid, "purpose": "marketing"}) == "consentimento_revogado"
    assert await consent.revogar_marketing(lid, "email", texto="STOP") is False  # nada mais a revogar

    await consent.registrar_consentimento(lid, "email", texto="Quero voltar a receber por e-mail", idioma="pt")
    assert await consent.pode_enviar_marketing(lid, "email") is True
    assert await consent.pode_enviar_marketing(lid, "whatsapp") is False
    assert await consent.pode_enviar_marketing(lid, "instagram") is False


async def test_revogacao_em_outro_canal_bloqueia_linha_ativa_mais_antiga(pg: asyncpg.Connection) -> None:
    lid = await _lead(pg)
    await consent.registrar_consentimento(lid, "email", texto="Aceito", idioma="pt")
    await pg.execute("UPDATE consent_log SET recorded_at = now() - interval '2 days' WHERE lead_id = $1", lid)
    await pg.execute("""INSERT INTO consent_log (lead_id, channel, recorded_at, consent_text, consent_version, source, purpose, status, revoked_at)
                        VALUES ($1, 'whatsapp', now() - interval '1 day', 'STOP', 'v1', 'whatsapp_keyword', 'marketing', 'revoked', now() - interval '1 day')""", lid)
    assert await consent.motivo_bloqueio_marketing(lid, "email") == "revogado_em_outro_canal"


async def test_janela_de_atendimento_pela_ultima_mensagem_do_cliente(pg: asyncpg.Connection) -> None:
    lid = await _lead(pg)
    ev = {"channel": "whatsapp", "lead_id": lid, "purpose": "session_reply"}
    assert await consent.motivo_bloqueio(ev) == "fora_da_janela_sem_registro_de_consentimento"
    conv = await pg.fetchval("INSERT INTO conversations (lead_id, channel) VALUES ($1, 'whatsapp') RETURNING id", lid)
    await pg.execute("INSERT INTO messages (conversation_id, direction, author, body, created_at) VALUES ($1, 'in', 'client', 'oi', now() - interval '25 hours')", conv)
    await pg.execute("INSERT INTO messages (conversation_id, direction, author, body) VALUES ($1, 'out', 'ai:consultant', 'olá')", conv)
    assert await consent.dentro_da_janela(lid, "whatsapp", 24) is False  # mensagem nossa não abre janela
    await pg.execute("INSERT INTO messages (conversation_id, direction, author, body) VALUES ($1, 'in', 'client', 'quero um orçamento')", conv)
    assert await consent.dentro_da_janela(lid, "whatsapp", 24) is True
    assert await consent.dentro_da_janela(lid, "email", 24) is False
    assert await consent.motivo_bloqueio(ev) is None
    assert await consent.motivo_bloqueio({**ev, "purpose": "marketing"}) == "sem_registro_de_consentimento"


async def test_constraint_status_e_revoked_at(pg: asyncpg.Connection) -> None:
    lid = await _lead(pg)
    with pytest.raises(asyncpg.CheckViolationError):
        await pg.execute("""INSERT INTO consent_log (lead_id, channel, consent_text, consent_version, source, purpose, status)
                            VALUES ($1, 'whatsapp', 'x', 'v1', 't', 'marketing', 'revoked')""", lid)
    with pytest.raises(asyncpg.CheckViolationError):
        await pg.execute("""INSERT INTO consent_log (lead_id, channel, consent_text, consent_version, source, purpose)
                            VALUES ($1, 'whatsapp', 'x', 'v1', 't', 'promo')""", lid)


async def test_dsar_prazo_15_dias_e_idempotente(pg: asyncpg.Connection) -> None:
    lid = await _lead(pg, market_code="BR")
    a = await consent.abrir_dsar(lid, "whatsapp", "5511999", "quero excluir meus dados", jurisdiction="LGPD")
    assert a["duplicado"] is False and a["status"] == "open"
    assert a["due_at"] - a["received_at"] == timedelta(days=15)
    b = await consent.abrir_dsar(lid, "whatsapp", "5511999", "delete my data")
    assert b["duplicado"] is True and b["id"] == a["id"] and b["due_at"] == a["due_at"]
    row = await pg.fetchrow("SELECT kind, jurisdiction, channel, source_text, lead_id::text AS lead_id FROM data_requests")
    assert dict(row) == {"kind": "erasure", "jurisdiction": "LGPD", "channel": "whatsapp", "source_text": "quero excluir meus dados", "lead_id": lid}
    # concluído o pedido, um novo pode ser aberto
    await pg.execute("UPDATE data_requests SET status = 'completed' WHERE id = $1", a["id"])
    c = await consent.abrir_dsar(lid, "whatsapp", "5511999", "apagar meus dados")
    assert c["duplicado"] is False and c["id"] != a["id"]


# ───────────────────────── 013: suspensão (descadastro fora da lista) ─────────────────────────


async def test_suspensao_ambigua_bloqueia_sem_revogar_e_e_idempotente(pg: asyncpg.Connection) -> None:
    lid = await _lead(pg)
    await consent.registrar_consentimento(lid, "whatsapp", texto="Aceito receber ofertas", idioma="pt")
    a = await consent.suspender_marketing(lid, "whatsapp", texto="STOP please?", idioma="en", classe="ambiguo")
    b = await consent.suspender_marketing(lid, "whatsapp", texto="stop?", idioma="en", classe="ambiguo")
    assert a["nova"] is True and b["nova"] is False and a["id"] == b["id"]
    assert await consent.pode_enviar_marketing(lid, "whatsapp") is False
    assert await consent.confirmacao_pendente(lid, "whatsapp") is not None
    row = await pg.fetchrow("""SELECT status, detection_class, source, awaiting_until - recorded_at AS prazo FROM consent_log
                               WHERE lead_id = $1 AND status = 'suspended'""", lid)
    assert (row["detection_class"], row["source"], row["prazo"]) == ("ambiguo", "whatsapp_fora_da_lista", timedelta(days=7))
    assert await pg.fetchval("SELECT count(*) FROM consent_log WHERE lead_id = $1 AND status = 'active'", lid) == 1  # não revogou


async def test_nao_retoma_e_sim_revoga(pg: asyncpg.Connection) -> None:
    lid = await _lead(pg)
    await consent.registrar_consentimento(lid, "whatsapp", texto="Aceito", idioma="pt")
    await consent.suspender_marketing(lid, "whatsapp", texto="chega", idioma="pt", classe="ambiguo")
    assert await consent.retomar_marketing(lid, "whatsapp", resposta="não") is True
    assert await consent.retomar_marketing(lid, "whatsapp", resposta="não") is False
    assert await consent.pode_enviar_marketing(lid, "whatsapp") is True
    assert await pg.fetchval("SELECT reply_text FROM consent_log WHERE lead_id = $1 AND status = 'lifted'", lid) == "não"

    await consent.suspender_marketing(lid, "whatsapp", texto="parar?", idioma="pt", classe="ambiguo")
    assert await consent.revogar_marketing(lid, "whatsapp", texto="sim", origem="whatsapp_confirmacao", classe="ambiguo", resposta="sim")
    assert await consent.pode_enviar_marketing(lid, "whatsapp") is False
    assert await pg.fetchval("SELECT count(*) FROM consent_log WHERE lead_id = $1 AND status IN ('active', 'suspended')", lid) == 0
    assert await consent.registrar_consentimento(lid, "whatsapp", texto="Quero voltar", idioma="pt") is True  # novo opt-in funciona


async def test_retomar_sem_consentimento_anterior_continua_bloqueado(pg: asyncpg.Connection) -> None:
    lid = await _lead(pg)
    await consent.suspender_marketing(lid, "whatsapp", texto="genug?", idioma="de", classe="ambiguo")
    await consent.retomar_marketing(lid, "whatsapp", resposta="nein")
    assert await consent.pode_enviar_marketing(lid, "whatsapp") is False


async def test_claro_abre_uma_tarefa_humana_e_nao_revoga(pg: asyncpg.Connection) -> None:
    lid = await _lead(pg)
    await consent.registrar_consentimento(lid, "whatsapp", texto="Aceito", idioma="pt")
    s = await consent.suspender_marketing(lid, "whatsapp", texto="parar de mandar mensagem", idioma="pt", classe="claro")
    assert s["awaiting_until"] is None
    a = await consent.abrir_revisao_humana(lid, "whatsapp", resumo="fora da lista")
    b = await consent.abrir_revisao_humana(lid, "whatsapp", resumo="fora da lista")
    assert a and b and a["duplicado"] is False and b["duplicado"] is True and a["escalation_id"] == b["escalation_id"]
    esc = await pg.fetchrow("SELECT trigger_id, severity, status FROM escalations WHERE lead_id = $1", lid)
    assert dict(esc) == {"trigger_id": "consent_review", "severity": "medium", "status": "open"}
    assert await pg.fetchval("SELECT escalation_id::text FROM consent_log WHERE lead_id = $1 AND status = 'suspended'", lid) == a["escalation_id"]
    assert await pg.fetchval("SELECT count(*) FROM consent_log WHERE lead_id = $1 AND status = 'revoked'", lid) == 0


async def test_silencio_mantem_suspenso_e_abre_tarefa_uma_vez(pg: asyncpg.Connection) -> None:
    lid = await _lead(pg)
    await consent.registrar_consentimento(lid, "whatsapp", texto="Aceito", idioma="pt")
    await consent.suspender_marketing(lid, "whatsapp", texto="STOP please?", idioma="en", classe="ambiguo")
    assert await consent.vencer_confirmacoes() == 0  # ainda no prazo
    await pg.execute("UPDATE consent_log SET awaiting_until = now() - interval '1 minute' WHERE lead_id = $1 AND status = 'suspended'", lid)
    assert await consent.confirmacao_pendente(lid, "whatsapp") is None  # "sim"/"não" fora do prazo não valem mais
    assert await consent.vencer_confirmacoes() == 1
    assert await consent.vencer_confirmacoes() == 0
    assert await consent.pode_enviar_marketing(lid, "whatsapp") is False
    assert await pg.fetchval("SELECT count(*) FROM escalations WHERE lead_id = $1 AND trigger_id = 'consent_review'", lid) == 1


async def test_suspender_quem_ja_revogou_nao_cria_linha(pg: asyncpg.Connection) -> None:
    lid = await _lead(pg)
    await consent.revogar_marketing(lid, "whatsapp", texto="STOP")
    s = await consent.suspender_marketing(lid, "whatsapp", texto="stop?", idioma="en", classe="ambiguo")
    assert s["status"] == "revoked" and s["nova"] is False
    assert await pg.fetchval("SELECT count(*) FROM consent_log WHERE lead_id = $1", lid) == 1


async def test_constraints_da_013(pg: asyncpg.Connection) -> None:
    lid = await _lead(pg)
    with pytest.raises(asyncpg.CheckViolationError):
        await pg.execute("""INSERT INTO consent_log (lead_id, channel, consent_text, consent_version, source, purpose, status)
                            VALUES ($1, 'whatsapp', 'x', 'v1', 't', 'marketing', 'lifted')""", lid)  # lifted sem lifted_at
    with pytest.raises(asyncpg.CheckViolationError):
        await pg.execute("""INSERT INTO consent_log (lead_id, channel, consent_text, consent_version, source, purpose, detection_class)
                            VALUES ($1, 'whatsapp', 'x', 'v1', 't', 'marketing', 'outra')""", lid)


async def test_reversao_013(pg: asyncpg.Connection) -> None:
    lid = await _lead(pg)
    await consent.registrar_consentimento(lid, "whatsapp", texto="Aceito", idioma="pt")
    await consent.suspender_marketing(lid, "whatsapp", texto="chega", idioma="pt", classe="ambiguo")
    await pg.execute((ROOT / "db" / "migrations_down" / "013_descadastro_fora_da_lista.sql").read_text())
    cols = {r["column_name"] for r in await pg.fetch("SELECT column_name FROM information_schema.columns WHERE table_name = 'consent_log'")}
    assert not {"detection_class", "awaiting_until", "escalation_id", "lifted_at", "reply_text"} & cols
    assert {r["status"] for r in await pg.fetch("SELECT status FROM consent_log WHERE lead_id = $1", lid)} == {"revoked"}  # falha segura
    await pg.execute((ROOT / "db" / "migrations" / "013_descadastro_fora_da_lista.sql").read_text())  # e volta


async def test_reversao(pg: asyncpg.Connection) -> None:
    await pg.execute((ROOT / "db" / "migrations_down" / "012_consent_log.sql").read_text())
    assert await pg.fetchval("SELECT to_regclass('consent_log')") is None
    cols = {r["column_name"] for r in await pg.fetch("SELECT column_name FROM information_schema.columns WHERE table_name = 'data_requests'")}
    assert not {"channel", "source_text"} & cols
    assert await pg.fetchval("SELECT count(*) FROM rules WHERE rule LIKE 'Descadastro: PARAR, STOP, SAIR%'") == 0
    await pg.execute((ROOT / "db" / "migrations" / "012_consent_log.sql").read_text())  # e volta
    assert await pg.fetchval("SELECT to_regclass('consent_log')") is not None
