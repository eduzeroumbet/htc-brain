"""Revisão estática da máquina (roda sem banco, sem rede): `python -m scripts.check`.

1. Todos os .py compilam.           5. Todo agente do registry tem prompt e renderiza para cada mercado.
2. YAMLs válidos.                   6. Toda ferramenta em `allowed` existe no servidor correspondente.
3. Departamentos ↔ registry ↔ DELEGABLE ↔ budgets coerentes.   7. Scheduler só referencia métodos existentes.
4. Nenhuma credencial/segredo em prompts, knowledge, config, docs.
"""
from __future__ import annotations

import os
import py_compile
import re
import sys
from pathlib import Path

os.environ.setdefault("ANTHROPIC_API_KEY", "x")
os.environ.setdefault("DATABASE_URL", "postgresql://x:x@localhost/x")
os.environ.setdefault("REDIS_URL", "redis://localhost")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
errors: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)
    print("  ✗", msg)


print("1. compilação")
for p in ROOT.rglob("*.py"):
    if "__pycache__" in p.parts:
        continue
    try:
        py_compile.compile(str(p), doraise=True)
    except py_compile.PyCompileError as e:
        err(f"{p.relative_to(ROOT)}: {e.msg}")

print("2. yaml")
import yaml
for p in list((ROOT / "config").rglob("*.yaml")) + list((ROOT / "evals").glob("*.yaml")):
    try:
        yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        err(f"{p.relative_to(ROOT)}: {e}")

print("3. departamentos ↔ registry ↔ delegação ↔ orçamentos")
from brain.core import registry
from brain.tools.company import DELEGABLE
deps = yaml.safe_load((ROOT / "config/departments.yaml").read_text(encoding="utf-8"))
in_depts = {a for d in deps["departments"].values() for a in d["agents"]}
roster = set(registry.ROSTER)
for a in roster - in_depts:
    err(f"agente {a} não está em departments.yaml")
for a in in_depts - roster:
    err(f"departments.yaml cita agente inexistente: {a}")
for name, cls in registry.ROSTER.items():
    dep = next((k for k, d in deps["departments"].items() if name in d["agents"]), None)
    if dep != cls.department:
        err(f"{name}.department={cls.department!r} mas departments.yaml diz {dep!r}")
for a, tasks in DELEGABLE.items():
    if a not in roster:
        err(f"DELEGABLE cita agente inexistente: {a}")
    for t in tasks:
        if not hasattr(registry.ROSTER[a], t):
            err(f"DELEGABLE: {a}.{t} não existe")
for a in deps["delegation"]["ceo"]:
    if a not in DELEGABLE:
        err(f"delegation.ceo cita {a} sem tarefas em DELEGABLE")
if "auditor" in deps["delegation"]["ceo"]:
    err("auditor não pode ser delegável (independência)")
budgets = yaml.safe_load((ROOT / "config/budgets.yaml").read_text(encoding="utf-8"))["tokens"]["per_agent_daily_cap_usd"]
for a in roster - set(budgets):
    err(f"sem orçamento de tokens para {a}")
for a in set(budgets) - roster:
    err(f"orçamento para agente inexistente: {a}")

print("4. segredos")
SECRET_RX = re.compile(r"(jv_live_[A-Za-z0-9]{8,}|sk-ant-[A-Za-z0-9_-]{12,}|sk_live_[A-Za-z0-9]{12,}|EAA[A-Za-z0-9]{40,}|\b\d{3,4}:AA[A-Za-z0-9_-]{30,}|(password|senha|passwd)\s*[:=]\s*['\"]?(?!troque|s\.|settings|os\.|\$|\{|get_|None|<)[A-Za-z0-9!@#%^&*()_+=.,-]{8,})", re.I)
for p in list(ROOT.rglob("*.md")) + list(ROOT.rglob("*.yaml")) + list(ROOT.rglob("*.py")) + list(ROOT.rglob("*.sql")) + [ROOT / ".env.example"]:
    if "__pycache__" in p.parts or not p.exists():
        continue
    for i, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
        if SECRET_RX.search(line) and "SECRET_RX" not in line:
            err(f"possível segredo em {p.relative_to(ROOT)}:{i}")

print("5. prompts renderizam")
from brain.core.prompts import render
from brain.settings import markets_config
markets = list(markets_config())
for name in registry.ROSTER:
    if not (ROOT / "prompts" / f"{name}.md").exists():
        err(f"prompt ausente: prompts/{name}.md")
        continue
    for mc in [None, *markets]:
        try:
            out = render(name, market_code=mc)
            if "{{" in out or "{%" in out or "{agency_name}" in out:
                err(f"prompts/{name}.md ({mc}): template não renderizado por completo")
        except Exception as e:  # noqa: BLE001
            if mc is None and ("market" in str(e) or "'None' has no attribute" in str(e)):
                continue  # prompt exige mercado (consultor, content_studio, seo_site)
            err(f"prompts/{name}.md ({mc}): {type(e).__name__}: {e}")

print("6. ferramentas permitidas existem")
import importlib
servers: dict[str, set[str]] = {}
for mod in ["crm", "catalog", "quotes", "payments", "handoff", "knowledge", "marketing", "ops", "fleet", "admin", "prospects", "billing", "resolution", "audit", "company", "social", "growth", "legal", "partners", "people", "sysops", "mice"]:
    m = importlib.import_module(f"brain.tools.{mod}")
    names = set()
    # Varre o módulo: com o SDK real, @tool devolve SdkMcpTool (.name); sem SDK, a função ganha _tool_meta.
    for obj in vars(m).values():
        meta = getattr(obj, "_tool_meta", None)
        if meta:
            names.add(meta[0])
        elif hasattr(obj, "handler") and isinstance(getattr(obj, "name", None), str):
            names.add(obj.name)
    if not names:  # fallback: config do servidor (versão sem SDK)
        srv = m.server()
        for t in (srv.get("tools", []) if isinstance(srv, dict) else []):
            meta = getattr(t, "_tool_meta", None)
            names.add(meta[0] if meta else getattr(t, "name", str(t)))
    servers[getattr(m, "SERVER", mod)] = names
for name, cls in registry.ROSTER.items():
    for ref in cls.allowed:
        _, srv, tool = ref.split("__", 2)
        if srv not in servers:
            err(f"{name}: servidor desconhecido {srv}")
        elif tool not in servers[srv]:
            err(f"{name}: ferramenta {ref} não existe")
    try:
        declared = set(cls().tools().keys()) if hasattr(cls, "tools") else set()
    except Exception:  # noqa: BLE001
        declared = set()
    for ref in cls.allowed:
        srv = ref.split("__")[1]
        if declared and srv not in declared:
            err(f"{name}: usa {srv} em allowed mas não em tools()")

print("7. scheduler → métodos existentes")
src = (ROOT / "brain/core/scheduler.py").read_text(encoding="utf-8")
for agent, task in re.findall(r'args=\["([a-z_]+)", "([a-z_]+)"\]', src):
    if agent == "_channels":
        continue
    if agent not in registry.ROSTER:
        err(f"scheduler: agente {agent} inexistente")
    elif not hasattr(registry.ROSTER[agent], task):
        err(f"scheduler: {agent}.{task} não existe")

total_tools = sum(len(v) for v in servers.values())
print(f"\n{len(registry.ROSTER)} agentes · {len(deps['departments'])} departamentos · {total_tools} ferramentas · {len(markets)} mercados")
if errors:
    print(f"\n{len(errors)} problema(s).")
    sys.exit(1)
print("\nOK — tudo coerente.")
