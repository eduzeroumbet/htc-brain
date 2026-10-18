"""Payloads de webhook no formato do WhatsApp Cloud API e assinatura X-Hub-Signature-256.

A assinatura é HMAC-SHA256 do corpo BRUTO (os mesmos bytes enviados) com o segredo de TESTE, em hexadecimal,
prefixada por "sha256=" — o mesmo cálculo de brain/channels/whatsapp.verify_signature.
O segredo nunca é gravado nem logado: vem de HTC_E2E_WA_SECRET ou é gerado na execução (efêmero).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any

PHONE_NUMBER_ID = os.environ.get("HTC_E2E_PHONE_NUMBER_ID", "e2e-phone-number-id")
DISPLAY_PHONE = os.environ.get("HTC_E2E_DISPLAY_PHONE", "15550000000")   # sintético; nada é enviado a ele


def wamid() -> str:
    """Identificador único por mensagem, no formato wamid.* (prefixo TEST para nunca colidir com um real)."""
    return "wamid.TEST" + secrets.token_hex(12).upper()


def payload_texto(*, wa_id: str, nome: str, texto: str, message_id: str | None = None,
                  timestamp: float | None = None) -> dict[str, Any]:
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "WABA-E2E-TESTE",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": DISPLAY_PHONE, "phone_number_id": PHONE_NUMBER_ID},
                    "contacts": [{"profile": {"name": nome}, "wa_id": wa_id}],
                    "messages": [{"from": wa_id, "id": message_id or wamid(), "timestamp": str(int(timestamp or time.time())),
                                  "type": "text", "text": {"body": texto}}],
                },
            }],
        }],
    }


def payload_vazio() -> dict[str, Any]:
    """Webhook válido sem mensagens (para pré-voo: não cria lead nem mensagem)."""
    return {"object": "whatsapp_business_account", "entry": []}


def corpo_bruto(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def assinar(corpo: bytes, segredo: str) -> str:
    return "sha256=" + hmac.new(segredo.encode("utf-8"), corpo, hashlib.sha256).hexdigest()


def segredo_de_teste() -> tuple[str, str]:
    """(segredo, origem). Nunca lê .env nem o segredo de produção."""
    s = os.environ.get("HTC_E2E_WA_SECRET", "")
    if s:
        return s, "HTC_E2E_WA_SECRET"
    return secrets.token_hex(32), "efemero (gerado nesta execucao)"
