"""Base de todos os agentes: Claude Agent SDK + orçamento + rastreamento + registro.

Cada agente declara:
  name        — id estável (igual ao prompts/<name>.md e à chave em config/budgets.yaml)
  tier        — "strategy" | "work" | "fast" → modelo (MODEL_STRATEGY / MODEL_WORK / MODEL_FAST)
  department  — departamento (config/departments.yaml)
  tools()     — servidores MCP internos (brain.tools.*) que ele pode usar
  Gate de risco: ferramentas em RISKY_TOOLS passam pelo Jev (PreToolUse) antes de executar.
  allowed     — nomes de ferramentas permitidas (mcp__<server>__<tool>)
  max_turns   — limite de iterações do loop agentico

Uso:
    result = await agent.run("tarefa em texto", market_code="IN", trigger="cron")
    result.text, result.cost_usd, result.session_id
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

import structlog

from brain.core import db, guardrails
from brain.core.prompts import render
from brain.settings import budgets_config, get_settings

log = structlog.get_logger(__name__)

from brain.core import jev

try:  # runtime completo (loop agentico com ferramentas)
    from claude_agent_sdk import (  # type: ignore
        AssistantMessage,
        ClaudeAgentOptions,
        HookMatcher,
        ResultMessage,
        TextBlock,
        ToolUseBlock,
        query,
    )
    SDK_AVAILABLE = True
except Exception:  # pragma: no cover — fallback só texto, sem ferramentas
    SDK_AVAILABLE = False
    HookMatcher = None  # type: ignore

# Ferramentas com efeito no mundo: passam pelo gate de risco do Jev antes de executar (brain/core/jev.tool_risk).
RISKY_TOOLS = {
    "mcp__payments__create_payment_link", "mcp__payments__request_refund", "mcp__quotes__accept_quote", "mcp__quotes__build_quote",
    "mcp__ops__set_booking_status", "mcp__ops__record_rule", "mcp__marketing__set_campaign_budget", "mcp__marketing__pause_campaign",
    "mcp__marketing__review_content", "mcp__handoff__notify_ceo", "mcp__billing__send_billing_reminder", "mcp__billing__mark_payable_paid",
    "mcp__resolution__assign_issue_to_staff", "mcp__prospects__log_outreach", "mcp__company__pause_agent", "mcp__company__decide",
    "mcp__fleet__send_daily_agenda", "mcp__admin__request_quotes_by_email",
}

try:
    from langfuse import Langfuse  # type: ignore
except Exception:  # pragma: no cover
    Langfuse = None  # type: ignore


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class AgentResult:
    text: str
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    session_id: str | None = None
    tool_calls: list[str] = field(default_factory=list)
    status: str = "ok"
    error: str | None = None
    session_lost: bool = False


class BaseAgent:
    name: str = "base"
    department: str = "ceo_office"
    tier: str = "work"
    max_turns: int = 12
    timeout_s: int = 240          # teto de parede por execução; estourou → status "timeout" e resposta de contingência
    allowed: tuple[str, ...] = ()
    permission_mode: str = "bypassPermissions"   # ferramentas internas já são restritas por `allowed`

    def __init__(self) -> None:
        self.settings = get_settings()
        self._langfuse = None
        if Langfuse and self.settings.langfuse_public_key and self.settings.langfuse_secret_key:
            try:
                self._langfuse = Langfuse(
                    public_key=self.settings.langfuse_public_key,
                    secret_key=self.settings.langfuse_secret_key,
                    host=self.settings.langfuse_host or None,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("langfuse_disabled", reason=str(exc)[:200])

    async def _lf(self, fn, *args, **kwargs):
        """Chama o cliente Langfuse fora do event loop com teto de 3 s. Se falhar (serviço fora), desliga o rastreio — nunca trava o atendimento."""
        if not self._langfuse:
            return None
        import asyncio as _asyncio
        try:
            return await _asyncio.wait_for(_asyncio.to_thread(fn, *args, **kwargs), timeout=3)
        except Exception as exc:  # noqa: BLE001
            log.warning("langfuse_disabled", agent=self.name, reason=str(exc)[:200] or type(exc).__name__)
            self._langfuse = None
            return None

    # ───────── pontos de extensão ─────────
    def tools(self) -> dict[str, Any]:
        """Servidores MCP internos {nome: server} (ver brain/tools). Sobrescrever por agente."""
        return {}

    def system_prompt(self, market_code: str | None, **ctx: Any) -> str:
        return render(self.name, market_code=market_code, **ctx)

    # ───────── infra ─────────
    @property
    def model(self) -> str:
        return {
            "strategy": self.settings.model_strategy,
            "work": self.settings.model_work,
            "fast": self.settings.model_fast,
        }[self.tier]

    async def _check_budget(self) -> str:
        """Retorna o modelo a usar; degrada ou bloqueia conforme config/budgets.yaml."""
        b = budgets_config()["tokens"]
        total = await db.spent_today_usd()
        mine = await db.spent_today_usd(self.name)
        cap_total = float(b.get("daily_cap_usd_total", self.settings.daily_token_budget_usd))
        cap_mine = float(b.get("per_agent_daily_cap_usd", {}).get(self.name, cap_total))
        if total >= cap_total or mine >= cap_mine:
            policy = b.get("on_cap_reached", {}).get(self.name, b.get("on_cap_reached", {}).get("default"))
            if policy == "degrade_to_fast_model_then_queue":
                log.warning("budget_degrade", agent=self.name, spent=mine, cap=cap_mine)
                return self.settings.model_fast
            raise BudgetExceeded(f"{self.name}: orçamento diário atingido (USD {mine:.2f} de {cap_mine:.2f})")
        return self.model

    async def _is_paused(self) -> str | None:
        """O CEO-agente pode pausar um agente (company.pause_agent). Atendimento nunca pausa."""
        if self.name in ("consultant", "escalation_router"):
            return None
        try:
            from brain.core import bus
            return await bus.client().get(f"agent_paused:{self.name}")
        except Exception:  # noqa: BLE001
            return None

    # ───────── gate de risco (Jev) ─────────
    async def _pre_tool_use(self, input_data: dict[str, Any], tool_use_id: str | None, context: Any,
                            denied: Iterable[str] = ()) -> dict[str, Any]:
        """Hook PreToolUse do SDK. 1) allowlist no servidor: ferramenta fora de `allowed` (inclusive as nativas do
        Claude Code, liberadas por bypassPermissions) ou em `denied` → nega, com ou sem Jev. 2) RISKY_TOOLS passam
        pelo Jev: block → nega; confirm → nega e pede decisão do CEO; allow → segue."""
        tool_name = input_data.get("tool_name", "")
        reason = guardrails.tool_denied(tool_name, self.allowed, denied)
        if reason:
            log.warning("tool_denied", agent=self.name, tool=tool_name)
            return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                    "permissionDecisionReason": reason}}
        if tool_name not in RISKY_TOOLS or not jev.enabled():
            return {}
        args = json.dumps(input_data.get("tool_input", {}), ensure_ascii=False, default=str)
        ans = await jev.tool_risk(self.name, tool_name, args, self._current_context)
        if not ans:
            return {}
        action = ans.choice("action", "allow")
        risk = ans.score("risk")
        violation = ans.noul("policy_violation")
        log.info("jev_tool_gate", agent=self.name, tool=tool_name, action=action, risk=round(risk, 2), violation=round(violation, 2))
        if action == "block" or violation >= 0.7:
            return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                    "permissionDecisionReason": f"Bloqueado pelo gate de risco (risco {risk:.2f}, violação {violation:.2f}). Não execute; explique ao cliente/CEO e, se fizer sentido, use request_ceo_decision."}}
        if action == "confirm" and risk >= 0.6:
            return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                    "permissionDecisionReason": f"Ação relevante (risco {risk:.2f}) exige decisão humana: registre com request_ceo_decision e informe que aguarda aprovação."}}
        return {}

    _current_context: str = ""

    async def run(
        self,
        prompt: str,
        *,
        market_code: str | None = None,
        trigger: str = "manual",
        resume_session: str | None = None,
        prompt_ctx: dict[str, Any] | None = None,
        delegated_by: str | None = None,
        deny_tools: Iterable[str] = (),
    ) -> AgentResult:
        started = time.perf_counter()
        trace = None
        self._current_context = prompt[:2000]
        paused = await self._is_paused()
        if paused:
            await db.log_agent_run(agent=self.name, department=self.department, market_code=market_code, trigger=trigger,
                                   input_summary=prompt[:500], status="paused", error=paused)
            return AgentResult(text="", status="paused", error=paused)
        try:
            model = await self._check_budget()
        except BudgetExceeded as exc:
            await db.log_agent_run(agent=self.name, department=self.department, market_code=market_code, trigger=trigger,
                                   input_summary=prompt[:500], status="budget_exceeded", error=str(exc))
            return AgentResult(text="", status="budget_exceeded", error=str(exc))

        system = self.system_prompt(market_code, **(prompt_ctx or {}))
        trace = await self._lf(lambda: self._langfuse.trace(name=self.name, metadata={"market": market_code, "trigger": trigger, "model": model}))

        log.info("agent_start", agent=self.name, trigger=trigger, market=market_code, model=model, sdk=SDK_AVAILABLE)
        try:
            import asyncio as _asyncio
            if SDK_AVAILABLE:
                try:
                    result = await _asyncio.wait_for(self._run_sdk(prompt, system, model, resume_session, deny_tools), timeout=self.timeout_s)
                except Exception as exc:  # noqa: BLE001
                    if resume_session and "No conversation found" in str(exc):
                        # sessão do SDK perdida (container recriado): recomeça sem contexto de sessão; o histórico vem do banco
                        log.warning("session_lost_retry", agent=self.name, session=resume_session)
                        result = await _asyncio.wait_for(self._run_sdk(prompt, system, model, None, deny_tools), timeout=self.timeout_s)
                        result.session_lost = True
                    else:
                        raise
            else:
                result = await _asyncio.wait_for(self._run_text_only(prompt, system, model), timeout=self.timeout_s)
        except _asyncio.TimeoutError:
            log.error("agent_timeout", agent=self.name, timeout_s=self.timeout_s)
            result = AgentResult(text="", status="timeout", error=f"sem resposta em {self.timeout_s}s")
        except Exception as exc:  # noqa: BLE001
            log.exception("agent_failed", agent=self.name)
            result = AgentResult(text="", status="error", error=str(exc))

        duration_ms = int((time.perf_counter() - started) * 1000)
        log.info("agent_done", agent=self.name, status=result.status, ms=duration_ms, cost=result.cost_usd, tools=len(result.tool_calls))
        await db.log_agent_run(
            agent=self.name, department=self.department, delegated_by=delegated_by, market_code=market_code, trigger=trigger, model=model,
            input_summary=prompt[:500], output_summary=(result.text or "")[:500], status=result.status,
            tokens_in=result.tokens_in, tokens_out=result.tokens_out, cost_usd=result.cost_usd,
            duration_ms=duration_ms, langfuse_trace_id=getattr(trace, "id", None), error=result.error,
        )
        if trace and self._langfuse:
            lf = self._langfuse
            await self._lf(lambda: (trace.update(output=result.text[:2000], metadata={"cost_usd": result.cost_usd, "tools": result.tool_calls}), lf.flush()))
        return result

    async def _run_sdk(self, prompt: str, system: str, model: str, resume_session: str | None,
                       deny_tools: Iterable[str] = ()) -> AgentResult:
        servers = self.tools()
        denied = frozenset(deny_tools)   # por execução (o agente é compartilhado entre workers concorrentes)

        async def pre_tool_use(input_data: dict[str, Any], tool_use_id: str | None, context: Any) -> dict[str, Any]:
            return await self._pre_tool_use(input_data, tool_use_id, context, denied=denied)

        # o hook roda sempre (allowlist no servidor); o gate do Jev dentro dele só age se o Jev estiver ligado
        hooks = {"PreToolUse": [HookMatcher(matcher=None, hooks=[pre_tool_use])]} if HookMatcher else None
        options = ClaudeAgentOptions(
            system_prompt=system,
            model=model,
            max_turns=self.max_turns,
            allowed_tools=list(self.allowed),
            mcp_servers=servers,  # type: ignore[arg-type]
            permission_mode=self.permission_mode,  # type: ignore[arg-type]
            resume=resume_session,
            setting_sources=[],          # nunca herdar settings do host
            hooks=hooks,  # type: ignore[arg-type]
        )
        out: list[str] = []
        res = AgentResult(text="")
        async for msg in query(prompt=prompt, options=options):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        out.append(block.text)
                    elif isinstance(block, ToolUseBlock):
                        res.tool_calls.append(block.name)
            elif isinstance(msg, ResultMessage):
                res.cost_usd = float(msg.total_cost_usd or 0)
                res.session_id = msg.session_id
                usage = msg.usage or {}
                res.tokens_in = int(usage.get("input_tokens", 0)) + int(usage.get("cache_read_input_tokens", 0))
                res.tokens_out = int(usage.get("output_tokens", 0))
                if msg.is_error:
                    res.status, res.error = "error", str(msg.result)
        res.text = "\n".join(t for t in out if t).strip()
        return res

    async def _run_text_only(self, prompt: str, system: str, model: str) -> AgentResult:
        """Fallback sem ferramentas (Messages API). Mantém a máquina respondendo se o runtime do SDK faltar."""
        from anthropic import AsyncAnthropic  # import tardio

        client = AsyncAnthropic(api_key=self.settings.anthropic_api_key)
        resp = await client.messages.create(
            model=model, max_tokens=2048, system=system, messages=[{"role": "user", "content": prompt}]
        )
        text = "".join(getattr(b, "text", "") for b in resp.content)
        usage = resp.usage
        return AgentResult(text=text, tokens_in=usage.input_tokens, tokens_out=usage.output_tokens,
                           cost_usd=_estimate_cost(model, usage.input_tokens, usage.output_tokens))


def _estimate_cost(model: str, tin: int, tout: int) -> float:
    """Estimativa grosseira por 1M tokens quando o SDK não devolve custo. Ajuste conforme a tabela vigente."""
    table = {"opus": (15.0, 75.0), "sonnet": (3.0, 15.0), "haiku": (1.0, 5.0)}
    for key, (pi, po) in table.items():
        if key in model:
            return round(tin / 1e6 * pi + tout / 1e6 * po, 5)
    return 0.0


def join_prompt(parts: Iterable[str]) -> str:
    return "\n\n".join(p.strip() for p in parts if p and p.strip())
