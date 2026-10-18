"""Ponto de entrada: FastAPI com webhooks dos canais, API do dashboard, workers e scheduler no mesmo processo."""
from __future__ import annotations

import asyncio
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from brain.channels import huda, meta_dm, telegram, webchat, whatsapp
from brain.core import db, orchestrator, scheduler
from brain.dashboard.api import router as dashboard_router
from brain.settings import get_settings

log = structlog.get_logger(__name__)
STATIC = Path(__file__).parent / "dashboard" / "static"
security = HTTPBasic()


def require_ceo(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    pw = get_settings().dashboard_password
    if pw and not (secrets.compare_digest(credentials.username, "ceo") and secrets.compare_digest(credentials.password, pw)):
        raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Basic"})
    return credentials.username


async def _knowledge_autoingest() -> None:
    """Na partida: se knowledge/**/*.md mudou desde a última ingestão (hash em Redis), reindexa em segundo plano."""
    import hashlib
    try:
        from brain.core import bus
        from scripts.ingest_knowledge import main as ingest
        files = sorted(Path("knowledge").rglob("*.md"))
        h = hashlib.sha256()
        for f in files:
            h.update(f.read_bytes())
        digest = h.hexdigest()
        if await bus.client().get("knowledge_hash") == digest:
            return
        log.info("knowledge_ingest_start", files=len(files))
        await ingest("knowledge", close_pool=False)
        await bus.client().set("knowledge_hash", digest)
        log.info("knowledge_ingest_done")
    except Exception as exc:  # noqa: BLE001
        log.error("knowledge_ingest_failed", error=str(exc)[:300])


@asynccontextmanager
async def lifespan(app: FastAPI):
    import os
    os.makedirs(os.environ.get("CLAUDE_CONFIG_DIR", "/app/state/claude"), exist_ok=True)  # sessões do SDK persistem no volume
    await db.pool()
    asyncio.create_task(_knowledge_autoingest(), name="knowledge_autoingest")
    app.state.workers = await orchestrator.run_workers()
    app.state.scheduler = scheduler.build()
    app.state.scheduler.start()
    log.info("brain_up")
    try:
        yield
    finally:
        app.state.scheduler.shutdown(wait=False)
        for t in app.state.workers:
            t.cancel()
        await asyncio.gather(*app.state.workers, return_exceptions=True)
        await db.close()


app = FastAPI(title="brain — agência 100% IA", version="0.1.0", lifespan=lifespan, docs_url=None, redoc_url=None)
app.include_router(dashboard_router, prefix="/api", dependencies=[Depends(require_ceo)])


@app.get("/docs/{key:path}")
async def serve_doc(key: str) -> FileResponse:
    """PDFs de cotação/voucher gravados em disco local (quando não há object store) — links enviados ao cliente."""
    from pathlib import Path
    base = Path("/app/state/docs").resolve()
    path = (base / key).resolve()
    if base not in path.parents or not path.is_file():
        raise HTTPException(404)
    return FileResponse(str(path), media_type="application/pdf")


@app.get("/api/debug/tasks", response_class=PlainTextResponse, dependencies=[Depends(require_ceo)])
async def debug_tasks() -> str:
    """Diagnóstico: onde cada tarefa assíncrona está parada (stack das corrotinas). Só CEO."""
    import traceback
    out: list[str] = []
    for t in asyncio.all_tasks():
        name = t.get_name()
        coro = getattr(t.get_coro(), "__qualname__", str(t.get_coro()))
        frames = t.get_stack(limit=12)
        out.append(f"=== {name} · {coro} · done={t.done()}")
        for f in frames:
            out.append("".join(traceback.format_stack(f, limit=1)).rstrip())
    return "\n".join(out)


@app.get("/healthz", response_class=PlainTextResponse)
async def healthz() -> str:
    await db.fetchrow("SELECT 1")
    return "ok"


# ───────────────────────── dashboard ─────────────────────────
@app.get("/", dependencies=[Depends(require_ceo)])
async def dashboard() -> FileResponse:
    return FileResponse(STATIC / "index.html")


# ───────────────────────── WhatsApp Cloud API ─────────────────────────
@app.get("/webhooks/whatsapp")
async def wa_verify(request: Request) -> Response:
    q = request.query_params
    if q.get("hub.mode") == "subscribe" and q.get("hub.verify_token") == get_settings().wa_verify_token:
        return PlainTextResponse(q.get("hub.challenge", ""))
    raise HTTPException(403)


@app.post("/webhooks/whatsapp")
async def wa_webhook(request: Request) -> dict:
    body = await request.body()
    if not whatsapp.verify_signature(body, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(401)
    n = await whatsapp.handle_webhook(await request.json())
    return {"queued": n}


# ───────────────────────── Messenger + Instagram ─────────────────────────
@app.get("/webhooks/meta")
async def meta_verify(request: Request) -> Response:
    q = request.query_params
    if q.get("hub.mode") == "subscribe" and q.get("hub.verify_token") == get_settings().meta_verify_token:
        return PlainTextResponse(q.get("hub.challenge", ""))
    raise HTTPException(403)


@app.post("/webhooks/meta")
async def meta_webhook(request: Request) -> dict:
    body = await request.body()
    if not meta_dm.verify_signature(body, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(401)
    n = await meta_dm.handle_webhook(await request.json())
    return {"queued": n}


# ───────────────────────── Telegram ─────────────────────────
@app.post("/webhooks/telegram")
async def tg_webhook(request: Request) -> dict:
    secret = get_settings().telegram_webhook_secret
    if secret and request.headers.get("X-Telegram-Bot-Api-Secret-Token") != secret:
        raise HTTPException(401)
    n = await telegram.handle_webhook(await request.json())
    return {"queued": n}


# ───────────────────────── Huda (WhatsApp já em operação — Manus WebDev + Evolution) ─────────────────────────
@app.post("/webhooks/huda")
async def huda_webhook(request: Request) -> dict:
    if not huda.verify(request.headers.get("X-Huda-Token")):
        raise HTTPException(401)
    return await huda.handle(await request.json())


# ───────────────────────── Webchat ─────────────────────────
@app.post("/webhooks/webchat")
async def webchat_webhook(request: Request) -> dict:
    n = await webchat.handle_post(await request.json())
    return {"queued": n}


@app.get("/webchat/stream/{session_id}")
async def webchat_stream(session_id: str) -> StreamingResponse:
    return StreamingResponse(webchat.stream(session_id), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ───────────────────────── Público: dados para o site (bloco "Dubai em 2026") ─────────────────────────
@app.get("/public/dubai-now.json")
async def dubai_now() -> Response:
    """Números da semana que o site lê sem autenticação. O Market Intel grava o topic 'dubai_now' (JSON) todo dia às 05:00."""
    import json as _json
    row = await db.fetchrow(
        "SELECT content, source_url, source_date FROM knowledge_chunks WHERE topic = 'dubai_now' AND market_code IS NULL ORDER BY created_at DESC LIMIT 1")
    payload: dict = {"updated": None, "items": [], "source": None}
    if row:
        try:
            payload = _json.loads(row["content"])
        except Exception:  # noqa: BLE001 — conteúdo em texto
            payload = {"updated": str(row["source_date"]), "items": [{"label": "Resumo", "value": row["content"][:400]}], "source": row["source_url"]}
    return Response(content=_json.dumps(payload, ensure_ascii=False), media_type="application/json",
                    headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=3600"})


# ───────────────────────── Pagamentos (webhooks dos gateways) ─────────────────────────
@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request) -> dict:
    """Confirma pagamento → atualiza reserva e avisa o consultor para seguir com a confirmação."""
    payload = await request.json()
    if payload.get("type") in ("checkout.session.completed", "payment_link.completed", "charge.succeeded"):
        obj = payload["data"]["object"]
        ref = (obj.get("metadata") or {}).get("booking_ref")
        amount = float(obj.get("amount_total") or obj.get("amount") or 0) / 100
        if ref:
            await db.execute(
                """UPDATE bookings SET paid_usd = paid_usd + $2,
                     payment_status = CASE WHEN paid_usd + $2 >= total_usd THEN 'paid' ELSE 'deposit' END
                   WHERE ref = $1""", ref, amount)
            from brain.core import bus, registry
            b = await db.fetchrow("SELECT id FROM bookings WHERE ref = $1", ref)
            if b:
                await registry.get("finance").on_payment_event(str(b["id"]), amount, "charge")  # type: ignore[attr-defined]  # baixa a fatura (A/R)
            await bus.publish(bus.TASKS, {"agent": "booking_payments", "task": "confirm_pending"})
    return {"ok": True}
