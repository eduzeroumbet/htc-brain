"""Ambiente de teste local do harness: o app real (brain.main) com banco, fila, Graph API e modelo simulados.

- Settings só do processo (env_file=None: o .env, que pode ter segredos de produção, nunca é lido).
- Banco em memória (FakeDB) que entende só o SQL do caminho webhook → consentimento/DSAR → roteador → consultor;
  SQL inesperado derruba o cenário (nada passa em silêncio). Com --db postgres usa o banco real de teste.
- Fila em memória: inbound vira tarefa imediata (como os 4 consumidores de inbound), outbound passa pelo
  channels.dispatch real (gate de marketing, guarda do Brasil) até o whatsapp.send real, cuja Graph API é um mock.
- Rede real bloqueada: qualquer HTTP fora do mock conta como violação (no modo real só api.anthropic.com passa).
- Modelo: modo offline troca BaseAgent.run por um dublê (roteador sem LLM = Jev e Haiku fora; consultor devolve
  um marcador); modo real chama o modelo de verdade e registra ferramentas usadas.
"""
from __future__ import annotations

import asyncio
import contextvars
import os
import re
import time
import types
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

RESPOSTA_OFFLINE = "[modo offline: resposta do modelo não gerada]"
GRAPH_HOST = "graph.facebook.com"
_msg_atual: contextvars.ContextVar[str | None] = contextvars.ContextVar("e2e_msg_atual", default=None)


# ───────────────────────── banco simulado ─────────────────────────
class FakeDB:
    def __init__(self) -> None:
        self.t = {"leads": [], "conversations": [], "messages": [], "consent_log": [], "data_requests": [],
                  "escalations": [], "agent_runs": [], "quotes": [], "proposal_requests": []}
        self._ultimo = datetime.now(timezone.utc)
        self._seq = 0

    def now(self) -> datetime:
        n = datetime.now(timezone.utc)
        self._ultimo = n if n > self._ultimo else self._ultimo + timedelta(microseconds=1)
        return self._ultimo

    # interface de brain.core.db
    async def fetch(self, sql: str, *a: Any) -> list[dict[str, Any]]:
        return [dict(r) for r in self._run(sql, a)]

    async def fetchrow(self, sql: str, *a: Any) -> dict[str, Any] | None:
        r = self._run(sql, a)
        return dict(r[0]) if r else None

    async def execute(self, sql: str, *a: Any) -> str:
        self._run(sql, a)
        return "OK"

    async def fetchval(self, sql: str, *a: Any) -> Any:
        r = self._run(sql, a)
        return next(iter(r[0].values())) if r else None

    async def pool(self) -> "FakeDB":
        return self

    async def close(self) -> None:
        return None

    def acquire(self) -> "_CM":
        return _CM(self)

    def transaction(self) -> "_CM":
        return _CM(self)

    # ─── SQL ───
    def _lead(self, **kw: Any) -> dict[str, Any] | None:
        return next((r for r in self.t["leads"] if all(r.get(k) == v for k, v in kw.items())), None)

    @staticmethod
    def _cols(s: str, tabela: str) -> list[str]:
        m = re.search(rf"INSERT INTO {tabela} \(([^)]*)\)", s)
        assert m, s
        return [c.strip() for c in m.group(1).split(",")]

    def _set(self, linha: dict[str, Any], atribs: str, a: tuple) -> None:
        for parte in [p.strip() for p in atribs.split(",")]:
            col, val = [x.strip() for x in parte.split("=", 1)]
            if val.startswith("$"):
                linha[col] = a[int(val[1:]) - 1]
            elif val in ("true", "false"):
                linha[col] = val == "true"
            elif val == "now()":
                linha[col] = self.now()
            elif val.startswith("'") and val.endswith("'"):
                linha[col] = val[1:-1]
            else:
                raise AssertionError(f"UPDATE não suportado pelo banco simulado: {parte}")

    def _run(self, sql: str, a: tuple) -> list[dict[str, Any]]:
        s = " ".join(sql.split())
        msgs = self.t["messages"]
        if s.startswith("SELECT * FROM leads WHERE channel = $1 AND channel_user_id = $2"):
            r = self._lead(channel=a[0], channel_user_id=a[1])
            return [r] if r else []
        if s.startswith("SELECT * FROM leads WHERE id = $1"):
            r = self._lead(id=a[0])
            return [r] if r else []
        if s.startswith("INSERT INTO leads ("):
            cols = self._cols(s, "leads")
            vals = dict(zip(cols, a))
            r = self._lead(channel=vals["channel"], channel_user_id=vals["channel_user_id"])
            if r is None:
                r = {"id": str(uuid.uuid4()), "language": None, "market_code": None, "consent_marketing": False, "stage": "new",
                     "vip": False, "created_at": self.now()}
                self.t["leads"].append(r)
            r.update(vals)
            return [r]
        m = re.match(r"UPDATE (leads|conversations) SET (.*) WHERE id = \$1$", s)
        if m:
            tab = self.t[m.group(1)]
            linha = next((r for r in tab if r["id"] == a[0]), None)
            if linha is not None:
                self._set(linha, m.group(2), a)
            return []
        if s.startswith("SELECT * FROM conversations WHERE lead_id = $1 AND status <> 'closed'"):
            cs = sorted((c for c in self.t["conversations"] if c["lead_id"] == a[0] and c["status"] != "closed"),
                        key=lambda c: c["last_message_at"], reverse=True)
            return cs[:1]
        if s.startswith("INSERT INTO conversations (lead_id, channel)"):
            c = {"id": str(uuid.uuid4()), "lead_id": a[0], "channel": a[1], "status": "ai", "agent_session_id": None,
                 "first_response_ms": None, "chatwoot_conversation_id": None, "escalation_trigger": None,
                 "started_at": self.now(), "last_message_at": self.now()}
            self.t["conversations"].append(c)
            return [c]
        if s.startswith("INSERT INTO messages ("):
            self._seq += 1
            msgs.append({**dict(zip(self._cols(s, "messages"), a)), "id": self._seq, "created_at": self.now()})
            return []
        if s.startswith("SELECT count(*) AS n FROM messages WHERE conversation_id = $1 AND direction = 'in' AND created_at > (SELECT max"):
            iguais = [x["created_at"] for x in msgs if x["conversation_id"] == a[0] and x["direction"] == "in" and x["body"] == a[1]]
            if not iguais:
                return [{"n": 0}]
            return [{"n": sum(1 for x in msgs if x["conversation_id"] == a[0] and x["direction"] == "in" and x["created_at"] > max(iguais))}]
        if s.startswith("SELECT body FROM messages WHERE conversation_id = $1 AND direction = 'in' ORDER BY created_at DESC LIMIT 3"):
            rs = sorted((x for x in msgs if x["conversation_id"] == a[0] and x["direction"] == "in"), key=lambda x: x["created_at"], reverse=True)
            return [{"body": x["body"]} for x in rs[:3]]
        if s.startswith("SELECT count(*) AS n FROM messages WHERE conversation_id = $1 AND direction = 'out' AND author NOT LIKE 'ai:%'"):
            lim = self.now() - timedelta(minutes=20)
            return [{"n": sum(1 for x in msgs if x["conversation_id"] == a[0] and x["direction"] == "out"
                              and not str(x["author"]).startswith("ai:") and x["created_at"] > lim)}]
        if s.startswith("SELECT count(*) AS n FROM messages m JOIN conversations c ON c.id = m.conversation_id WHERE c.lead_id = $1 AND m.direction = 'out'"):
            convs = {c["id"] for c in self.t["conversations"] if c["lead_id"] == a[0]}
            return [{"n": sum(1 for x in msgs if x["conversation_id"] in convs and x["direction"] == "out")}]
        if s.startswith("SELECT direction, author, body, created_at FROM messages WHERE conversation_id = $1 ORDER BY created_at DESC LIMIT 14"):
            rs = sorted((x for x in msgs if x["conversation_id"] == a[0]), key=lambda x: x["created_at"], reverse=True)[:14]
            return [{k: x.get(k) for k in ("direction", "author", "body", "created_at")} for x in rs]
        if s.startswith("SELECT m.sentiment FROM messages m JOIN conversations c"):
            convs = {c["id"] for c in self.t["conversations"] if c["lead_id"] == a[0]}
            rs = sorted((x for x in msgs if x["conversation_id"] in convs and x["direction"] == "in"), key=lambda x: x["created_at"], reverse=True)
            return [{"sentiment": x.get("sentiment")} for x in rs[:2]]
        if s.startswith("SELECT pg_advisory_xact_lock"):
            return [{"pg_advisory_xact_lock": None}]
        if re.match(r"SELECT (id, status|status) FROM consent_log WHERE lead_id = \$1 AND channel = \$2 AND purpose = 'marketing'", s):
            rs = [r for r in self.t["consent_log"] if r["lead_id"] == a[0] and r["channel"] == a[1] and r["purpose"] == "marketing"]
            rs.sort(key=lambda r: (r["recorded_at"], r["id"]), reverse=True)
            return rs[:1]
        if s.startswith("UPDATE consent_log SET status = 'revoked', revoked_at = now() WHERE id = $1"):
            for r in self.t["consent_log"]:
                if r["id"] == a[0]:
                    r["status"], r["revoked_at"] = "revoked", self.now()
            return []
        if s.startswith("INSERT INTO consent_log ("):
            cols = self._cols(s, "consent_log")
            vals = dict(zip(cols, a))
            if "'revoked'" in s:
                vals.update(purpose="marketing", status="revoked", revoked_at=self.now())
            else:
                vals.setdefault("status", "active")
                if any(r["lead_id"] == vals["lead_id"] and r["channel"] == vals["channel"] and r["purpose"] == vals["purpose"]
                       and r["status"] == "active" for r in self.t["consent_log"]):
                    return []
            self._seq += 1
            linha = {"id": self._seq, "recorded_at": self.now(), "revoked_at": None, **vals}
            self.t["consent_log"].append(linha)
            return [{"id": linha["id"]}]
        if s.startswith("INSERT INTO data_requests ("):
            lead_id = a[0]
            if any(d["lead_id"] == lead_id and d["kind"] == "erasure" and d["status"] not in ("completed", "refused") for d in self.t["data_requests"]):
                return []
            dias = int(re.search(r"interval '(\d+) days'", s).group(1))  # type: ignore[union-attr]
            agora = self.now()
            d = {"id": str(uuid.uuid4()), "lead_id": lead_id, "requester": a[1], "kind": "erasure", "jurisdiction": a[2],
                 "received_at": agora, "due_at": agora + timedelta(days=dias), "channel": a[3], "source_text": a[4], "status": "open"}
            self.t["data_requests"].append(d)
            return [{k: d[k] for k in ("id", "received_at", "due_at", "status")}]
        if s.startswith("SELECT id, received_at, due_at, status FROM data_requests WHERE lead_id = $1 AND kind = 'erasure'"):
            rs = [d for d in self.t["data_requests"] if d["lead_id"] == a[0] and d["status"] not in ("completed", "refused")]
            return [{k: d[k] for k in ("id", "received_at", "due_at", "status")} for d in rs[-1:]]
        if s.startswith("INSERT INTO agent_runs"):
            self.t["agent_runs"].append({"sql": s[:80], "args": a})
            return []
        raise AssertionError(f"SQL não suportado pelo banco simulado: {s[:140]}")

    # ─── coleta para a avaliação ───
    async def coletar(self, wa_id: str) -> dict[str, Any]:
        lead = self._lead(channel="whatsapp", channel_user_id=wa_id)
        if not lead:
            return {"lead": None, "mensagens": [], "consent": [], "dsar": [], "escalations": [], "quotes": 0, "proposal_requests": 0}
        convs = {c["id"] for c in self.t["conversations"] if c["lead_id"] == lead["id"]}
        return {
            "lead": {k: lead.get(k) for k in ("id", "language", "market_code", "consent_marketing")},
            "mensagens": sorted(({k: m.get(k) for k in ("direction", "author", "body", "created_at", "channel_message_id")}
                                 for m in self.t["messages"] if m["conversation_id"] in convs), key=lambda m: m["created_at"]),
            "consent": [dict(r) for r in self.t["consent_log"] if r["lead_id"] == lead["id"]],
            "dsar": [dict(d) for d in self.t["data_requests"] if d["lead_id"] == lead["id"]],
            "escalations": [dict(e) for e in self.t["escalations"] if e["lead_id"] == lead["id"]],
            "quotes": sum(1 for q in self.t["quotes"] if q["lead_id"] == lead["id"]),
            "proposal_requests": sum(1 for p in self.t["proposal_requests"] if p["lead_id"] == lead["id"]),
        }

    async def contagens_globais(self) -> dict[str, int]:
        return {"rules": 0, "knowledge_chunks": 0}


class _CM:
    def __init__(self, obj: Any) -> None:
        self.obj = obj

    async def __aenter__(self) -> Any:
        return self.obj

    async def __aexit__(self, *exc: Any) -> None:
        return None


class PgColetor:
    """Leitura do banco de TESTE (Postgres) para os efeitos esperados. Nunca escreve nem apaga."""

    def __init__(self, url: str) -> None:
        self.url = url

    async def _con(self) -> Any:
        import asyncpg
        return await asyncpg.connect(self.url)

    async def coletar(self, wa_id: str) -> dict[str, Any]:
        con = await self._con()
        try:
            lead = await con.fetchrow("SELECT id, language, market_code, consent_marketing FROM leads WHERE channel = 'whatsapp' AND channel_user_id = $1", wa_id)
            if not lead:
                return {"lead": None, "mensagens": [], "consent": [], "dsar": [], "escalations": [], "quotes": 0, "proposal_requests": 0}
            lid = lead["id"]
            q = lambda sql: con.fetch(sql, lid)  # noqa: E731
            return {
                "lead": {**dict(lead), "id": str(lid)},
                "mensagens": [dict(r) for r in await q("""SELECT m.direction, m.author, m.body, m.created_at, m.channel_message_id FROM messages m
                                                           JOIN conversations c ON c.id = m.conversation_id WHERE c.lead_id = $1 ORDER BY m.created_at""")],
                "consent": [dict(r) for r in await q("SELECT status, revoked_at, language, source, purpose, channel, recorded_at FROM consent_log WHERE lead_id = $1 ORDER BY recorded_at")],
                "dsar": [dict(r) for r in await q("SELECT kind, status, received_at, due_at, jurisdiction FROM data_requests WHERE lead_id = $1")],
                "escalations": [dict(r) for r in await q("SELECT trigger_id, created_at FROM escalations WHERE lead_id = $1 ORDER BY created_at")],
                "quotes": await con.fetchval("SELECT count(*) FROM quotes WHERE lead_id = $1", lid),
                "proposal_requests": await con.fetchval("SELECT count(*) FROM proposal_requests WHERE lead_id = $1", lid),
            }
        finally:
            await con.close()

    async def contagens_globais(self) -> dict[str, int]:
        con = await self._con()
        try:
            return {"rules": await con.fetchval("SELECT count(*) FROM rules"),
                    "knowledge_chunks": await con.fetchval("SELECT count(*) FROM knowledge_chunks")}
        finally:
            await con.close()


# ───────────────────────── ambiente local ─────────────────────────
class AmbienteLocal:
    """Monta o app real com as trocas acima. Use como `async with AmbienteLocal(...) as amb:`."""

    def __init__(self, *, segredo: str, modo_llm: str = "offline", db_url: str | None = None, escala_tempo: float = 1.0) -> None:
        self.segredo, self.modo_llm, self.db_url, self.escala = segredo, modo_llm, db_url, escala_tempo
        self.fake_db: FakeDB | None = None if db_url else FakeDB()
        self.coletor: Any = PgColetor(db_url) if db_url else self.fake_db
        self.publicados: list[tuple[float, str, dict[str, Any]]] = []
        self.outbound: list[dict[str, Any]] = []        # cada resposta que o cérebro mandou para a fila de saída
        self.graph: list[dict[str, Any]] = []           # chamadas que chegaram à Graph API simulada (dry-run)
        self.rede_bloqueada: list[str] = []             # tentativas de rede real (deve ficar vazio)
        self.erros: dict[str, list[str]] = defaultdict(list)
        self.triagens: dict[str, dict[str, Any]] = {}   # message_id → saída do roteador
        self.llm: list[dict[str, Any]] = []             # chamadas ao modelo (prompt, ferramentas negadas/usadas)
        self.system_prompts: dict[str, str] = {}
        self._tarefas: dict[str, list[asyncio.Task]] = defaultdict(list)
        self._desfazer: list[tuple[Any, str, Any]] = []
        self.client: httpx.AsyncClient | None = None

    def _patch(self, obj: Any, nome: str, valor: Any) -> None:
        self._desfazer.append((obj, nome, getattr(obj, nome)))
        setattr(obj, nome, valor)

    def _configurar_settings(self) -> Any:
        env = {
            "WA_APP_SECRET": self.segredo, "WA_PHONE_NUMBER_ID": os.environ.get("HTC_E2E_PHONE_NUMBER_ID", "e2e-phone-number-id"),
            "WA_ACCESS_TOKEN": "e2e-dry-run-token", "WA_VERIFY_TOKEN": "e2e-verify",
            # a Graph é simulada, então a guarda do Brasil pode ficar desligada aqui para a resposta a +55 chegar ao mock;
            # em produção (flag desligada) ela iria para a rota alternativa — coberto por tests/delivery/test_130497.py
            "WA_BR_DELIVERY_ENABLED": "true", "CEO_WHATSAPP": "", "CHATWOOT_URL": "", "CHATWOOT_API_TOKEN": "",
            "LANGFUSE_PUBLIC_KEY": "", "LANGFUSE_SECRET_KEY": "", "DASHBOARD_PASSWORD": "e2e-teste-nao-usado",
            "META_APP_SECRET": "e2e-meta-teste", "HUDA_WEBHOOK_SECRET": "", "SMTP_HOST": "",
        }
        if self.db_url:
            env["DATABASE_URL"] = self.db_url
        if self.modo_llm == "offline":
            env["ANTHROPIC_API_KEY"] = "e2e-offline"
        for k, v in env.items():
            self._desfazer.append((os.environ, k, os.environ.get(k)))
            os.environ[k] = v
        from brain import settings as st
        self._desfazer.append((st.Settings.model_config, "env_file", st.Settings.model_config.get("env_file")))
        st.Settings.model_config["env_file"] = None   # o .env (segredos de produção) nunca é lido pelo harness
        st.get_settings.cache_clear()
        s = st.get_settings()
        assert s.wa_app_secret == self.segredo and s.wa_access_token == "e2e-dry-run-token"
        return s

    async def __aenter__(self) -> "AmbienteLocal":
        self.settings = self._configurar_settings()
        from brain import main
        from brain.agents.consultant import ConsultantAgent
        from brain.agents.escalation_router import EscalationRouterAgent
        from brain.channels import whatsapp
        from brain.core import agent_base, bus, db, jev, orchestrator
        import brain.channels as channels

        self.app = main.app
        amb = self

        # rede real: bloqueada (o ASGITransport do app não passa por aqui)
        real_handle = httpx.AsyncHTTPTransport.handle_async_request

        async def guarda(transport: Any, request: httpx.Request) -> httpx.Response:
            if amb.modo_llm == "real" and request.url.host == "api.anthropic.com":
                return await real_handle(transport, request)
            amb.rede_bloqueada.append(f"{request.method} {request.url.host}")
            raise RuntimeError(f"rede real bloqueada pelo harness: {request.url.host}")

        self._patch(httpx.AsyncHTTPTransport, "handle_async_request", guarda)
        try:
            import aiosmtplib

            async def smtp_bloqueado(*_a: Any, **_k: Any) -> Any:
                amb.rede_bloqueada.append("smtp")
                raise RuntimeError("SMTP bloqueado pelo harness")
            self._patch(aiosmtplib, "send", smtp_bloqueado)
        except ImportError:
            pass

        # Graph API simulada só para o adaptador do WhatsApp (dry-run: registra e responde 200)
        def graph_handler(request: httpx.Request) -> httpx.Response:
            import json as _json
            body = _json.loads(request.content or b"{}")
            amb.graph.append({"t": time.monotonic(), "host": request.url.host, "path": request.url.path, "to": body.get("to"),
                              "type": body.get("type"), "text": (body.get("text") or {}).get("body")})
            return httpx.Response(200, json={"messages": [{"id": "wamid.DRYRUN" + uuid.uuid4().hex[:12].upper()}]})

        real_client = httpx.AsyncClient
        self._patch(whatsapp, "httpx", types.SimpleNamespace(
            AsyncClient=lambda **kw: real_client(transport=httpx.MockTransport(graph_handler), **kw)))

        # banco
        if self.fake_db is not None:
            for nome in ("fetch", "fetchrow", "execute", "pool", "close"):
                self._patch(db, nome, getattr(self.fake_db, nome))
            self._patch(db, "log_agent_run", self._log_agent_run)
            self._patch(db, "spent_today_usd", self._zero)

        # fila em memória
        async def publish(stream: str, event: dict[str, Any]) -> str:
            t = time.monotonic()
            amb.publicados.append((t, stream, event))
            if stream == bus.INBOUND:
                amb._spawn(event["channel_user_id"], orchestrator.handle_inbound(event))
            elif stream == bus.OUTBOUND:
                amb.outbound.append({**event, "t": t})
                amb._spawn(event["channel_user_id"], channels.dispatch(event))
            return f"{len(amb.publicados)}-0"

        async def rate_limit(key: str, limit: int, window_s: int) -> bool:
            return True

        async def cache_get(key: str) -> Any:
            return None

        async def cache_set(key: str, value: Any, ttl_s: int = 3600) -> None:
            return None

        for nome, fn in (("publish", publish), ("rate_limit", rate_limit), ("cache_get", cache_get), ("cache_set", cache_set)):
            self._patch(bus, nome, fn)

        # registro da triagem e da mensagem em atendimento (para ligar prompt ↔ turno)
        triage_real = EscalationRouterAgent.triage

        async def triage(agent: Any, event: dict[str, Any], lead: Any) -> dict[str, Any]:
            out = await triage_real(agent, event, lead)
            amb.triagens[event.get("message_id") or ""] = out
            return out

        self._patch(EscalationRouterAgent, "triage", triage)
        handle_real = ConsultantAgent.handle_inbound

        async def handle_inbound(agent: Any, event: dict[str, Any], triage: dict[str, Any]) -> None:
            _msg_atual.set(event.get("message_id"))
            await handle_real(agent, event, triage)

        self._patch(ConsultantAgent, "handle_inbound", handle_inbound)

        # modelo
        run_real = agent_base.BaseAgent.run
        if self.modo_llm == "offline":
            self._patch(jev, "JEV_KEY", "")   # Jev fora: triagem pelo caminho degradado (regras + fallback)

        async def run(agent: Any, prompt: str, *, market_code: str | None = None, trigger: str = "manual",
                      resume_session: str | None = None, prompt_ctx: dict[str, Any] | None = None,
                      delegated_by: str | None = None, deny_tools: Any = ()) -> Any:
            reg: dict[str, Any] = {"agente": agent.name, "message_id": _msg_atual.get(), "market_code": market_code,
                                   "prompt": prompt, "deny_tools": sorted(deny_tools), "t": time.monotonic()}
            amb.llm.append(reg)
            if agent.name == "consultant" and market_code and market_code not in amb.system_prompts:
                amb.system_prompts[market_code] = agent.system_prompt(market_code)   # também prova que o template renderiza
            if amb.modo_llm == "offline":
                if agent.name == "consultant":
                    return agent_base.AgentResult(text=RESPOSTA_OFFLINE)
                return agent_base.AgentResult(text="", status="error", error="modelo indisponível no modo offline")
            res = await run_real(agent, prompt, market_code=market_code, trigger=trigger, resume_session=resume_session,
                                 prompt_ctx=prompt_ctx, delegated_by=delegated_by, deny_tools=deny_tools)
            reg.update(texto=res.text, ferramentas=list(res.tool_calls), status=res.status)
            return res

        self._patch(agent_base.BaseAgent, "run", run)

        # escala de tempo (debounce de 6 s e esperas do harness), 1.0 = tempo real
        if self.escala != 1.0:
            sleep_real = asyncio.sleep

            async def sleep(d: float, *a: Any, **k: Any) -> Any:
                return await sleep_real(d * self.escala, *a, **k)
            self._patch(asyncio, "sleep", sleep)

        self.client = real_client(transport=httpx.ASGITransport(app=self.app), base_url="http://e2e.local", timeout=30)
        return self

    async def __aexit__(self, *exc: Any) -> None:
        for ts in self._tarefas.values():
            for t in ts:
                if not t.done():
                    t.cancel()
        if self.client:
            await self.client.aclose()
        for obj, nome, valor in reversed(self._desfazer):
            if isinstance(obj, dict) or obj is os.environ:
                if valor is None:
                    obj.pop(nome, None)
                else:
                    obj[nome] = valor
            else:
                setattr(obj, nome, valor)
        from brain import settings as st
        st.get_settings.cache_clear()

    async def _log_agent_run(self, **fields: Any) -> None:
        return None

    async def _zero(self, *_a: Any) -> float:
        return 0.0

    def _spawn(self, chave: str, coro: Any) -> None:
        async def guardado() -> None:
            try:
                await coro
            except Exception as exc:  # noqa: BLE001 — vira evidência do cenário, não derruba os demais
                self.erros[chave].append(f"{type(exc).__name__}: {str(exc)[:300]}")
        self._tarefas[chave].append(asyncio.get_running_loop().create_task(guardado()))

    async def aguardar(self, chave: str, timeout_s: float) -> bool:
        """Espera as tarefas do contato (inbound → consultor → outbound → dispatch) terminarem. False = estourou."""
        fim = time.monotonic() + timeout_s
        while time.monotonic() < fim:
            pend = [t for t in self._tarefas.get(chave, []) if not t.done()]
            if not pend:
                return True
            await asyncio.wait(pend, timeout=max(0.05, fim - time.monotonic()))
        return not [t for t in self._tarefas.get(chave, []) if not t.done()]

    async def enviar(self, corpo: bytes, assinatura: str | None) -> tuple[int, float]:
        assert self.client is not None
        h = {"Content-Type": "application/json"}
        if assinatura is not None:
            h["X-Hub-Signature-256"] = assinatura
        t0 = time.monotonic()
        r = await self.client.post("/webhooks/whatsapp", content=corpo, headers=h)
        return r.status_code, (time.monotonic() - t0) * 1000
