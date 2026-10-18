"""Verificação do webhook de pagamento: HMAC-SHA256 sobre o corpo BRUTO, tempo constante, tolerância de timestamp.

Formato implementado: o do Stripe (`Stripe-Signature: t=<unix>,v1=<hex>[,v1=<hex>]`, assinatura de "<t>.<corpo>"),
porque /webhooks/stripe é a única rota de pagamento que existe no código. Outro provedor (Tap etc.) precisa de
um verificador próprio seguindo a documentação dele — não reaproveitar este formato.

Regras:
- sem segredo configurado → rejeita sempre (a rota fica desligada; nunca "aceita em dev");
- cabeçalho ausente/malformado, assinatura errada ou timestamp fora da janela → SignatureError (a rota responde 401/403);
- só depois de verificado o corpo é desserializado.
A idempotência por ID de evento fica no banco (tabela payment_webhook_events, migração 012), na mesma transação do efeito.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

DEFAULT_TOLERANCE_S = 300


class SignatureError(Exception):
    """Webhook recusado. 401 = assinatura ausente; 403 = inválida/fora da janela; 400 = autêntico mas sem evento válido."""

    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


def sign(raw_body: bytes, secret: str, timestamp: int) -> str:
    """Gera o cabeçalho no formato do provedor (usado nos testes e no roteiro de teste manual)."""
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + raw_body, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={mac}"


def _parse(header: str) -> tuple[int, list[str]]:
    ts: int | None = None
    sigs: list[str] = []
    for part in header.split(","):
        k, _, v = part.strip().partition("=")
        if k == "t":
            ts = int(v)
        elif k == "v1" and v:
            sigs.append(v)
    if ts is None or not sigs:
        raise ValueError("cabeçalho incompleto")
    return ts, sigs


def verify(raw_body: bytes, header: str | None, secret: str, tolerance_s: int = DEFAULT_TOLERANCE_S,
           now: float | None = None) -> dict[str, Any]:
    """Devolve o evento (dict) se autêntico; senão levanta SignatureError. Nada é processado antes disto."""
    if not secret or not secret.strip():
        raise SignatureError(403, "webhook_secret_not_configured")
    if not header:
        raise SignatureError(401, "signature_missing")
    try:
        ts, sigs = _parse(header)
    except (ValueError, TypeError):
        raise SignatureError(403, "signature_malformed") from None
    now = time.time() if now is None else now
    if tolerance_s <= 0 or abs(now - ts) > tolerance_s:   # tolerância sempre finita
        raise SignatureError(403, "timestamp_out_of_tolerance")
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + raw_body, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, s) for s in sigs):
        raise SignatureError(403, "signature_invalid")
    try:
        event = json.loads(raw_body)
    except ValueError:
        raise SignatureError(400, "body_not_json") from None
    if not isinstance(event, dict) or not isinstance(event.get("id"), str) or not event["id"]:
        raise SignatureError(400, "event_id_missing")
    return event
