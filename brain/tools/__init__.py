"""Ferramentas internas expostas aos agentes como servidores MCP (Claude Agent SDK).

Cada módulo define funções decoradas com @tool e um `server()` que devolve a config MCP.
Nomes das ferramentas vistos pelo agente: mcp__<server>__<tool>  (ex.: mcp__crm__find_lead).
"""
from __future__ import annotations

import json
from typing import Any, Callable

try:
    from claude_agent_sdk import create_sdk_mcp_server, tool  # type: ignore
    SDK_AVAILABLE = True
except Exception:  # pragma: no cover — permite importar/testar sem o SDK
    SDK_AVAILABLE = False

    def tool(name: str, description: str, schema: Any):  # type: ignore[no-redef]
        def deco(fn: Callable):
            fn._tool_meta = (name, description, schema)  # type: ignore[attr-defined]
            return fn
        return deco

    def create_sdk_mcp_server(name: str, version: str = "1.0.0", tools: list | None = None):  # type: ignore[no-redef]
        return {"type": "sdk", "name": name, "tools": tools or []}


def ok(payload: Any) -> dict[str, Any]:
    """Resposta padrão de ferramenta: JSON serializado em texto."""
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, default=str)}]}


def err(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps({"error": message}, ensure_ascii=False)}], "is_error": True}


def names(server: str, *tools: str) -> tuple[str, ...]:
    return tuple(f"mcp__{server}__{t}" for t in tools)
