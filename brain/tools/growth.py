"""Analista de Marketing & Tráfego: playbooks por mercado e experimentos test-and-learn dentro do budget.

Semi-autonomia: o analista cria e roda experimentos até o teto de experimentação do mercado (config/budgets.yaml →
media.experiments) sem pedir; canal novo que exige conta/contrato, gasto acima do teto ou mudança de split entre
mercados viram decisão da CEO. O Jev estima a promessa de cada hipótese e decide ganhou/perdeu/inconclusivo.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from brain.core import bus, db, jev
from brain.settings import budgets_config
from brain.tools import create_sdk_mcp_server, err, ok, tool

SERVER = "growth"


def _exp_cfg() -> dict[str, Any]:
    return budgets_config()["media"].get("experiments", {"share_of_market_budget_pct": 25, "max_concurrent_per_market": 2, "min_spend_before_judgement_usd": 40, "default_duration_days": 14})


@tool("get_playbook", "Playbook do mercado: canais B2C (disponível/restrito/bloqueado, CPL estimado), canais B2B, notas legais, pagamento, normas criativas, sazonalidade, concorrentes, perguntas abertas, fontes. knowledge_level diz quanto já sabemos.", {"market_code": str})
async def get_playbook(args: dict[str, Any]) -> dict[str, Any]:
    row = await db.fetchrow("SELECT * FROM market_playbooks WHERE market_code = $1", args["market_code"])
    return ok(row or {"market_code": args["market_code"], "knowledge_level": "none", "hint": "sem playbook — rode research_market e grave com upsert_playbook; a base inicial está em knowledge/markets/<XX>.md (search_knowledge topic='playbook_<xx>')"})


@tool("upsert_playbook", "Grava/atualiza o playbook do mercado (merge por campo; listas substituem). Toda afirmação sobre plataforma bloqueada/permitida ou lei precisa de fonte em sources com data.", {
    "market_code": str, "knowledge_level": str, "b2c_channels": list, "b2b_channels": list, "legal_notes": str, "payment_notes": str, "creative_norms": str, "seasonality": str, "competitors": list, "open_questions": list, "sources": list})
async def upsert_playbook(args: dict[str, Any]) -> dict[str, Any]:
    row = await db.fetchrow(
        """INSERT INTO market_playbooks (market_code, knowledge_level, b2c_channels, b2b_channels, legal_notes, payment_notes, creative_norms, seasonality, competitors, open_questions, sources, updated_by)
           VALUES ($1, coalesce($2,'low'), coalesce($3,'[]'::jsonb), coalesce($4,'[]'::jsonb), $5, $6, $7, $8, coalesce($9,'[]'::jsonb), $10, coalesce($11,'[]'::jsonb), 'ai:market_analyst')
           ON CONFLICT (market_code) DO UPDATE SET version = market_playbooks.version + 1,
             knowledge_level = coalesce(EXCLUDED.knowledge_level, market_playbooks.knowledge_level),
             b2c_channels = CASE WHEN $3 IS NULL THEN market_playbooks.b2c_channels ELSE EXCLUDED.b2c_channels END,
             b2b_channels = CASE WHEN $4 IS NULL THEN market_playbooks.b2b_channels ELSE EXCLUDED.b2b_channels END,
             legal_notes = coalesce(EXCLUDED.legal_notes, market_playbooks.legal_notes), payment_notes = coalesce(EXCLUDED.payment_notes, market_playbooks.payment_notes),
             creative_norms = coalesce(EXCLUDED.creative_norms, market_playbooks.creative_norms), seasonality = coalesce(EXCLUDED.seasonality, market_playbooks.seasonality),
             competitors = CASE WHEN $9 IS NULL THEN market_playbooks.competitors ELSE EXCLUDED.competitors END,
             open_questions = coalesce(EXCLUDED.open_questions, market_playbooks.open_questions),
             sources = CASE WHEN $11 IS NULL THEN market_playbooks.sources ELSE market_playbooks.sources || EXCLUDED.sources END,
             updated_by = 'ai:market_analyst', updated_at = now()
           RETURNING market_code, version, knowledge_level""",
        args["market_code"], args.get("knowledge_level"), args.get("b2c_channels"), args.get("b2b_channels"), args.get("legal_notes"), args.get("payment_notes"),
        args.get("creative_norms"), args.get("seasonality"), args.get("competitors"), args.get("open_questions"), args.get("sources"))
    return ok(row)


@tool("experiment_budget", "Quanto o mercado pode gastar em experimentos agora: teto do mercado (split × teto diário × dias), parcela de experimentação, em uso por experimentos ativos, disponível; limite de experimentos simultâneos.", {"market_code": str})
async def experiment_budget(args: dict[str, Any]) -> dict[str, Any]:
    media = budgets_config()["media"]
    cfg = _exp_cfg()
    split = float(media["split_pct"].get(args["market_code"], 0))
    monthly_market = float(media["monthly_cap_usd"]) * split / 100
    exp_cap = round(monthly_market * float(cfg["share_of_market_budget_pct"]) / 100, 2)
    running = await db.fetch("SELECT id, name, budget_usd, spend_actual_usd, status FROM v_experiment_results WHERE market_code = $1 AND status IN ('approved','running')", args["market_code"])
    committed = sum(float(r["budget_usd"]) for r in running)
    return ok({"market_code": args["market_code"], "market_monthly_budget_usd": round(monthly_market, 2), "experiments_cap_usd": exp_cap, "committed_usd": round(committed, 2),
               "available_usd": round(max(0.0, exp_cap - committed), 2), "running": running, "max_concurrent": cfg["max_concurrent_per_market"],
               "note": "split_pct = 0 → mercado em onda 2: experimentos só com decisão da CEO (kind='market_pilot')"})


@tool("propose_experiment", "Propõe um experimento: hipótese 'Se X então Y porque Z', canal, budget, duração, métrica/alvo e regra de kill. O Jev estima a promessa. Dentro do teto e do limite simultâneo → 'approved' (semi-autônomo); fora → cria decisão da CEO e fica 'proposed'.", {
    "market_code": str, "name": str, "hypothesis": str, "kind": str, "channel": str, "budget_usd": float, "daily_budget_usd": float, "duration_days": int, "success_metric": str, "success_target": float, "kill_rule": str, "requires_new_account": bool})
async def propose_experiment(args: dict[str, Any]) -> dict[str, Any]:
    b = await experiment_budget({"market_code": args["market_code"]})
    import json
    bd = json.loads(b["content"][0]["text"])
    cfg = _exp_cfg()
    ans = await jev.decide({k: args.get(k) for k in ("market_code", "hypothesis", "kind", "channel", "budget_usd", "duration_days", "success_metric", "success_target")}, {
        "promise": {"type": "score", "instructions": "Probabilidade de o experimento atingir o alvo, dado o canal, o mercado e o budget (pequeno demais para aprender? canal saturado? hipótese vaga?)", "criteria": ["improvável", "incerto", "provável", "muito provável"]},
        "well_formed": {"type": "noul", "instructions": "A hipótese é testável (métrica, alvo, prazo, regra de kill claros)?"}})
    promise = round(ans.score("promise"), 3) if ans else None
    if ans and ans.noul("well_formed") < 0.5:
        return err("hipótese mal formada: precisa de métrica, alvo, prazo e regra de kill explícitos")
    autonomous = (float(args["budget_usd"]) <= bd["available_usd"] and len(bd["running"]) < int(bd["max_concurrent"]) and not args.get("requires_new_account") and bd["market_monthly_budget_usd"] > 0)
    status = "approved" if autonomous else "proposed"
    row = await db.fetchrow(
        """INSERT INTO experiments (market_code, name, hypothesis, kind, channel, budget_usd, daily_budget_usd, duration_days, success_metric, success_target, kill_rule, status, jev_promise)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13) RETURNING id""",
        args["market_code"], args["name"], args["hypothesis"], args["kind"], args.get("channel"), float(args["budget_usd"]), args.get("daily_budget_usd"),
        int(args.get("duration_days") or cfg["default_duration_days"]), args["success_metric"], float(args["success_target"]), args.get("kill_rule"), status, promise)
    out = {"experiment_id": str(row["id"]), "status": status, "jev_promise": promise, "available_usd": bd["available_usd"]}  # type: ignore[index]
    if not autonomous:
        reason = "novo canal/conta" if args.get("requires_new_account") else ("mercado em onda 2 (split 0%)" if bd["market_monthly_budget_usd"] == 0 else "acima do teto de experimentação ou limite simultâneo")
        d = await db.fetchrow("""INSERT INTO decisions (kind, context, recommendation, requested_by, amount_usd, market_code) VALUES ('experiment', $1, $2, 'ai:market_analyst', $3, $4) RETURNING id""",
                              f"Experimento {args['name']} ({args['market_code']}, {args.get('channel')}): {args['hypothesis']} — motivo da decisão: {reason}",
                              f"Aprovar USD {float(args['budget_usd']):.0f} por {args.get('duration_days') or cfg['default_duration_days']} dias; promessa Jev {promise}", float(args["budget_usd"]), args["market_code"])
        await db.execute("UPDATE experiments SET decision_id = $2 WHERE id = $1", row["id"], d["id"])  # type: ignore[index]
        await bus.publish(bus.ALERTS, {"kind": "decision", "severity": "medium", "text": f"Experimento aguardando aprovação: {args['name']} ({args['market_code']}) — USD {float(args['budget_usd']):.0f}"})
        out["decision_id"] = str(d["id"])  # type: ignore[index]
    return ok(out)


@tool("start_experiment", "Inicia um experimento 'approved': vincula/cria a campanha (campaign_id existente ou cria registro em campaigns com daily_budget) e marca 'running'.", {"experiment_id": str, "campaign_id": str, "campaign_name": str, "platform": str})
async def start_experiment(args: dict[str, Any]) -> dict[str, Any]:
    e = await db.fetchrow("SELECT * FROM experiments WHERE id = $1", args["experiment_id"])
    if not e or e["status"] not in ("approved",):
        return err("experimento não está 'approved' (aprovação da CEO pendente ou já iniciado)")
    cid = args.get("campaign_id")
    if not cid:
        c = await db.fetchrow("""INSERT INTO campaigns (name, platform, market_code, daily_budget_usd, status, experiment_id) VALUES ($1,$2,$3,$4,'active',$5) RETURNING id""",
                              args.get("campaign_name") or f"EXP · {e['name']}", args.get("platform") or e["channel"], e["market_code"], e["daily_budget_usd"] or round(float(e["budget_usd"]) / e["duration_days"], 2), e["id"])
        cid = str(c["id"])  # type: ignore[index]
    else:
        await db.execute("UPDATE campaigns SET experiment_id = $2 WHERE id = $1", cid, e["id"])
    await db.execute("UPDATE experiments SET status = 'running', campaign_id = $2, started_at = now() WHERE id = $1", e["id"], cid)
    return ok({"experiment_id": str(e["id"]), "campaign_id": cid, "status": "running"})


@tool("experiment_results", "Resultados dos experimentos (running e encerrados nos últimos N dias): gasto real, leads, CPL, reservas, CAC vs alvo, dias corridos, se a regra de kill disparou.", {"market_code": str, "days": int})
async def experiment_results(args: dict[str, Any]) -> dict[str, Any]:
    rows = await db.fetch("""SELECT * FROM v_experiment_results WHERE ($1::text IS NULL OR market_code = $1)
                             AND (status = 'running' OR coalesce(ended_at, created_at) > now() - ($2 || ' days')::interval) ORDER BY status, started_at""", args.get("market_code"), str(int(args.get("days") or 30)))
    cfg = _exp_cfg()
    for r in rows:
        r["days_running"] = (datetime.now(r["started_at"].tzinfo) - r["started_at"]).days if r.get("started_at") else 0
        metric = r["success_metric"]
        val = r.get(metric) if metric in ("cpl_usd", "cac_usd") else None
        r["on_target"] = (float(val) <= float(r["success_target"])) if val is not None else None
        r["enough_spend_to_judge"] = float(r["spend_actual_usd"] or 0) >= float(cfg["min_spend_before_judgement_usd"])
        r["kill_triggered"] = bool(val is not None and r["enough_spend_to_judge"] and float(val) > 2 * float(r["success_target"]))
    return ok(rows)


@tool("close_experiment", "Encerra um experimento com veredito won|lost|inconclusive (o Jev confirma com os números), registra o aprendizado e, se 'won', devolve a recomendação de escala para o Paid Media.", {"experiment_id": str, "verdict": str, "learning": str})
async def close_experiment(args: dict[str, Any]) -> dict[str, Any]:
    r = await db.fetchrow("SELECT * FROM v_experiment_results WHERE id = $1", args["experiment_id"])
    if not r:
        return err("experimento não encontrado")
    verdict = args["verdict"]
    ans = await jev.decide({"metric": r["success_metric"], "target": float(r["success_target"]), "cpl": r.get("cpl_usd"), "cac": r.get("cac_usd"), "spend": float(r["spend_actual_usd"] or 0), "leads": int(r["leads"] or 0), "bookings": int(r["bookings"] or 0), "days": r["duration_days"], "proposed_verdict": verdict},
                           {"verdict": {"type": "choice", "instructions": "Veredito estatisticamente honesto", "criteria": {"won": "bateu o alvo com gasto suficiente", "lost": "ficou claramente fora do alvo com gasto suficiente", "inconclusive": "gasto/leads insuficientes para concluir"}}})
    if ans and ans.choice("verdict") != verdict and ans.confidence("verdict") >= 0.7:
        verdict = ans.choice("verdict") or verdict
    result = {"leads": int(r["leads"] or 0), "cpl_usd": r.get("cpl_usd"), "bookings": int(r["bookings"] or 0), "cac_usd": r.get("cac_usd"), "spend_usd": float(r["spend_actual_usd"] or 0)}
    await db.execute("UPDATE experiments SET status = $2, result = $3, learning = $4, spend_usd = $5, ended_at = now() WHERE id = $1",
                     r["id"], verdict, result, args.get("learning"), result["spend_usd"])
    if r.get("campaign_id") and verdict != "won":
        await db.execute("UPDATE campaigns SET status = 'paused' WHERE id = $1", r["campaign_id"])
    scale = None
    if verdict == "won":
        scale = {"campaign_id": str(r["campaign_id"]) if r.get("campaign_id") else None, "recommendation": "Paid Media: absorver a campanha no orçamento regular do mercado; subir o diário em até 30% por semana enquanto CPL ≤ alvo."}
        await bus.publish(bus.TASKS, {"agent": "paid_media", "task": "optimize", "note": f"Experimento vencedor {r['name']} ({r['market_code']}): escalar campanha {r.get('campaign_id')}"})
    return ok({"experiment_id": str(r["id"]), "verdict": verdict, "result": result, "scale": scale})


@tool("channel_benchmarks", "Benchmarks internos: CPL/CAC por canal e mercado nos últimos N dias (campanhas + experimentos) para comparar com o que o playbook estima.", {"days": int})
async def channel_benchmarks(args: dict[str, Any]) -> dict[str, Any]:
    rows = await db.fetch("""SELECT c.market_code, c.platform, sum(a.spend_usd) spend_usd, sum(a.leads) leads, sum(a.bookings) bookings,
                                    CASE WHEN sum(a.leads) > 0 THEN round(sum(a.spend_usd)/sum(a.leads), 2) END cpl_usd,
                                    CASE WHEN sum(a.bookings) > 0 THEN round(sum(a.spend_usd)/sum(a.bookings), 2) END cac_usd
                             FROM ad_spend_daily a JOIN campaigns c ON c.id = a.campaign_id WHERE a.day > current_date - $1::int GROUP BY 1, 2 ORDER BY 1, cpl_usd NULLS LAST""", int(args.get("days") or 60))
    return ok({"days": int(args.get("days") or 60), "rows": rows, "targets": budgets_config()["media"]["targets_usd"]})


def server():
    return create_sdk_mcp_server(SERVER, "1.0.0", [get_playbook, upsert_playbook, experiment_budget, propose_experiment, start_experiment, experiment_results, close_experiment, channel_benchmarks])
