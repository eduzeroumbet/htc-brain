"""Roda os casos de evals/consultant_cases.yaml contra o roteador e o consultor.

Uso: python -m evals.run_evals [--case id] [--report evals/last_report.json]
Sai com código 1 se algum caso obrigatório falhar. Rode antes de qualquer mudança de prompt ir para produção.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import yaml

from brain.core import db, registry

CASES = Path(__file__).parent / "consultant_cases.yaml"


def _check(expect: dict, reply: str, tools: list[str], triage: dict) -> list[str]:
    fails: list[str] = []
    low = reply.lower()
    if "language" in expect and triage.get("language") != expect["language"]:
        fails.append(f"idioma: esperado {expect['language']}, veio {triage.get('language')}")
    for key in ("must_include_any", "must_include_any_2"):
        if key in expect and not any(s.lower() in low for s in expect[key]):
            fails.append(f"{key}: nenhum de {expect[key]}")
    for s in expect.get("must_not_include", []):
        if s.lower() in low:
            fails.append(f"não devia conter: {s!r}")
    for t in expect.get("tools_required", []):
        if t not in tools:
            fails.append(f"ferramenta obrigatória não usada: {t}")
    if "tools_required_any" in expect and not any(t in tools for t in expect["tools_required_any"]):
        fails.append(f"nenhuma das ferramentas usada: {expect['tools_required_any']}")
    for t in expect.get("tools_forbidden", []):
        if t in tools:
            fails.append(f"ferramenta proibida usada: {t}")
    if "max_questions" in expect and reply.count("?") > expect["max_questions"]:
        fails.append(f"perguntas: {reply.count('?')} > {expect['max_questions']}")
    if "max_response_chars" in expect and len(reply) > expect["max_response_chars"]:
        fails.append(f"resposta longa: {len(reply)} chars")
    if "router_intent_any" in expect and triage.get("intent") not in expect["router_intent_any"]:
        fails.append(f"roteador: intenção {triage.get('intent')!r} fora de {expect['router_intent_any']}")
    for t in expect.get("router_triggers", []):
        if t not in [x.split(":")[0] for x in triage.get("triggers", [])]:
            fails.append(f"roteador não detectou gatilho: {t}")
    return fails


async def run(case_filter: str | None, report_path: Path) -> int:
    cases = yaml.safe_load(CASES.read_text(encoding="utf-8"))
    router = registry.get("escalation_router")
    consultant = registry.get("consultant")
    results, failed = [], 0
    for case in cases:
        if case_filter and case["id"] != case_filter:
            continue
        event = {"channel": case["channel"], "channel_user_id": f"eval-{case['id']}", "text": case["message"], "market_code": case["market"]}
        triage = await router.triage(event, {"market_code": case["market"]})  # type: ignore[attr-defined]
        prompt = (f"[contexto] lead_id=eval conversation_id=eval canal={case['channel']} mercado={case['market']} "
                  f"idioma_detectado={triage['language']} intent={triage['intent']} primeira_mensagem=True\n"
                  f"[mensagem do cliente]\n{case['message']}")
        if triage["triggers"]:
            prompt += f"\n\n[SISTEMA: gatilho de escalonamento '{triage['triggers'][0].split(':')[0]}' detectado. Responda com a mensagem-ponte e chame escalate_to_human.]"
        res = await consultant.run(prompt, market_code=case["market"], trigger="manual")
        fails = _check(case["expect"], res.text, res.tool_calls, triage)
        ok = not fails
        failed += 0 if ok else 1
        results.append({"id": case["id"], "ok": ok, "fails": fails, "reply": res.text, "tools": res.tool_calls, "triage": triage, "cost_usd": res.cost_usd})
        print(("PASS " if ok else "FAIL ") + case["id"] + ("" if ok else "  → " + "; ".join(fails)))
    report_path.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    total = len(results)
    print(f"\n{total - failed}/{total} casos ok · custo USD {sum(r['cost_usd'] for r in results):.3f} · relatório: {report_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--case")
    ap.add_argument("--report", default="evals/last_report.json")
    a = ap.parse_args()

    async def main() -> int:
        await db.pool()
        try:
            return await run(a.case, Path(a.report))
        finally:
            await db.close()

    sys.exit(asyncio.run(main()))
