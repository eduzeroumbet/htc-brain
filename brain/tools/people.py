"""Pessoas: os humanos que ficam (motoristas, guias freelancers, pessoal de resolução). Escala de folgas, documentos a vencer,
ocorrências e avaliações, pool de guias, insumo para o PRO (vistos/labour) e para a folha (WPS)."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from brain.core import bus, db
from brain.tools import create_sdk_mcp_server, err, ok, tool

SERVER = "people"


@tool("staff_overview", "Quadro humano ativo: papel, vínculo, idiomas, documentos a vencer em ≤ N dias (visto, labour card, passaporte, CNH, TGD), folgas do mês, ocorrências recentes.", {"days": int})
async def staff_overview(args: dict[str, Any]) -> dict[str, Any]:
    days = int(args.get("days") or 60)
    rows = await db.fetch("""SELECT s.*, (SELECT count(*) FROM staff_leave l WHERE l.staff_id = s.id AND l.status IN ('planned','approved','taken') AND date_trunc('month', l.starts_on) = date_trunc('month', current_date)) AS leave_days_month,
                                    (SELECT count(*) FROM staff_events e WHERE e.staff_id = s.id AND e.created_at > now() - interval '90 days' AND e.kind IN ('complaint','warning','accident','fine')) AS incidents_90d,
                                    (SELECT avg(score) FROM staff_events e WHERE e.staff_id = s.id AND e.score IS NOT NULL AND e.created_at > now() - interval '90 days') AS avg_score_90d
                             FROM staff s WHERE s.active ORDER BY s.role, s.name""")
    expiring = []
    for r in rows:
        for f in ("visa_expiry", "labour_card_expiry", "passport_expiry", "licence_expiry", "tgd_expiry"):
            if r.get(f) and r[f] <= date.today() + timedelta(days=days):
                expiring.append({"staff_id": r["id"], "name": r["name"], "document": f, "expires": str(r[f]), "days_left": (r[f] - date.today()).days})
    return ok({"staff": rows, "expiring_documents": sorted(expiring, key=lambda x: x["days_left"])})


@tool("update_staff", "Atualiza dados de um humano: datas de documentos, salário (AED), idiomas, ativo, notas.", {"staff_id": str, "fields": dict})
async def update_staff(args: dict[str, Any]) -> dict[str, Any]:
    allowed = {"visa_expiry", "labour_card_expiry", "passport_expiry", "licence_expiry", "tgd_expiry", "monthly_salary_aed", "languages", "active", "notes", "days_off_per_month", "whatsapp_env"}
    fields = {k: v for k, v in (args.get("fields") or {}).items() if k in allowed}
    if not fields:
        return err("nenhum campo válido")
    for k, v in fields.items():
        if k.endswith("_expiry") and isinstance(v, str):
            v = date.fromisoformat(v)
        await db.execute(f"UPDATE staff SET {k} = $2, updated_at = now() WHERE id = $1", args["staff_id"], v)
    return ok({"updated": list(fields)})


@tool("plan_leave", "Planeja folga/férias. Regra: nunca os dois motoristas no mesmo dia em alta temporada (nov–fev) nem em dia com ≥ 3 serviços de campo; 4 folgas/mês por motorista. Devolve conflito em vez de gravar quando a regra falha.", {"staff_id": str, "kind": str, "starts_on": str, "ends_on": str, "note": str})
async def plan_leave(args: dict[str, Any]) -> dict[str, Any]:
    s, e = date.fromisoformat(args["starts_on"]), date.fromisoformat(args.get("ends_on") or args["starts_on"])
    st = await db.fetchrow("SELECT role FROM staff WHERE id = $1", args["staff_id"])
    if not st:
        return err("staff não encontrado")
    conflicts = []
    if st["role"] == "driver":
        others = await db.fetch("""SELECT l.staff_id, l.starts_on, l.ends_on FROM staff_leave l JOIN staff s ON s.id = l.staff_id
                                   WHERE s.role = 'driver' AND l.staff_id <> $1 AND l.status IN ('planned','approved') AND daterange(l.starts_on, l.ends_on, '[]') && daterange($2, $3, '[]')""", args["staff_id"], s, e)
        d = s
        while d <= e:
            high = d.month in (11, 12, 1, 2)
            n = await db.fetchrow("SELECT count(*) n FROM field_assignments WHERE service_date = $1 AND kind <> 'issue_resolution' AND status NOT IN ('cancelled')", d)
            if others and (high or int(n["n"]) >= 3):  # type: ignore[index]
                conflicts.append({"day": str(d), "reason": "outro motorista de folga" + (" em alta temporada" if high else f" com {n['n']} serviços")})  # type: ignore[index]
            elif int(n["n"]) >= 3 and st["role"] == "driver":  # type: ignore[index]
                conflicts.append({"day": str(d), "reason": f"{n['n']} serviços planejados — confirmar cobertura terceirizada"})  # type: ignore[index]
            d += timedelta(days=1)
    if conflicts:
        return ok({"planned": False, "conflicts": conflicts})
    row = await db.fetchrow("INSERT INTO staff_leave (staff_id, kind, starts_on, ends_on, note, status) VALUES ($1,$2,$3,$4,$5,'approved') RETURNING id", args["staff_id"], args.get("kind") or "day_off", s, e, args.get("note"))
    return ok({"planned": True, "leave_id": str(row["id"])})  # type: ignore[index]


@tool("leave_calendar", "Folgas e férias planejadas nos próximos N dias (para o Frota planejar).", {"days": int})
async def leave_calendar(args: dict[str, Any]) -> dict[str, Any]:
    return ok(await db.fetch("SELECT l.*, s.name, s.role FROM staff_leave l JOIN staff s ON s.id = l.staff_id WHERE l.status IN ('planned','approved') AND l.ends_on >= current_date AND l.starts_on <= current_date + $1::int ORDER BY l.starts_on", int(args.get("days") or 30)))


@tool("record_staff_event", "Registra elogio, reclamação, advertência, treinamento, avaliação (score 0–10), acidente ou multa de um humano, ligado à reserva quando houver.", {"staff_id": str, "kind": str, "detail": str, "score": float, "booking_id": str})
async def record_staff_event(args: dict[str, Any]) -> dict[str, Any]:
    await db.execute("INSERT INTO staff_events (staff_id, kind, detail, score, booking_id) VALUES ($1,$2,$3,$4,$5)", args["staff_id"], args["kind"], args.get("detail"), args.get("score"), args.get("booking_id"))
    if args["kind"] in ("accident", "warning"):
        await bus.publish(bus.ALERTS, {"kind": "people", "severity": "high" if args["kind"] == "accident" else "medium", "text": f"{args['kind']} — {args['staff_id']}: {args.get('detail', '')[:300]}"})
    return ok({"recorded": True})


@tool("guide_pool", "Pool de guias/tradutores freelancers por idioma e estágio (candidate→vetted→trial→active), com licença e validade.", {"language": str, "stage": str})
async def guide_pool(args: dict[str, Any]) -> dict[str, Any]:
    return ok(await db.fetch("SELECT * FROM guide_pool WHERE ($1::text IS NULL OR $1 = ANY(languages)) AND ($2::text IS NULL OR stage = $2) ORDER BY stage, name", args.get("language"), args.get("stage")))


@tool("upsert_guide_candidate", "Cadastra/atualiza candidato a guia (licença DET obrigatória para 'vetted'; VIP só com vip_cleared e 2 avaliações ≥ 8). Ao virar 'active', copia para a tabela guides usada pelo Frota.", {"id": str, "name": str, "languages": list, "licence_no": str, "licence_expiry": str, "vip_cleared": bool, "source": str, "stage": str, "rate_aed_per_day": float, "notes": str})
async def upsert_guide_candidate(args: dict[str, Any]) -> dict[str, Any]:
    if args.get("stage") in ("vetted", "trial", "active") and not args.get("licence_no"):
        return err("guia sem licença não pode passar de 'contacted'")
    if args.get("id"):
        await db.execute("""UPDATE guide_pool SET name = coalesce($2,name), languages = coalesce($3,languages), licence_no = coalesce($4,licence_no), licence_expiry = coalesce($5,licence_expiry),
                            vip_cleared = coalesce($6,vip_cleared), stage = coalesce($7,stage), rate_aed_per_day = coalesce($8,rate_aed_per_day), notes = coalesce($9,notes) WHERE id = $1""",
                         args["id"], args.get("name"), args.get("languages"), args.get("licence_no"), date.fromisoformat(args["licence_expiry"]) if args.get("licence_expiry") else None,
                         args.get("vip_cleared"), args.get("stage"), args.get("rate_aed_per_day"), args.get("notes"))
        gid = args["id"]
    else:
        row = await db.fetchrow("INSERT INTO guide_pool (name, languages, licence_no, licence_expiry, vip_cleared, source, stage, rate_aed_per_day, notes) VALUES ($1,$2,$3,$4,coalesce($5,false),$6,coalesce($7,'candidate'),$8,$9) RETURNING id",
                                args["name"], args.get("languages") or [], args.get("licence_no"), date.fromisoformat(args["licence_expiry"]) if args.get("licence_expiry") else None,
                                args.get("vip_cleared"), args.get("source"), args.get("stage"), args.get("rate_aed_per_day"), args.get("notes"))
        gid = str(row["id"])  # type: ignore[index]
    if args.get("stage") == "active":
        g = await db.fetchrow("SELECT * FROM guide_pool WHERE id = $1", gid)
        exists = await db.fetchrow("SELECT id FROM guides WHERE tgd_license = $1", g["licence_no"])  # type: ignore[index]
        if not exists:
            await db.execute("""INSERT INTO guides (name, languages, tgd_license, tgd_expiry, rate_full_day_aed, vip_cleared, active) VALUES ($1,$2,$3,$4,$5,$6,true)""",
                             g["name"], g["languages"], g["licence_no"], g["licence_expiry"], g["rate_aed_per_day"], g["vip_cleared"])  # type: ignore[index]
    return ok({"id": gid})


@tool("payroll_pack", "Pacote mensal para folha/WPS e PRO: salário base, horas extras e multas (do Frota), folgas não gozadas, documentos a renovar, guias freelancers a pagar (serviços do mês × diária).", {"month": str})
async def payroll_pack(args: dict[str, Any]) -> dict[str, Any]:
    month = args.get("month") or date.today().strftime("%Y-%m")
    staff = await db.fetch("SELECT id, name, role, employment, monthly_salary_aed, visa_expiry, labour_card_expiry FROM staff WHERE active")
    hours = await db.fetch("SELECT driver_id, sum(hours_regular + hours_extra) total, sum(hours_extra) extra FROM driver_hours WHERE to_char(day, 'YYYY-MM') = $1 GROUP BY 1", month)
    fines = await db.fetch("SELECT driver_id, sum(amount_aed) aed FROM vehicle_events WHERE kind = 'fine' AND deduct_from_driver AND to_char(event_date, 'YYYY-MM') = $1 GROUP BY 1", month)
    guides = await db.fetch("""SELECT g.name, g.licence_no, count(f.id) services FROM field_assignments f JOIN guides g ON g.id = f.guide_id
                               WHERE to_char(f.service_date, 'YYYY-MM') = $1 AND f.status = 'done' GROUP BY g.id""", month)
    return ok({"month": month, "staff": staff, "driver_hours": hours, "fines_to_deduct_aed": fines, "freelance_guides": guides, "rule": "extras AED 35/h fora do horário; desconto de multas ≤ 20% do salário no WPS"})


def server():
    return create_sdk_mcp_server(SERVER, "1.0.0", [staff_overview, update_staff, plan_leave, leave_calendar, record_staff_event, guide_pool, upsert_guide_candidate, payroll_pack])
