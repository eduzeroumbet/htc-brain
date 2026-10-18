"""Configuração central: lê .env e os YAML de config/."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
PROMPTS_DIR = ROOT / "prompts"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # infra
    domain: str = Field("localhost", alias="DOMAIN")
    tz: str = Field("Asia/Dubai", alias="TZ")
    database_url: str = Field("postgresql://brain:brain@localhost:5432/brain", alias="DATABASE_URL")
    redis_url: str = Field("redis://localhost:6379/0", alias="REDIS_URL")
    s3_endpoint: str = Field("http://localhost:9000", alias="S3_ENDPOINT")
    s3_bucket_docs: str = Field("docs", alias="S3_BUCKET_DOCS")
    s3_bucket_media: str = Field("media", alias="S3_BUCKET_MEDIA")
    minio_user: str = Field("brain", alias="MINIO_ROOT_USER")
    minio_password: str = Field("", alias="MINIO_ROOT_PASSWORD")

    # modelos
    anthropic_api_key: str = Field("", alias="ANTHROPIC_API_KEY")
    model_strategy: str = Field("claude-opus-5", alias="MODEL_STRATEGY")
    model_work: str = Field("claude-sonnet-5", alias="MODEL_WORK")
    model_fast: str = Field("claude-haiku-4-5-20251001", alias="MODEL_FAST")
    daily_token_budget_usd: float = Field(60.0, alias="DAILY_TOKEN_BUDGET_USD")

    # observabilidade
    langfuse_host: str = Field("", alias="LANGFUSE_HOST")
    langfuse_public_key: str = Field("", alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: str = Field("", alias="LANGFUSE_SECRET_KEY")

    # inbox humana
    chatwoot_url: str = Field("", alias="CHATWOOT_URL")
    chatwoot_api_token: str = Field("", alias="CHATWOOT_API_TOKEN")
    chatwoot_account_id: int = Field(1, alias="CHATWOOT_ACCOUNT_ID")
    chatwoot_human_inbox_id: int | None = Field(None, alias="CHATWOOT_HUMAN_INBOX_ID")

    @field_validator("chatwoot_human_inbox_id", mode="before")
    @classmethod
    def empty_str_to_none(cls, v):  # .env com valor vazio ou comentário inline → None
        if isinstance(v, str) and (not v.strip() or v.strip().startswith("#")):
            return None
        return v

    # canais
    wa_phone_number_id: str = Field("", alias="WA_PHONE_NUMBER_ID")
    wa_access_token: str = Field("", alias="WA_ACCESS_TOKEN")
    wa_verify_token: str = Field("", alias="WA_VERIFY_TOKEN")
    wa_app_secret: str = Field("", alias="WA_APP_SECRET")
    meta_page_id: str = Field("", alias="META_PAGE_ID")
    meta_ig_account_id: str = Field("", alias="META_IG_ACCOUNT_ID")
    meta_page_access_token: str = Field("", alias="META_PAGE_ACCESS_TOKEN")
    meta_verify_token: str = Field("", alias="META_VERIFY_TOKEN")
    meta_app_secret: str = Field("", alias="META_APP_SECRET")
    telegram_bot_token: str = Field("", alias="TELEGRAM_BOT_TOKEN")
    telegram_webhook_secret: str = Field("", alias="TELEGRAM_WEBHOOK_SECRET")
    imap_host: str = Field("", alias="IMAP_HOST")
    imap_user: str = Field("", alias="IMAP_USER")
    imap_password: str = Field("", alias="IMAP_PASSWORD")
    smtp_host: str = Field("", alias="SMTP_HOST")
    smtp_port: int = Field(587, alias="SMTP_PORT")
    smtp_user: str = Field("", alias="SMTP_USER")
    smtp_password: str = Field("", alias="SMTP_PASSWORD")
    smtp_from: str = Field("", alias="SMTP_FROM")
    webchat_signing_secret: str = Field("", alias="WEBCHAT_SIGNING_SECRET")              # sem ele /webhooks/webchat recusa tudo
    webchat_signature_tolerance_s: int = Field(600, alias="WEBCHAT_SIGNATURE_TOLERANCE_SECONDS")   # janela anti-replay
    webchat_max_body_bytes: int = Field(8192, alias="WEBCHAT_MAX_BODY_BYTES")
    webchat_max_text_chars: int = Field(2000, alias="WEBCHAT_MAX_TEXT_CHARS")
    webchat_rate_limit_ip: int = Field(30, alias="WEBCHAT_RATE_LIMIT_IP")                # requisições por IP por janela
    webchat_rate_limit_ip_window_s: int = Field(60, alias="WEBCHAT_RATE_LIMIT_IP_WINDOW_SECONDS")
    webchat_rate_limit_session: int = Field(60, alias="WEBCHAT_RATE_LIMIT_SESSION")      # requisições por sessão por janela
    webchat_rate_limit_session_window_s: int = Field(3600, alias="WEBCHAT_RATE_LIMIT_SESSION_WINDOW_SECONDS")
    huda_webhook_secret: str = Field("", alias="HUDA_WEBHOOK_SECRET")   # Huda (Manus/Evolution) → cérebro

    # WhatsApp para +55: pausado até o teste de entrega passar (erro 130497). Só humano liga; nenhum código liga sozinho.
    wa_br_delivery_enabled: bool = Field(False, alias="WA_BR_DELIVERY_ENABLED")
    wa_br_block_scope: str = Field("all", alias="WA_BR_BLOCK_SCOPE")   # all | proactive_only
    # rota alternativa (config/alt_route.yaml): links oferecidos ao contato; vazio = canal não aparece
    alt_route_webchat_url: str = Field("", alias="ALT_ROUTE_WEBCHAT_URL")
    alt_route_email: str = Field("", alias="ALT_ROUTE_EMAIL")
    alt_route_messenger_url: str = Field("", alias="ALT_ROUTE_MESSENGER_URL")
    alt_route_instagram_handle: str = Field("", alias="ALT_ROUTE_INSTAGRAM_HANDLE")

    # transbordo para humano (brain/core/handoff.py): alerta à equipe e escalonamento quando o SLA vence; vazio = não envia
    handoff_alert_channel: str = Field("email", alias="HANDOFF_ALERT_CHANNEL")             # email | whatsapp | both
    handoff_alert_email_to: str = Field("", alias="HANDOFF_ALERT_EMAIL_TO")                # e-mails separados por vírgula
    handoff_alert_whatsapp_to: str = Field("", alias="HANDOFF_ALERT_WHATSAPP_TO")          # números E.164 separados por vírgula
    handoff_escalation_email_to: str = Field("", alias="HANDOFF_ESCALATION_EMAIL_TO")      # vazio = usa HANDOFF_ALERT_EMAIL_TO
    handoff_escalation_whatsapp_to: str = Field("", alias="HANDOFF_ESCALATION_WHATSAPP_TO")
    handoff_alert_max_attempts: int = Field(5, alias="HANDOFF_ALERT_MAX_ATTEMPTS")
    handoff_alert_timeout_s: float = Field(10.0, alias="HANDOFF_ALERT_TIMEOUT_SECONDS")

    # CEO
    ceo_whatsapp: str = Field("", alias="CEO_WHATSAPP")
    ceo_email: str = Field("", alias="CEO_EMAIL")
    dashboard_password: str = Field("", alias="DASHBOARD_PASSWORD")   # obrigatória: sem ela o processo não sobe

    # painel: autenticação forte na frente do Basic (brain/core/panel_auth.py, docs/SEGURANCA_GATE_FASE2.md)
    panel_auth_mode: str = Field("basic", alias="PANEL_AUTH_MODE")                    # basic | cloudflare | tailscale
    panel_require_strong_auth: bool = Field(False, alias="PANEL_REQUIRE_STRONG_AUTH")  # true em produção após o Access
    cf_access_team_domain: str = Field("", alias="CF_ACCESS_TEAM_DOMAIN")
    cf_access_aud: str = Field("", alias="CF_ACCESS_AUD")
    cf_access_jwks_url: str = Field("", alias="CF_ACCESS_JWKS_URL")
    tailscale_allowed_logins: str = Field("", alias="TAILSCALE_ALLOWED_LOGINS")       # e-mails separados por vírgula

    # pagamentos
    stripe_secret_key: str = Field("", alias="STRIPE_SECRET_KEY")
    stripe_webhook_secret: str = Field("", alias="STRIPE_WEBHOOK_SECRET")             # sem ele /webhooks/stripe recusa tudo
    payment_webhook_tolerance_s: int = Field(300, alias="PAYMENT_WEBHOOK_TOLERANCE_SECONDS")
    tap_secret_key: str = Field("", alias="TAP_SECRET_KEY")

    # fila: retry com backoff exponencial + jitter; esgotado → stream "dlq" (scripts/dlq.py reprocessa)
    queue_max_attempts: int = Field(5, alias="QUEUE_MAX_ATTEMPTS")
    queue_retry_base_delay_s: float = Field(2.0, alias="QUEUE_RETRY_BASE_DELAY_SECONDS")
    queue_retry_max_delay_s: float = Field(600.0, alias="QUEUE_RETRY_MAX_DELAY_SECONDS")
    queue_retry_jitter_ratio: float = Field(0.2, alias="QUEUE_RETRY_JITTER_RATIO")

    # balcão de propostas: lease com fencing token
    proposal_lease_ttl_s: int = Field(300, alias="PROPOSAL_LEASE_TTL_SECONDS")
    proposal_lease_renew_s: int = Field(90, alias="PROPOSAL_LEASE_RENEW_INTERVAL_SECONDS")

    # segurança
    field_encryption_key: str = Field("", alias="FIELD_ENCRYPTION_KEY")
    pii_retention_days_after_trip: int = Field(30, alias="PII_RETENTION_DAYS_AFTER_TRIP")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@lru_cache
def agency_config() -> dict[str, Any]:
    return _load_yaml(CONFIG_DIR / "agency.yaml")


@lru_cache
def escalation_config() -> dict[str, Any]:
    return _load_yaml(CONFIG_DIR / "escalation.yaml")


@lru_cache
def budgets_config() -> dict[str, Any]:
    return _load_yaml(CONFIG_DIR / "budgets.yaml")


@lru_cache
def alt_route_config() -> dict[str, Any]:
    return _load_yaml(CONFIG_DIR / "alt_route.yaml")


@lru_cache
def consent_config() -> dict[str, Any]:
    return _load_yaml(CONFIG_DIR / "consent.yaml")


@lru_cache
def handoff_config() -> dict[str, Any]:
    return _load_yaml(CONFIG_DIR / "handoff.yaml")


@lru_cache
def markets_config() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for p in sorted((CONFIG_DIR / "markets").glob("*.yaml")):
        data = _load_yaml(p)
        out[data["code"]] = data
    return out


def market(code: str) -> dict[str, Any]:
    try:
        return markets_config()[code]
    except KeyError as exc:  # pragma: no cover
        raise ValueError(f"mercado desconhecido: {code}") from exc


def active_markets() -> list[str]:
    return [c for c, m in markets_config().items() if m.get("active")]
