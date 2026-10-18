"""Acesso ao painel do CEO: senha obrigatória (fail-closed) e autenticação forte na frente dela.

1. Senha de administração (DASHBOARD_PASSWORD): ausente, vazia, só espaços, valor de exemplo ou curta demais
   → o processo NÃO sobe (PanelConfigError na partida → uvicorn sai com código ≠ 0). Nunca há senha padrão.
2. Autenticação forte (PANEL_AUTH_MODE):
     basic       — só HTTP Basic (estado atual; aceito enquanto PANEL_REQUIRE_STRONG_AUTH=false)
     cloudflare  — exige o JWT `Cf-Access-Jwt-Assertion` do Cloudflare Access (RS256, JWKS, iss, aud, exp, nbf)
     tailscale   — exige identidade do Tailscale Serve (`Tailscale-User-Login`) vinda de loopback e na allowlist
   Nos modos fortes o Basic continua exigido por trás (camada extra; nunca é caminho alternativo).
   PANEL_REQUIRE_STRONG_AUTH=true em produção → o processo não sobe em modo basic nem com a config forte incompleta.

Este módulo só usa a biblioteca padrão; a verificação RSA usa `cryptography` (já dependência do projeto) sob demanda.
Mensagens de erro nunca contêm o valor da senha nem do token.
"""
from __future__ import annotations

import base64
import ipaddress
import json
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

MIN_PASSWORD_LENGTH = 12
# valores de exemplo/óbvios que já apareceram em .env.example e docs, ou que qualquer um tentaria
PLACEHOLDERS = {"troque", "changeme", "change-me", "password", "senha", "admin", "ceo", "dashboard", "123456", "12345678",
                "123456789012", "qwerty", "letmein"}
PLACEHOLDER_PREFIXES = ("troque", "gere-com", "change", "sua-senha", "your-password")
MODES = ("basic", "cloudflare", "tailscale")


class PanelConfigError(RuntimeError):
    """Configuração do painel insegura: a máquina não deve subir."""


class PanelAuthError(Exception):
    """Requisição sem identidade forte válida. status = 401 (ausente) ou 403 (inválida/não autorizada)."""

    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


# ───────────────────────── 1. senha de administração ─────────────────────────

def check_admin_password(pw: str | None, min_length: int = MIN_PASSWORD_LENGTH) -> None:
    """Levanta PanelConfigError se a senha não serve. Nunca inclui o valor na mensagem."""
    if pw is None or not pw.strip():
        raise PanelConfigError("DASHBOARD_PASSWORD ausente ou vazia: o painel não sobe sem senha de administração")
    low = pw.strip().lower()
    if low in PLACEHOLDERS or low.startswith(PLACEHOLDER_PREFIXES):
        raise PanelConfigError("DASHBOARD_PASSWORD é um valor de exemplo: gere uma senha aleatória (openssl rand -hex 16)")
    if len(pw) < min_length:
        raise PanelConfigError(f"DASHBOARD_PASSWORD fraca: mínimo de {min_length} caracteres")
    if len(set(pw)) < 6:
        raise PanelConfigError("DASHBOARD_PASSWORD fraca: caracteres repetidos demais")


# ───────────────────────── 2. configuração da autenticação forte ─────────────────────────

@dataclass
class AccessConfig:
    mode: str = "basic"
    require_strong: bool = False
    cf_team_domain: str = ""          # ex.: highclass.cloudflareaccess.com (sem https://)
    cf_aud: str = ""                  # Application Audience (AUD) Tag da aplicação no Zero Trust
    cf_jwks_url: str = ""             # padrão: https://<team>/cdn-cgi/access/certs
    tailscale_allowed: tuple[str, ...] = ()
    leeway_s: int = 30

    @property
    def issuer(self) -> str:
        d = self.cf_team_domain.strip().rstrip("/")
        return d if d.startswith("https://") else f"https://{d}"

    @property
    def jwks_url(self) -> str:
        return self.cf_jwks_url.strip() or f"{self.issuer}/cdn-cgi/access/certs"


def check_access_config(cfg: AccessConfig) -> None:
    """Valida na partida. Modo forte com config incompleta nunca degrada para basic: falha."""
    if cfg.mode not in MODES:
        raise PanelConfigError(f"PANEL_AUTH_MODE inválido (use {', '.join(MODES)})")
    if cfg.mode == "cloudflare" and not (cfg.cf_team_domain.strip() and cfg.cf_aud.strip()):
        raise PanelConfigError("PANEL_AUTH_MODE=cloudflare exige CF_ACCESS_TEAM_DOMAIN e CF_ACCESS_AUD")
    if cfg.mode == "tailscale" and not cfg.tailscale_allowed:
        raise PanelConfigError("PANEL_AUTH_MODE=tailscale exige TAILSCALE_ALLOWED_LOGINS")
    if cfg.require_strong and cfg.mode == "basic":
        raise PanelConfigError("PANEL_REQUIRE_STRONG_AUTH=true: configure PANEL_AUTH_MODE=cloudflare (ou tailscale)")


# ───────────────────────── 3. Cloudflare Access (JWT RS256) ─────────────────────────

def _b64url(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _b64url_int(data: str) -> int:
    return int.from_bytes(_b64url(data), "big")


def _rsa_verify(jwk: dict[str, Any], signing_input: bytes, signature: bytes) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    pub = rsa.RSAPublicNumbers(_b64url_int(jwk["e"]), _b64url_int(jwk["n"])).public_key()
    try:
        pub.verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
        return True
    except InvalidSignature:
        return False


JwksFetcher = Callable[[str], Awaitable[dict[str, Any]]]


async def _httpx_fetch(url: str) -> dict[str, Any]:
    import httpx
    async with httpx.AsyncClient(timeout=5) as c:
        r = await c.get(url)
        r.raise_for_status()
        return r.json()


@dataclass
class CloudflareVerifier:
    """Valida `Cf-Access-Jwt-Assertion`. Chaves vêm do JWKS da equipe (cache de 1 h; kid desconhecido força recarga)."""
    cfg: AccessConfig
    fetch: JwksFetcher = _httpx_fetch
    cache_ttl_s: int = 3600
    _keys: dict[str, dict[str, Any]] = field(default_factory=dict)
    _fetched_at: float = 0.0

    async def _key(self, kid: str, now: float) -> dict[str, Any] | None:
        if kid not in self._keys or now - self._fetched_at > self.cache_ttl_s:
            try:
                jwks = await self.fetch(self.cfg.jwks_url)
            except Exception:  # noqa: BLE001 — JWKS fora do ar → nega (fail-closed), nunca libera
                return self._keys.get(kid) if now - self._fetched_at <= self.cache_ttl_s else None
            self._keys = {k["kid"]: k for k in jwks.get("keys", []) if k.get("kid") and k.get("kty") == "RSA"}
            self._fetched_at = now
        return self._keys.get(kid)

    async def verify(self, token: str | None, now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else now
        if not token:
            raise PanelAuthError(401, "cf_jwt_missing")
        try:
            h64, p64, s64 = token.split(".")
            header, claims, sig = json.loads(_b64url(h64)), json.loads(_b64url(p64)), _b64url(s64)
        except Exception:  # noqa: BLE001
            raise PanelAuthError(403, "cf_jwt_malformed") from None
        if header.get("alg") != "RS256":          # nunca aceitar "none" nem HS256 com chave pública
            raise PanelAuthError(403, "cf_jwt_bad_alg")
        jwk = await self._key(str(header.get("kid") or ""), now)
        if not jwk:
            raise PanelAuthError(403, "cf_jwt_unknown_kid")
        if not _rsa_verify(jwk, f"{h64}.{p64}".encode(), sig):
            raise PanelAuthError(403, "cf_jwt_bad_signature")
        if claims.get("iss") != self.cfg.issuer:
            raise PanelAuthError(403, "cf_jwt_bad_issuer")
        aud = claims.get("aud")
        if self.cfg.cf_aud not in (aud if isinstance(aud, list) else [aud]):
            raise PanelAuthError(403, "cf_jwt_bad_audience")
        exp = claims.get("exp")
        if not isinstance(exp, (int, float)) or exp < now - self.cfg.leeway_s:
            raise PanelAuthError(403, "cf_jwt_expired")
        nbf = claims.get("nbf")
        if isinstance(nbf, (int, float)) and nbf > now + self.cfg.leeway_s:
            raise PanelAuthError(403, "cf_jwt_not_yet_valid")
        return claims


# ───────────────────────── 4. Tailscale Serve ─────────────────────────

def verify_tailscale(client_host: str | None, login: str | None, cfg: AccessConfig) -> str:
    """Tailscale Serve injeta `Tailscale-User-Login` e fala com o backend por loopback.
    Requisição que não veio de loopback pode ter o cabeçalho forjado → nega."""
    try:
        local = bool(client_host) and ipaddress.ip_address(client_host).is_loopback
    except ValueError:
        local = False
    if not local:
        raise PanelAuthError(403, "tailscale_not_loopback")
    if not login:
        raise PanelAuthError(401, "tailscale_identity_missing")
    if login.strip().lower() not in {a.strip().lower() for a in cfg.tailscale_allowed}:
        raise PanelAuthError(403, "tailscale_user_not_allowed")
    return login
