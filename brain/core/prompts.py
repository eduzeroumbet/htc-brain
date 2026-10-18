"""Carrega e renderiza os prompts de prompts/*.md com Jinja2.

Todo prompt recebe: agency (config/agency.yaml), market (config/markets/XX.yaml quando houver),
today (data em Dubai) e o conteúdo dos arquivos em prompts/_shared/ como variáveis `shared_<nome>`.
"""
from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from brain.settings import PROMPTS_DIR, agency_config, market

_env = Environment(
    loader=FileSystemLoader(str(PROMPTS_DIR)),
    undefined=StrictUndefined,
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
)


@lru_cache
def _shared_names() -> tuple[str, ...]:
    return tuple(sorted(p.stem for p in (PROMPTS_DIR / "_shared").glob("*.md")))


def render(name: str, market_code: str | None = None, **extra: Any) -> str:
    """Renderiza prompts/<name>.md. `market_code` injeta a config do mercado.

    Os arquivos de prompts/_shared/ também são templates: são renderizados com o mesmo contexto
    e entram como `shared_<nome>` no prompt principal.
    """
    agency = agency_config()
    ctx: dict[str, Any] = {
        "agency": agency["agency"],
        "autonomy": agency["autonomy"],
        "policies": agency["policies"],
        "products": agency["products"],
        "kpis": agency["kpis"],
        "market": market(market_code) if market_code else None,
        "today": datetime.now(ZoneInfo(agency["agency"].get("hq_timezone", "Asia/Dubai"))).strftime("%Y-%m-%d"),
        **extra,
    }
    # os _shared podem referenciar uns aos outros (agency_context inclui departments): renderiza em passes
    pending = list(_shared_names())
    for _ in range(len(pending) + 1):
        still = []
        for stem in pending:
            try:
                ctx[f"shared_{stem}"] = _env.get_template(f"_shared/{stem}.md").render(**ctx)
            except Exception:  # noqa: BLE001 — dependência ainda não renderizada
                still.append(stem)
        if not still:
            break
        pending = still
    if pending:  # ciclo ou erro real: renderiza de novo para levantar a exceção certa
        ctx[f"shared_{pending[0]}"] = _env.get_template(f"_shared/{pending[0]}.md").render(**ctx)
    return _env.get_template(f"{name}.md").render(**ctx)


def fill_agency_placeholders(text: str) -> str:
    """Substitui {agency_name} e {det_license_number} em textos dos YAML (saudações, disclosure)."""
    a = agency_config()["agency"]
    return text.replace("{agency_name}", a["name"]).replace("{det_license_number}", a["det_license_number"])
