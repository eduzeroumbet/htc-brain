"""Auditoria independente: SLAs medidos no banco, conformidade de fluxo por reserva, achados e notas Jev."""
from __future__ import annotations

from typing import Any

from brain.core import db, jev
from brain.settings import agency_config
from brain.tools import create_sdk_mcp_server, ok, tool

SERVER = "audit"

SLA_TARGETS = {  # metric → (target, janela h, sentido)
    "first_response_s": (60, 24, "max"),
    "quote_pdf_min": (15, 24, "max"),
    "escalation_ack_min": (60, 24, "max"),
    "supplier_confirm_min": (120, 48, "max"),
    "issue_resolution_h": (24, 72, "max"),
    "followup_sent_pct": (90, 168, "min"),
}


@tool("sla_metrics", "Mede os SLAs reais nas últimas janelas: 1ª resposta (p50/p95 s), cotação→PDF (min), escalonamento até humano assumir (min), reserva→confirmação do fornecedor (min), problema→resolução (h), follow-ups devidos vs enviados. Grava em sla_checks e devolve violações.", {})
async def sla_metrics(args: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    fr = await db.fetchrow("""SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY first_response_ms)/1000.0 p50, percentile_cont(0.95) WITHIN GROUP (ORDER BY first_response_ms)/1000.0 p95, count(*) n
                              FROM conversations WHERE started_at > now() - interval '24 hours' AND first_response_ms IS NOT NULL""")
    out["first_response_s"] = {"p50": fr["p50"], "p95": fr["p95"], "n": fr["n"]}  # type: ignore[index]
    qp = await db.fetchrow("""SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch from (pdf_rendered_at - created_at))/60) p50, count(*) n
                              FROM quotes WHERE created_at > now() - interval '24 hours' AND pdf_rendered_at IS NOT NULL""")
    out["quote_pdf_min"] = {"p50": qp["p50"], "n": qp["n"]}  # type: ignore[index]
    ea = await db.fetchrow("""SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch from (acknowledged_at - opened_at))/60) p50,
                                     count(*) FILTER (WHERE acknowledged_at IS NULL AND opened_at < now() - interval '60 minutes') unacked, count(*) n
                              FROM escalations WHERE opened_at > now() - interval '24 hours'""")
    out["escalation_ack_min"] = {"p50": ea["p50"], "unacked_over_60min": ea["unacked"], "n": ea["n"]}  # type: ignore[index]
    sc = await db.fetchrow("""SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch from (confirmed_at - created_at))/60) p50,
                                     count(*) FILTER (WHERE status = 'confirming' AND created_at < now() - interval '120 minutes') stuck, count(*) n
                              FROM bookings WHERE created_at > now() - interval '48 hours'""")
    out["supplier_confirm_min"] = {"p50": sc["p50"], "stuck_over_120min": sc["stuck"], "n": sc["n"]}  # type: ignore[index]
    ir = await db.fetchrow("""SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch from (resolved_at - opened_at))/3600) p50,
                                     count(*) FILTER (WHERE status NOT IN ('resolved','cancelled') AND due_at < now()) overdue, count(*) n
                              FROM issues WHERE opened_at > now() - interval '72 hours'""")
    out["issue_resolution_h"] = {"p50": ir["p50"], "overdue": ir["overdue"], "n": ir["n"]}  # type: ignore[index]
    fu = await db.fetchrow("""SELECT count(*) FILTER (WHERE stage IN ('quoted','negotiating') AND updated_at < now() - interval '26 hours'
                                     AND NOT EXISTS (SELECT 1 FROM messages m JOIN conversations c ON c.id = m.conversation_id WHERE c.lead_id = leads.id AND m.direction = 'out' AND m.created_at > now() - interval '26 hours')) missing,
                                     count(*) FILTER (WHERE stage IN ('quoted','negotiating')) n FROM leads WHERE updated_at > now() - interval '7 days'""")
    n = int(fu["n"] or 0)  # type: ignore[index]
    out["followup_sent_pct"] = {"pct": round(100 * (1 - int(fu["missing"] or 0) / n), 1) if n else None, "missing": fu["missing"], "n": n}  # type: ignore[index]

    breaches = []
    checks = [("first_response_s", out["first_response_s"]["p95"]), ("quote_pdf_min", out["quote_pdf_min"]["p50"]), ("escalation_ack_min", out["escalation_ack_min"]["p50"]),
              ("supplier_confirm_min", out["supplier_confirm_min"]["p50"]), ("issue_resolution_h", out["issue_resolution_h"]["p50"]), ("followup_sent_pct", out["followup_sent_pct"]["pct"])]
    for metric, value in checks:
        target, window, sense = SLA_TARGETS[metric]
        if value is None:
            continue
        breached = float(value) > target if sense == "max" else float(value) < target
        await db.execute("INSERT INTO sla_checks (metric, window_hours, value, target, breached, detail) VALUES ($1,$2,$3,$4,$5,$6)",
                         metric, window, float(value), target, breached, {k: (float(v) if isinstance(v, (int, float)) or hasattr(v, "quantize") else v) for k, v in out[metric].items() if v is not None})
        if breached:
            breaches.append({"metric": metric, "value": value, "target": target})
    hard = {"unacked_escalations": out["escalation_ack_min"]["unacked_over_60min"], "stuck_bookings": out["supplier_confirm_min"]["stuck_over_120min"], "overdue_issues": out["issue_resolution_h"]["overdue"]}
    return ok({"metrics": out, "breaches": breaches, "hard_counts": hard})


@tool("flow_conformance", "Para reservas dos últimos N dias, verifica se o fluxo padrão foi seguido na ordem: lead qualificado → cotação → PDF → aceite → pagamento → confirmação fornecedor → emissão → serviços de campo → concierge D-1. Devolve por reserva as etapas faltantes/fora de ordem.", {"days": int})
async def flow_conformance(args: dict[str, Any]) -> dict[str, Any]:
    days = int(args.get("days") or 7)
    rows = await db.fetch(
        """SELECT b.id, b.ref, b.status, b.created_at, b.travel_start, b.confirmed_at,
                  q.created_at AS quote_at, q.pdf_rendered_at, q.accepted_at,
                  (SELECT min(created_at) FROM payments p WHERE p.booking_id = b.id AND p.kind = 'charge' AND p.status = 'succeeded') AS paid_at,
                  (SELECT count(*) FROM issuances i WHERE i.booking_id = b.id AND i.status IN ('issued','reissued')) AS issued_n,
                  (SELECT count(*) FROM issuances i WHERE i.booking_id = b.id) AS issuance_n,
                  (SELECT count(*) FROM field_assignments f WHERE f.booking_id = b.id AND f.kind <> 'issue_resolution') AS field_n,
                  (SELECT bool_or(items::text ILIKE '%transfer%' OR items::text ILIKE '%tour%') FROM bookings bb WHERE bb.id = b.id) AS needs_field,
                  (SELECT count(*) FROM messages m JOIN conversations c ON c.id = m.conversation_id WHERE c.lead_id = b.lead_id AND m.author = 'ai:concierge') AS concierge_msgs
           FROM bookings b LEFT JOIN quotes q ON q.id = b.quote_id
           WHERE b.created_at > now() - ($1 || ' days')::interval ORDER BY b.created_at DESC""", str(days))
    report = []
    for r in rows:
        gaps = []
        if not r["quote_at"]:
            gaps.append("sem cotação vinculada")
        if r["quote_at"] and not r["pdf_rendered_at"]:
            gaps.append("cotação sem PDF")
        if not r["accepted_at"]:
            gaps.append("aceite não registrado")
        if r["paid_at"] and r["accepted_at"] and r["paid_at"] < r["accepted_at"]:
            gaps.append("pagamento antes do aceite")
        if r["status"] in ("confirmed", "in_trip", "completed") and not r["paid_at"]:
            gaps.append("confirmada sem pagamento registrado")
        if r["status"] in ("confirmed", "in_trip", "completed") and not r["confirmed_at"]:
            gaps.append("status confirmado sem confirmed_at")
        if r["status"] in ("confirmed", "in_trip", "completed") and r["issuance_n"] == 0:
            gaps.append("sem emissão registrada")
        if r["needs_field"] and r["status"] in ("confirmed", "in_trip") and r["field_n"] == 0:
            gaps.append("transfer/tour sem serviço de campo")
        if r["status"] in ("in_trip", "completed") and r["concierge_msgs"] == 0:
            gaps.append("sem mensagem do concierge")
        report.append({"ref": r["ref"], "status": r["status"], "gaps": gaps})
    total = len(report)
    conform = sum(1 for x in report if not x["gaps"])
    return ok({"days": days, "bookings": total, "conformant": conform, "conformance_pct": round(100 * conform / total, 1) if total else None, "detail": [x for x in report if x["gaps"]]})


@tool("jev_score_conversation", "Notas calibradas do Jev para uma transcrição (0–1 por dimensão da rubrica + flow_followed + hallucination). Use antes de pontuar você mesmo para ancorar.", {"transcript": str})
async def jev_score_conversation(args: dict[str, Any]) -> dict[str, Any]:
    ans = await jev.audit_scores(args["transcript"])
    if not ans:
        return ok({"available": False})
    dims = ["accuracy", "persona_language", "sales_flow", "empathy_clarity", "compliance", "escalation"]
    scores = {d: round(ans.score(d), 3) for d in dims}
    return ok({"available": True, "scores": scores, "avg_0_10": round(10 * sum(scores.values()) / len(dims), 2),
               "flow_followed": ans.noul("flow_followed"), "hallucination": ans.noul("hallucination")})


@tool("record_finding", "Registra um achado de auditoria com evidência literal e recomendação exata (área: customer_care|operations|marketing|finance|prospecting|strategy|ceo_office).", {"area": str, "flow": str, "severity": str, "title": str, "evidence": str, "recommendation": str})
async def record_finding(args: dict[str, Any]) -> dict[str, Any]:
    row = await db.fetchrow("INSERT INTO audit_findings (area, flow, severity, title, evidence, recommendation) VALUES ($1,$2,$3,$4,$5,$6) RETURNING id",
                            args["area"], args.get("flow"), args.get("severity") or "medium", args["title"], args.get("evidence"), args.get("recommendation"))
    return ok({"finding_id": str(row["id"])})  # type: ignore[index]


@tool("open_findings", "Achados abertos (para não repetir e para medir se foram implementados).", {"area": str})
async def open_findings(args: dict[str, Any]) -> dict[str, Any]:
    rows = await db.fetch("SELECT id, day, area, severity, title, recommendation, status FROM audit_findings WHERE status IN ('open','accepted') AND ($1::text IS NULL OR area = $1) ORDER BY day DESC", args.get("area"))
    return ok(rows)


@tool("department_activity", "Execuções por agente nas últimas N horas (runs, erros, custo, tarefas) e tarefas de cron esperadas que NÃO rodaram.", {"hours": int})
async def department_activity(args: dict[str, Any]) -> dict[str, Any]:
    hours = int(args.get("hours") or 24)
    rows = await db.fetch("""SELECT agent, trigger, count(*) runs, count(*) FILTER (WHERE status <> 'ok') errors, coalesce(sum(cost_usd),0) cost_usd, max(created_at) last_run
                             FROM agent_runs WHERE created_at > now() - ($1 || ' hours')::interval GROUP BY 1, 2 ORDER BY 1, 2""", str(hours))
    expected = ["ceo", "market_intel", "content_studio", "paid_media", "suppliers_pricing", "finance", "concierge", "fleet_dispatcher", "booking_payments", "prospector", "compliance"]
    ran = {r["agent"] for r in rows}
    return ok({"hours": hours, "activity": rows, "expected_but_silent": [a for a in expected if a not in ran]})


def server():
    return create_sdk_mcp_server(SERVER, "1.0.0", [sla_metrics, flow_conformance, jev_score_conversation, record_finding, open_findings, department_activity])
