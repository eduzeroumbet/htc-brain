"""Redação de segredos e dados pessoais em logs.

- `redact(text)`  — troca tokens, chaves, senhas e cabeçalhos de autorização por ***REDACTED*** e mascara telefones.
- `redact_value` / `redact_event_dict` — processor do structlog (campos com nome sensível viram ***REDACTED*** inteiros).
- `configure()` — liga a redação no structlog (antes e depois de renderizar) e no logging da stdlib (uvicorn).
- `scan_text(text)` — usado por scripts/scan_secrets.py: devolve (linha, padrão) SEM o valor encontrado.

Só biblioteca padrão; structlog é importado dentro de configure().
"""
from __future__ import annotations

import logging
import re
from typing import Any, Iterator

REDACTED = "***REDACTED***"

# (nome, regex). A ordem importa: os específicos antes dos genéricos. Os nomes aparecem nos relatórios; os valores nunca.
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)")),
    ("anthropic_key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{12,}")),
    ("openai_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}")),
    ("stripe_key", re.compile(r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{12,}")),
    ("stripe_webhook_secret", re.compile(r"\bwhsec_[A-Za-z0-9]{16,}")),
    ("jev_key", re.compile(r"\bjv_(?:live|test)_[A-Za-z0-9]{8,}")),
    ("meta_token", re.compile(r"\bEAA[A-Za-z0-9]{30,}")),
    ("telegram_bot_token", re.compile(r"\b(?:bot)?\d{6,12}:AA[A-Za-z0-9_\-]{30,}")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}")),
    ("groq_key", re.compile(r"\bgsk_[A-Za-z0-9]{20,}")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}")),
    ("authorization_header", re.compile(r"(?i)\b(?:authorization|x-huda-token|x-telegram-bot-api-secret-token|cf-access-jwt-assertion)"
                                        r"[\"']?\s*[:=]\s*[\"']?(?:bearer\s+|basic\s+)?[^\s\"',}]{6,}")),
    ("bearer_token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/\-]{16,}=*")),
    ("url_credentials", re.compile(r"(?i)\b[a-z][a-z0-9+.\-]*://[^/\s:@]+:[^/\s@]{3,}@")),
    ("secret_query_param", re.compile(r"(?i)([?&](?:hub\.verify_token|access_token|token|secret|api_key|apikey|key|password)=)[^&\s\"']+")),
    ("secret_assignment", re.compile(r"(?i)\b([A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|TOKEN|API_KEY|AUTH_KEY|PRIVATE_KEY)[A-Z0-9_]*)"
                                     r"(\s*[:=]\s*[\"']?)(?![\"']?\s*(?:$|#|\$\{|None|null|\*\*\*))(?!\d+\b)[^\s\"'#,}]{6,}")),
]
# telefone internacional (E.164 com +): mantém o código do país e os 4 últimos dígitos
PHONE_RX = re.compile(r"(?<![\w+])\+(\d{1,3})[\s\-.]?((?:\d[\s\-.]?){5,11})(\d{4})(?!\d)")

SENSITIVE_KEYS = re.compile(r"(?i)(?:^|_|-)(?:password|passwd|secret|token|api_?key|authorization|cookie|signature|private_?key|credentials?)(?:$|_|-)")


def _sub(name: str, rx: re.Pattern[str], text: str) -> str:
    if name == "secret_query_param":
        return rx.sub(lambda m: m.group(1) + REDACTED, text)
    if name == "secret_assignment":
        return rx.sub(lambda m: m.group(1) + m.group(2) + REDACTED, text)
    return rx.sub(REDACTED, text)


def mask_phones(text: str) -> str:
    return PHONE_RX.sub(lambda m: f"+{m.group(1)}{'*' * 5}{m.group(3)}", text)


def redact(text: str, phones: bool = True) -> str:
    if not text:
        return text
    for name, rx in PATTERNS:
        text = _sub(name, rx, text)
    return mask_phones(text) if phones else text


def redact_value(value: Any, key: str | None = None, phones: bool = True) -> Any:
    if key is not None and SENSITIVE_KEYS.search(key) and value not in (None, "", True, False):
        return REDACTED
    if isinstance(value, str):
        return redact(value, phones)
    if isinstance(value, dict):
        return {k: redact_value(v, str(k), phones) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(redact_value(v, phones=phones) for v in value)
    if isinstance(value, BaseException):
        return redact(f"{type(value).__name__}: {value}")
    return value


def redact_event_dict(logger: Any, method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Processor do structlog: roda antes do renderer."""
    return {k: (v if k in ("level", "timestamp", "logger") else redact_value(v, k)) for k, v in event_dict.items()}


def redact_rendered(logger: Any, method: str, rendered: Any) -> Any:
    """Processor do structlog depois do renderer: última barreira sobre a linha pronta (inclui tracebacks)."""
    return redact(rendered) if isinstance(rendered, str) else rendered


class RedactingFilter(logging.Filter):
    """Filtro da stdlib (uvicorn, httpx, apscheduler): redige a mensagem já formatada."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001
            return True
        clean = redact(msg)
        if clean != msg:
            record.msg, record.args = clean, None
        return True


_configured = False


def configure() -> None:
    """Liga a redação em todo log do processo. Idempotente."""
    global _configured
    if _configured:
        return
    import structlog

    structlog.configure(processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=False),
        structlog.processors.format_exc_info,     # traceback vira texto ANTES da redação
        redact_event_dict,
        structlog.dev.ConsoleRenderer(colors=False),
        redact_rendered,
    ])
    f = RedactingFilter()
    for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access", "httpx", "apscheduler", "asyncio"):
        lg = logging.getLogger(name)
        lg.addFilter(f)
        for h in lg.handlers:
            h.addFilter(f)
    _configured = True


# ───────────────────────── varredura (sem expor valores) ─────────────────────────

def scan_text(text: str, phones: bool = False) -> Iterator[tuple[int, str]]:
    """(número da linha, nome do padrão) para cada achado. Nunca devolve o trecho encontrado."""
    for i, line in enumerate(text.splitlines(), 1):
        for name, rx in PATTERNS:
            if name == "private_key_block":
                if "PRIVATE KEY-----" in line:
                    yield i, name
                continue
            if name == "secret_assignment":
                if (m := rx.search(line)) and REDACTED not in line and not _looks_placeholder(line[m.end(2):]):
                    yield i, name
                continue
            if rx.search(line):
                yield i, name
        if phones and PHONE_RX.search(line):
            yield i, "phone_number"


_PLACEHOLDER_RX = re.compile(r"(?i)^[\"']?(troque|gere-com|um-segredo|outro-segredo|xxx|changeme|your|sua|seu|<|\.\.\.|\$|settings|os\.|get_|s\.|self\.|args|env|config)")


def _looks_placeholder(value: str) -> bool:
    return bool(_PLACEHOLDER_RX.match(value.strip()))
