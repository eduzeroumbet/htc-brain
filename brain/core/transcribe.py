"""Áudio do cliente → texto. WhatsApp Cloud API entrega um media_id; baixamos com o token e transcrevemos.

Provedor: OpenAI Whisper (OPENAI_API_KEY) ou Groq Whisper (GROQ_API_KEY, mais rápido/barato) — o primeiro disponível.
Sem chave: devolve None e a Huda pede, com jeito, para escrever.
"""
from __future__ import annotations

import os
from typing import Any

import httpx
import structlog

from brain.settings import get_settings

log = structlog.get_logger(__name__)
GRAPH = "https://graph.facebook.com/v21.0"


async def download_whatsapp_media(media_id: str) -> tuple[bytes, str] | None:
    s = get_settings()
    headers = {"Authorization": f"Bearer {s.wa_access_token}"}
    async with httpx.AsyncClient(timeout=30) as c:
        meta = await c.get(f"{GRAPH}/{media_id}", headers=headers)
        if meta.status_code >= 400:
            log.error("wa_media_meta_failed", status=meta.status_code, body=meta.text[:200]); return None
        url = meta.json().get("url"); mime = meta.json().get("mime_type", "audio/ogg")
        r = await c.get(url, headers=headers)
        if r.status_code >= 400 or len(r.content) > 25 * 1024 * 1024:
            log.error("wa_media_download_failed", status=r.status_code); return None
        return r.content, mime


async def transcribe(audio: bytes, mime: str, language_hint: str | None = None) -> str | None:
    key, base, model = None, None, None
    if os.getenv("GROQ_API_KEY"):
        key, base, model = os.getenv("GROQ_API_KEY"), "https://api.groq.com/openai/v1", "whisper-large-v3-turbo"
    elif os.getenv("OPENAI_API_KEY"):
        key, base, model = os.getenv("OPENAI_API_KEY"), "https://api.openai.com/v1", "whisper-1"
    if not key:
        return None
    ext = {"audio/ogg": "ogg", "audio/mpeg": "mp3", "audio/mp4": "m4a", "audio/aac": "aac", "audio/amr": "amr", "audio/wav": "wav"}.get(mime.split(";")[0], "ogg")
    data: dict[str, Any] = {"model": model, "response_format": "json"}
    if language_hint and len(language_hint) == 2:
        data["language"] = language_hint
    async with httpx.AsyncClient(timeout=90) as c:
        r = await c.post(f"{base}/audio/transcriptions", headers={"Authorization": f"Bearer {key}"}, data=data, files={"file": (f"audio.{ext}", audio, mime.split(";")[0])})
        if r.status_code >= 400:
            log.error("transcribe_failed", status=r.status_code, body=r.text[:300]); return None
        return (r.json().get("text") or "").strip() or None


async def whatsapp_audio_to_text(media_id: str, language_hint: str | None = None) -> str | None:
    got = await download_whatsapp_media(media_id)
    if not got:
        return None
    return await transcribe(got[0], got[1], language_hint)
