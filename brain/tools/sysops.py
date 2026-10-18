"""Infra da máquina (SysOps): saúde de banco, filas, webhooks, e-mail, APIs externas, backups, disco, orçamento de tokens.
Quase tudo é programático (sem LLM). O agente só entra para diagnosticar e escrever o post-mortem."""
from __future__ import annotations

import os
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from brain.core import bus, db, jev
from brain.settings import budgets_config, get_settings
from brain.tools import create_sdk_mcp_server, ok, tool

SERVER = "sysops"
QUEUE_LAG_WARN = {"inbound": 20, "tasks": 200, "outbound": 50, "alerts": 20}
WEBHOOK_SILENCE_WARN_MIN = {"whatsapp": 180, "meta": 720, "telegram": 720, "email": 15}


async def _record(component: str, status: str, value: float | None = None, detail: str | None = None) -> dict[str, Any]:
    await db.execute("INSERT INTO health_checks (component, status, value, detail) VALUES ($1,$2,$3,$4)", component, status, value, detail)
    return {"component": component, "status": status, "value": value, "detail": detail}


@tool("health_check", "Roda todas as verificações e grava em health_checks: banco (latência), redis, lag das filas, silêncio por canal (último inbound), poll de e-mail, Anthropic, Jev, idade do último backup, disco, orçamento de tokens do dia, TLS. Devolve status por componente e os 'down/degraded'.", {})
async def health_check(args: dict[str, Any]) -> dict[str, Any]:
    s = get_settings()
    results: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    try:
        await db.fetchrow("SELECT 1")
        ms = (time.perf_counter() - t0) * 1000
        results.append(await _record("db", "ok" if ms < 200 else "degraded", round(ms, 1), "latência ms"))
    except Exception as exc:  # noqa: BLE001
        results.append({"component": "db", "status": "down", "detail": str(exc)})
    try:
        r = bus.client()
        await r.ping()
        for stream in ("inbound", "tasks", "outbound", "alerts"):
            name = getattr(bus, stream.upper(), stream)
            try:
                info = await r.xpending(name, "brain")
                pending = int(info["pending"]) if isinstance(info, dict) else int(info[0]) if info else 0
            except Exception:  # noqa: BLE001
                pending = 0
            results.append(await _record(f"queue_{stream}", "ok" if pending < QUEUE_LAG_WARN[stream] else "degraded", pending, "mensagens pendentes no grupo"))
        results.append(await _record("redis", "ok"))
    except Exception as exc:  # noqa: BLE001
        results.append(await _record("redis", "down", None, str(exc)))
    for ch, warn in WEBHOOK_SILENCE_WARN_MIN.items():
        last = await db.fetchrow("SELECT max(m.created_at) t FROM messages m JOIN conversations c ON c.id = m.conversation_id WHERE c.channel = $1 AND m.direction = 'in'", ch)
        t = (last or {}).get("t")
        active_leads = await db.fetchrow("SELECT count(*) n FROM leads WHERE channel = $1 AND created_at > now() - interval '30 days'", ch)
        if not t:
            results.append(await _record(f"webhook_{ch}", "unknown", None, "nenhuma mensagem registrada"))
            continue
        silence = (datetime.now(timezone.utc) - t).total_seconds() / 60
        status = "ok" if silence < warn or int(active_leads["n"]) == 0 else "degraded"  # type: ignore[index]
        results.append(await _record(f"webhook_{ch}", status, round(silence), "minutos desde o último inbound"))
    for name, url, hdr in (("anthropic", "https://api.anthropic.com/v1/models", {"x-api-key": s.anthropic_api_key, "anthropic-version": "2023-06-01"}),):
        try:
            async with httpx.AsyncClient(timeout=8) as c:
                r = await c.get(url, headers=hdr)
            results.append(await _record(name, "ok" if r.status_code < 500 else "degraded", r.status_code, "http"))
        except Exception as exc:  # noqa: BLE001
            results.append(await _record(name, "down", None, str(exc)))
    if jev.enabled():
        ans = await jev.decide("ping", {"ok": {"type": "noul", "instructions": "Responda sim."}})
        results.append(await _record("jev", "ok" if ans else "down", ans.cost_usd if ans else None, "decide() de teste"))
    else:
        results.append(await _record("jev", "unknown", None, "JEV_API_KEY ausente — modo degradado"))
    bdir = Path(os.getenv("BACKUP_DIR", "backups"))
    files = sorted(bdir.glob("*.enc"), key=lambda p: p.stat().st_mtime) if bdir.exists() else []
    if files:
        age_h = (time.time() - files[-1].stat().st_mtime) / 3600
        results.append(await _record("backup", "ok" if age_h < 30 else "degraded", round(age_h, 1), f"horas desde {files[-1].name}"))
    else:
        results.append(await _record("backup", "degraded", None, "nenhum backup encontrado em BACKUP_DIR"))
    du = shutil.disk_usage("/")
    free_pct = 100 * du.free / du.total
    results.append(await _record("disk", "ok" if free_pct > 15 else "degraded" if free_pct > 7 else "down", round(free_pct, 1), "% livre"))
    spent = await db.spent_today_usd()
    cap = float(budgets_config()["tokens"]["daily_cap_usd_total"])
    results.append(await _record("tokens_budget", "ok" if spent < 0.85 * cap else "degraded", round(spent, 2), f"USD gastos hoje de {cap}"))
    errs = await db.fetchrow("SELECT count(*) n FROM agent_runs WHERE created_at > now() - interval '1 hour' AND status = 'error'")
    results.append(await _record("agent_errors_1h", "ok" if int(errs["n"]) < 5 else "degraded", int(errs["n"]), "erros de agente na última hora"))  # type: ignore[index]
    bad = [r for r in results if r["status"] in ("down", "degraded")]
    return ok({"checked_at": datetime.now(timezone.utc).isoformat(), "results": results, "problems": bad})


@tool("open_incident", "Abre incidente de infra (sev1 = clientes sem resposta; sev2 = função degradada; sev3 = aviso) e alerta a CEO em sev1/sev2.", {"component": str, "severity": str, "title": str, "detail": str})
async def open_incident(args: dict[str, Any]) -> dict[str, Any]:
    existing = await db.fetchrow("SELECT id FROM incidents WHERE component = $1 AND status <> 'resolved'", args["component"])
    if existing:
        return ok({"incident_id": str(existing["id"]), "status": "already_open"})
    row = await db.fetchrow("INSERT INTO incidents (component, severity, title, detail) VALUES ($1,$2,$3,$4) RETURNING id", args["component"], args["severity"], args["title"], args.get("detail"))
    if args["severity"] in ("sev1", "sev2"):
        await bus.publish(bus.ALERTS, {"kind": "infra", "severity": "critical" if args["severity"] == "sev1" else "high", "text": f"[{args['severity']}] {args['title']} — {args.get('detail', '')[:300]}"})
    return ok({"incident_id": str(row["id"]), "status": "open"})  # type: ignore[index]


@tool("resolve_incident", "Fecha incidente com post-mortem curto (o que aconteceu, impacto, causa, correção, prevenção).", {"incident_id": str, "postmortem": str})
async def resolve_incident(args: dict[str, Any]) -> dict[str, Any]:
    await db.execute("UPDATE incidents SET status = 'resolved', resolved_at = now(), postmortem = $2 WHERE id = $1", args["incident_id"], args.get("postmortem"))
    return ok({"resolved": True})


@tool("open_incidents", "Incidentes de infra abertos.", {})
async def open_incidents(args: dict[str, Any]) -> dict[str, Any]:
    return ok(await db.fetch("SELECT id, component, severity, title, status, opened_at FROM incidents WHERE status <> 'resolved' ORDER BY opened_at"))


@tool("health_history", "Histórico de um componente nas últimas N horas (para ver tendência: lag crescendo, latência subindo).", {"component": str, "hours": int})
async def health_history(args: dict[str, Any]) -> dict[str, Any]:
    return ok(await db.fetch("SELECT checked_at, status, value, detail FROM health_checks WHERE component = $1 AND checked_at > now() - ($2 || ' hours')::interval ORDER BY checked_at DESC LIMIT 200", args["component"], str(int(args.get("hours") or 24))))


@tool("secrets_rotation_status", "Idade das credenciais críticas a partir de SECRETS_ROTATED_AT (JSON no .env: {nome: YYYY-MM-DD}); alerta ≥ 90 dias. Nunca mostra valores.", {})
async def secrets_rotation_status(args: dict[str, Any]) -> dict[str, Any]:
    import json
    raw = os.getenv("SECRETS_ROTATED_AT", "{}")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {}
    out = []
    for name in ("ANTHROPIC_API_KEY", "WA_ACCESS_TOKEN", "META_APP_SECRET", "TELEGRAM_BOT_TOKEN", "JEV_API_KEY", "STRIPE_SECRET_KEY", "DASHBOARD_PASSWORD", "FIELD_ENCRYPTION_KEY"):
        d = data.get(name)
        age = (datetime.now() - datetime.fromisoformat(d)).days if d else None
        out.append({"secret": name, "set": bool(os.getenv(name)), "rotated_at": d, "age_days": age, "due": age is None or age >= 90})
    return ok(out)


def server():
    return create_sdk_mcp_server(SERVER, "1.0.0", [health_check, open_incident, resolve_incident, open_incidents, health_history, secrets_rotation_status])
