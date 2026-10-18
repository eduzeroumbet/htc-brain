"""Frota e campo: veículos, motoristas, guias, escala diária, horas, multas e manutenção."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from brain.core import bus, db
from brain.tools import create_sdk_mcp_server, err, ok, tool

SERVER = "fleet"


@tool("fleet_status", "Veículos, motoristas e guias ativos com vencimentos (Mulkiya, seguro, visto, TGD) e odômetro.", {})
async def fleet_status(args: dict[str, Any]) -> dict[str, Any]:
    vehicles = await db.fetch("SELECT * FROM vehicles WHERE active ORDER BY id")
    drivers = await db.fetch("SELECT id, name, languages, license_expiry, visa_expiry, labour_card_expiry, iloe_expiry, max_hours_per_day FROM drivers WHERE active")
    guides = await db.fetch("SELECT id, name, languages, tgd_expiry, rating, vip_cleared FROM guides WHERE active ORDER BY rating DESC")
    for v in vehicles:
        v["km_to_service"] = int(v["last_service_km"] or 0) + int(v["service_interval_km"] or 10000) - int(v["odometer_km"] or 0)
    return ok({"vehicles": vehicles, "drivers": drivers, "guides": guides})


@tool("services_for_date", "Serviços de campo já planejados para uma data (YYYY-MM-DD), com motorista/guia/veículo.", {"date": str})
async def services_for_date(args: dict[str, Any]) -> dict[str, Any]:
    rows = await db.fetch("SELECT * FROM field_assignments WHERE service_date = $1::text::date ORDER BY start_time", args["date"])
    return ok(rows)


@tool("bookings_needing_field_services", "Reservas confirmadas com itens de transfer/tour/meet&greet entre hoje e D+N sem serviço de campo criado.", {"days_ahead": int})
async def bookings_needing_field_services(args: dict[str, Any]) -> dict[str, Any]:
    rows = await db.fetch(
        """SELECT b.id AS booking_id, b.ref, b.lead_id, b.travel_start, b.travel_end, b.items, b.pax, l.display_name, l.phone, l.language,
                  (l.score >= 90) AS vip
           FROM bookings b JOIN leads l ON l.id = b.lead_id
           WHERE b.status IN ('confirmed','in_trip') AND b.travel_start <= current_date + $1::int AND b.travel_end >= current_date
             AND NOT EXISTS (SELECT 1 FROM field_assignments f WHERE f.booking_id = b.id)
           ORDER BY b.travel_start""",
        int(args.get("days_ahead") or 2),
    )
    return ok(rows)


@tool("choose_vehicle", "Escolhe o veículo pela regra de bagagem: pax e malas grandes → menor veículo próprio que cabe; se nenhum, sugere terceirizado.", {"pax": int, "bags": int, "vip": bool, "date": str})
async def choose_vehicle(args: dict[str, Any]) -> dict[str, Any]:
    pax, bags, vip = int(args["pax"]), int(args.get("bags") or 0), bool(args.get("vip"))
    busy = await db.fetch("SELECT vehicle_id FROM field_assignments WHERE service_date = $1::text::date AND status NOT IN ('cancelled','done')", args.get("date") or str(date.today()))
    busy_ids = {b["vehicle_id"] for b in busy}
    vehicles = await db.fetch("SELECT * FROM vehicles WHERE active AND owned ORDER BY CASE WHEN category='suv_luxury' THEN 0 ELSE 1 END, pax_capacity")
    if vip:
        vehicles = sorted(vehicles, key=lambda v: 0 if v["category"] == "suv_luxury" else 1)
    for v in vehicles:
        cap_bags = int(v["bags_row3_down"] or 0) if pax <= max(1, int(v["pax_capacity"]) - 3) else int(v["bags_seats_up"] or 0)
        if pax <= int(v["pax_capacity"]) and bags <= cap_bags and v["id"] not in busy_ids:
            return ok({"vehicle_id": v["id"], "name": v["name"], "reason": f"{pax} pax e {bags} malas cabem ({cap_bags} malas nessa configuração)"})
    return ok({"vehicle_id": None, "third_party": True, "suggestion": "Sprinter 12–15 lugares" if pax > 7 or bags > 9 else "Yukon XL/Suburban terceirizado",
               "reason": "nenhum veículo próprio livre com capacidade para pax/malas nessa data"})


@tool("create_assignment", "Cria um serviço de campo. kind: transfer_in|transfer_out|tour|meet_greet|errand|abaya. Datas YYYY-MM-DD, horas HH:MM.", {"booking_id": str, "lead_id": str, "service_date": str, "start_time": str, "end_time": str, "kind": str, "pickup": str, "dropoff": str, "pax": int, "bags": int, "vehicle_id": str, "driver_id": str, "guide_id": str, "client_name": str, "vip": bool, "briefing": str})
async def create_assignment(args: dict[str, Any]) -> dict[str, Any]:
    if args.get("driver_id"):
        hours = await db.fetchrow("SELECT coalesce(sum(extract(epoch from (end_time - start_time))/3600),0) AS h FROM field_assignments WHERE driver_id = $1 AND service_date = $2::text::date AND status <> 'cancelled'",
                                  args["driver_id"], args["service_date"])
        drv = await db.fetchrow("SELECT max_hours_per_day FROM drivers WHERE id = $1", args["driver_id"])
        if drv and float(hours["h"] or 0) >= float(drv["max_hours_per_day"]):  # type: ignore[index]
            return err(f"motorista {args['driver_id']} já atinge {drv['max_hours_per_day']} h em {args['service_date']}")
    row = await db.fetchrow(
        """INSERT INTO field_assignments (booking_id, lead_id, service_date, start_time, end_time, kind, pickup, dropoff, pax, bags, vehicle_id, driver_id, guide_id, client_name, vip, briefing)
           VALUES ($1,$2,$3::text::date,$4::text::time,$5::text::time,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16) RETURNING id""",
        args.get("booking_id"), args.get("lead_id"), args["service_date"], args["start_time"], args.get("end_time"), args["kind"], args.get("pickup"), args.get("dropoff"),
        args.get("pax"), args.get("bags"), args.get("vehicle_id"), args.get("driver_id"), args.get("guide_id"), args.get("client_name"), bool(args.get("vip")), args.get("briefing"),
    )
    return ok({"assignment_id": str(row["id"])})  # type: ignore[index]


@tool("send_daily_agenda", "Envia a agenda de uma data a cada motorista e guia (WhatsApp de campo) e marca os serviços como 'sent'.", {"date": str})
async def send_daily_agenda(args: dict[str, Any]) -> dict[str, Any]:
    d = args.get("date") or str(date.today() + timedelta(days=1))
    rows = await db.fetch(
        """SELECT f.*, d.whatsapp AS driver_whatsapp, d.name AS driver_name, g.whatsapp AS guide_whatsapp, g.name AS guide_name, v.name AS vehicle_name
           FROM field_assignments f LEFT JOIN drivers d ON d.id = f.driver_id LEFT JOIN guides g ON g.id = f.guide_id LEFT JOIN vehicles v ON v.id = f.vehicle_id
           WHERE f.service_date = $1::text::date AND f.status IN ('planned','sent') ORDER BY f.driver_id, f.start_time""", d)
    sent = 0
    by_person: dict[str, list] = {}
    for r in rows:
        for who, wa in ((r["driver_name"], r["driver_whatsapp"]), (r["guide_name"], r["guide_whatsapp"])):
            if wa:
                by_person.setdefault(wa, []).append(r)
    for wa, items in by_person.items():
        lines = [f"Agenda {d}:"]
        for r in items:
            lines.append(f"• {str(r['start_time'])[:5]}{('–' + str(r['end_time'])[:5]) if r['end_time'] else ''} {r['kind']} · {r.get('client_name') or ''}{' (VIP)' if r['vip'] else ''} · {r['pax'] or ''} pax/{r['bags'] or 0} malas · {r['pickup'] or ''} → {r['dropoff'] or ''} · {r['vehicle_name'] or 'a definir'}")
            if r.get("briefing"):
                lines.append(f"  {r['briefing'][:200]}")
        lines.append("Responda OK para confirmar. Botões 'a caminho' / 'a bordo' / 'concluído' durante o dia. Foto do odômetro no início e no fim.")
        await bus.publish(bus.OUTBOUND, {"channel": "whatsapp", "channel_user_id": wa.lstrip("+"), "text": "\n".join(lines), "field": True})
        sent += 1
    await db.execute("UPDATE field_assignments SET status = 'sent' WHERE service_date = $1::text::date AND status = 'planned'", d)
    return ok({"date": d, "messages_sent": sent, "services": len(rows)})


@tool("update_assignment_status", "Atualiza status de um serviço (confirmed_by_driver|en_route|onboard|done|cancelled|no_show) e odômetro.", {"assignment_id": str, "status": str, "odometer": int})
async def update_assignment_status(args: dict[str, Any]) -> dict[str, Any]:
    col = {"en_route": "started_at", "done": "finished_at", "confirmed_by_driver": "driver_confirmed_at"}.get(args["status"])
    extra = f", {col} = now()" if col else ""
    odo = ""
    if args.get("odometer"):
        odo = ", odometer_start = coalesce(odometer_start, $3)" if args["status"] in ("en_route", "onboard") else ", odometer_end = $3"
    if odo:
        await db.execute(f"UPDATE field_assignments SET status = $2{extra}{odo} WHERE id = $1", args["assignment_id"], args["status"], int(args["odometer"]))
        await db.execute("UPDATE vehicles SET odometer_km = greatest(odometer_km, $2) WHERE id = (SELECT vehicle_id FROM field_assignments WHERE id = $1)", args["assignment_id"], int(args["odometer"]))
    else:
        await db.execute(f"UPDATE field_assignments SET status = $2{extra} WHERE id = $1", args["assignment_id"], args["status"])
    return ok({"assignment_id": args["assignment_id"], "status": args["status"]})


@tool("log_driver_hours", "Registra horas do dia por motorista (do GPS ou dos serviços) e calcula extras acima de 8h regulares.", {"driver_id": str, "day": str, "hours_total": float, "source": str})
async def log_driver_hours(args: dict[str, Any]) -> dict[str, Any]:
    total = float(args["hours_total"])
    regular, extra = min(total, 8.0), max(0.0, total - 8.0)
    await db.execute(
        """INSERT INTO driver_hours (driver_id, day, hours_regular, hours_extra, source) VALUES ($1,$2::text::date,$3,$4,$5)
           ON CONFLICT (driver_id, day) DO UPDATE SET hours_regular = EXCLUDED.hours_regular, hours_extra = EXCLUDED.hours_extra, source = EXCLUDED.source""",
        args["driver_id"], args["day"], regular, extra, args.get("source") or "gps",
    )
    return ok({"driver_id": args["driver_id"], "day": args["day"], "regular": regular, "extra": extra})


@tool("monthly_driver_payroll_input", "Horas regulares e extras do mês por motorista + multas a descontar (máx. 20% do salário em WPS).", {"month": str})
async def monthly_driver_payroll_input(args: dict[str, Any]) -> dict[str, Any]:
    month = args.get("month") or date.today().strftime("%Y-%m")
    rows = await db.fetch(
        """SELECT d.id, d.name, d.base_salary_aed, d.extra_hour_rate_aed,
                  coalesce(sum(h.hours_regular),0) AS hours_regular, coalesce(sum(h.hours_extra),0) AS hours_extra,
                  (SELECT coalesce(sum(amount_aed),0) FROM vehicle_events e WHERE e.driver_id = d.id AND e.deduct_from_driver AND to_char(e.event_date,'YYYY-MM') = $1) AS fines_aed
           FROM drivers d LEFT JOIN driver_hours h ON h.driver_id = d.id AND to_char(h.day,'YYYY-MM') = $1
           WHERE d.active GROUP BY d.id""", month)
    for r in rows:
        r["extra_pay_aed"] = round(float(r["hours_extra"]) * float(r["extra_hour_rate_aed"] or 35), 2)
        cap = round(float(r["base_salary_aed"] or 0) * 0.2, 2)
        r["fine_deduction_this_month_aed"] = min(float(r["fines_aed"]), cap) if cap else float(r["fines_aed"])
    return ok({"month": month, "drivers": rows})


@tool("record_vehicle_event", "Registra multa, revisão, combustível, Salik/DARB, dano, renovação. deduct_from_driver para multas.", {"vehicle_id": str, "kind": str, "amount_aed": float, "description": str, "driver_id": str, "deduct_from_driver": bool, "event_date": str})
async def record_vehicle_event(args: dict[str, Any]) -> dict[str, Any]:
    await db.execute(
        """INSERT INTO vehicle_events (vehicle_id, kind, amount_aed, description, driver_id, deduct_from_driver, event_date)
           VALUES ($1,$2,$3,$4,$5,$6, coalesce($7::text::date, current_date))""",
        args["vehicle_id"], args["kind"], args.get("amount_aed"), args.get("description"), args.get("driver_id"), bool(args.get("deduct_from_driver")), args.get("event_date"),
    )
    if args["kind"] == "service":
        await db.execute("UPDATE vehicles SET last_service_km = odometer_km WHERE id = $1", args["vehicle_id"])
    return ok({"recorded": True})


@tool("check_rta_fines", "Consulta multas RTA por placa (stub — ligar à consulta pública da Dubai Police). Retorna lista para registrar.", {"plate": str})
async def check_rta_fines(args: dict[str, Any]) -> dict[str, Any]:
    # TODO(Edu): automatizar via https://www.dubaipolice.gov.ae/app/services/fine-payment/search (captcha → consulta assistida) ou API RTA.
    return ok({"plate": args["plate"], "fines": [], "note": "consulta manual/assistida; registrar com record_vehicle_event(kind='fine')"})


def server():
    return create_sdk_mcp_server(SERVER, "1.0.0", [
        fleet_status, services_for_date, bookings_needing_field_services, choose_vehicle, create_assignment, send_daily_agenda,
        update_assignment_status, log_driver_hours, monthly_driver_payroll_input, record_vehicle_event, check_rta_fines,
    ])
