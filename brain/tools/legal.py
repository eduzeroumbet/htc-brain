"""Jurídico, proteção de dados e regulatório: contratos, pedidos de titulares (DSAR), screening de sanções, incidentes.

Screening de sanções: usa a API do OpenSanctions quando houver OPENSANCTIONS_API_KEY; sem chave, registra 'error' e o agente
pede decisão humana antes de receber dinheiro de cliente/parceiro RU/CIS. Nunca aprova sozinho um 'possible_match'.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Any

import httpx

from brain.core import bus, db, jev
from brain.tools import create_sdk_mcp_server, err, ok, tool

SERVER = "legal"
DSAR_DAYS = {"UAE_PDPL": 15, "LGPD": 15, "GDPR": 30, "UK_GDPR": 30, "DPDP": 15, "PDPL_KSA": 15, "CCPA": 45}


@tool("contracts_list", "Contratos por status/tipo, com vencimentos nos próximos N dias (padrão 60) e termos-chave.", {"status": str, "kind": str, "days": int})
async def contracts_list(args: dict[str, Any]) -> dict[str, Any]:
    rows = await db.fetch("""SELECT id, kind, counterparty, entity, status, starts_at, ends_at, auto_renew, key_terms, document_url, signed_by_ceo_at, (ends_at - current_date) AS days_to_end
                             FROM contracts WHERE ($1::text IS NULL OR status = $1) AND ($2::text IS NULL OR kind = $2)
                               AND (ends_at IS NULL OR ends_at <= current_date + $3::int OR status NOT IN ('expired','terminated')) ORDER BY ends_at NULLS LAST""",
                          args.get("status"), args.get("kind"), int(args.get("days") or 60))
    return ok(rows)


@tool("draft_contract", "Registra um contrato em rascunho a partir de um modelo (partner_agency|supplier|mice|freelancer|venue) com termos-chave. A assinatura é sempre da CEO: cria decisão kind='contract'.", {"kind": str, "counterparty": str, "entity": str, "partner_id": str, "supplier_id": str, "template": str, "starts_at": str, "ends_at": str, "auto_renew": bool, "key_terms": dict, "review_notes": str})
async def draft_contract(args: dict[str, Any]) -> dict[str, Any]:
    row = await db.fetchrow(
        """INSERT INTO contracts (kind, counterparty, entity, partner_id, supplier_id, template, starts_at, ends_at, auto_renew, key_terms, review_notes)
           VALUES ($1,$2,coalesce($3,'HCTE'),$4,$5,$6,$7,$8,coalesce($9,false),coalesce($10,'{}'::jsonb),$11) RETURNING id""",
        args["kind"], args["counterparty"], args.get("entity"), args.get("partner_id"), args.get("supplier_id"), args.get("template"),
        date.fromisoformat(args["starts_at"]) if args.get("starts_at") else None, date.fromisoformat(args["ends_at"]) if args.get("ends_at") else None,
        args.get("auto_renew"), args.get("key_terms"), args.get("review_notes"))
    d = await db.fetchrow("INSERT INTO decisions (kind, context, recommendation, requested_by) VALUES ('contract', $1, $2, 'ai:legal_compliance') RETURNING id",
                          f"Contrato {args['kind']} com {args['counterparty']} ({args.get('entity') or 'HCTE'}): termos {args.get('key_terms')}", args.get("review_notes") or "Revisar e assinar")
    await db.execute("UPDATE contracts SET status = 'sent' WHERE id = $1", row["id"])  # type: ignore[index]
    return ok({"contract_id": str(row["id"]), "decision_id": str(d["id"]), "status": "sent"})  # type: ignore[index]


@tool("set_contract_status", "Atualiza status (negotiating|signed|active|expired|terminated), URL do documento e data de assinatura.", {"contract_id": str, "status": str, "document_url": str, "signed": bool})
async def set_contract_status(args: dict[str, Any]) -> dict[str, Any]:
    await db.execute("""UPDATE contracts SET status = $2, document_url = coalesce($3, document_url), signed_by_ceo_at = CASE WHEN $4 THEN now() ELSE signed_by_ceo_at END, updated_at = now() WHERE id = $1""",
                     args["contract_id"], args["status"], args.get("document_url"), bool(args.get("signed")))
    return ok({"updated": True})


@tool("open_data_request", "Registra pedido de titular de dados (acesso|correção|exclusão|portabilidade|oposição|retirada de consentimento) com prazo pela jurisdição (nossa política: 15 dias, ou o legal se menor).", {"lead_id": str, "requester": str, "kind": str, "jurisdiction": str})
async def open_data_request(args: dict[str, Any]) -> dict[str, Any]:
    days = min(15, DSAR_DAYS.get(args.get("jurisdiction") or "", 15))
    row = await db.fetchrow("""INSERT INTO data_requests (lead_id, requester, kind, jurisdiction, due_at) VALUES ($1,$2,$3,$4,$5)
                               ON CONFLICT (lead_id, kind) WHERE status NOT IN ('completed', 'refused') DO NOTHING RETURNING id, due_at""",
                            args.get("lead_id"), args["requester"], args["kind"], args.get("jurisdiction"), datetime.now() + timedelta(days=days))
    if not row:  # já existe pedido aberto do mesmo tipo para o lead (ex.: aberto pela mensagem do cliente)
        row = await db.fetchrow("SELECT id, due_at FROM data_requests WHERE lead_id = $1 AND kind = $2 AND status NOT IN ('completed', 'refused') ORDER BY received_at DESC LIMIT 1",
                                args.get("lead_id"), args["kind"])
    return ok(row)


@tool("fulfil_data_request", "Executa o pedido: access → exporta dados do lead (JSON); erasure → anonimiza lead/mensagens e apaga pax da reserva (mantém o fiscal); rectification → aplica fields; registra ações e fecha.", {"request_id": str, "fields": dict, "note": str})
async def fulfil_data_request(args: dict[str, Any]) -> dict[str, Any]:
    r = await db.fetchrow("SELECT * FROM data_requests WHERE id = $1", args["request_id"])
    if not r:
        return err("pedido não encontrado")
    out: dict[str, Any] = {"kind": r["kind"]}
    lid = r["lead_id"]
    if r["kind"] == "access" and lid:
        out["export"] = {"lead": await db.fetchrow("SELECT display_name, phone, email, language, market_code, stage, segment, travel_dates, created_at FROM leads WHERE id = $1", lid),
                         "messages": await db.fetch("SELECT m.direction, m.body, m.created_at FROM messages m JOIN conversations c ON c.id = m.conversation_id WHERE c.lead_id = $1 ORDER BY m.created_at", lid),
                         "bookings": await db.fetch("SELECT ref, travel_start, travel_end, total_usd, status FROM bookings WHERE lead_id = $1", lid)}
    elif r["kind"] in ("erasure", "consent_withdrawal") and lid:
        await db.execute("UPDATE leads SET display_name = 'apagado', phone = NULL, email = NULL, notes = NULL, consent_marketing = false, consent_whatsapp = false WHERE id = $1", lid)
        if r["kind"] == "erasure":
            await db.execute("UPDATE messages SET body = '[apagado a pedido do titular]' WHERE conversation_id IN (SELECT id FROM conversations WHERE lead_id = $1)", lid)
            await db.execute("UPDATE bookings SET pax = NULL WHERE lead_id = $1", lid)
        out["anonymised"] = True
    elif r["kind"] == "rectification" and lid and args.get("fields"):
        allowed = {k: v for k, v in args["fields"].items() if k in ("display_name", "phone", "email", "language")}
        for k, v in allowed.items():
            await db.execute(f"UPDATE leads SET {k} = $2 WHERE id = $1", lid, v)
        out["updated"] = list(allowed)
    await db.execute("UPDATE data_requests SET status = 'completed', actions = $2, completed_at = now() WHERE id = $1", r["id"], args.get("note") or str(out.keys()))
    return ok(out)


@tool("open_data_requests", "Pedidos de titulares abertos com prazo.", {})
async def open_data_requests(args: dict[str, Any]) -> dict[str, Any]:
    return ok(await db.fetch("SELECT id, requester, kind, jurisdiction, received_at, due_at, status, extract(epoch from (due_at - now()))/3600 AS hours_left FROM data_requests WHERE status <> 'completed' ORDER BY due_at"))


@tool("sanctions_screen", "Screening de sanções (OFAC/EU/UK/UN) de pessoa ou empresa. Com OPENSANCTIONS_API_KEY consulta a API; sem chave registra 'error' (exige decisão humana). 'possible_match'/'match' → nunca receber pagamento sem decisão da CEO.", {"subject_kind": str, "subject_id": str, "name": str, "country": str})
async def sanctions_screen(args: dict[str, Any]) -> dict[str, Any]:
    key = os.getenv("OPENSANCTIONS_API_KEY", "")
    result, detail = "error", {"note": "sem OPENSANCTIONS_API_KEY — screening manual necessário"}
    if key:
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.post("https://api.opensanctions.org/match/sanctions", headers={"Authorization": f"ApiKey {key}"},
                                 json={"queries": {"q": {"schema": "LegalEntity", "properties": {"name": [args["name"]], "country": [args.get("country")] if args.get("country") else []}}}})
            data = r.json().get("responses", {}).get("q", {}).get("results", [])
            top = max((x.get("score", 0) for x in data), default=0)
            result = "match" if top >= 0.9 else "possible_match" if top >= 0.6 else "clear"
            detail = {"top_score": top, "hits": [{"name": x.get("caption"), "score": x.get("score"), "datasets": x.get("datasets")} for x in data[:3]]}
        except Exception as exc:  # noqa: BLE001
            detail = {"error": str(exc)}
    await db.execute("INSERT INTO sanctions_screenings (subject_kind, subject_id, name_checked, country, lists, result, detail) VALUES ($1,$2,$3,$4,$5,$6,$7)",
                     args["subject_kind"], args.get("subject_id"), args["name"], args.get("country"), ["OFAC_SDN", "EU", "UK_HMT", "UN"], result, detail)
    if result in ("match", "possible_match"):
        await bus.publish(bus.ALERTS, {"kind": "sanctions", "severity": "high", "text": f"Screening de sanções: {result} para {args['name']} ({args.get('country')}). Bloquear pagamento até decisão."})
    return ok({"result": result, "detail": detail})


@tool("open_legal_incident", "Abre incidente jurídico/regulatório (data_breach|consumer_complaint|regulator_notice|accident|public_crisis|chargeback_dispute). Data breach define prazo de notificação (72h) e alerta a CEO.", {"kind": str, "severity": str, "title": str, "detail": str})
async def open_legal_incident(args: dict[str, Any]) -> dict[str, Any]:
    deadline = datetime.now() + timedelta(hours=72) if args["kind"] == "data_breach" else None
    row = await db.fetchrow("INSERT INTO legal_incidents (kind, severity, title, detail, notify_deadline) VALUES ($1,$2,$3,$4,$5) RETURNING id",
                            args["kind"], args.get("severity") or "medium", args["title"], args.get("detail"), deadline)
    sev = "critical" if args["kind"] in ("data_breach", "accident", "public_crisis") else "high"
    await bus.publish(bus.ALERTS, {"kind": "legal", "severity": sev, "text": f"Incidente {args['kind']}: {args['title']} — {args.get('detail', '')[:300]}"})
    return ok({"incident_id": str(row["id"]), "notify_deadline": deadline})  # type: ignore[index]


@tool("legal_incidents_open", "Incidentes jurídicos abertos e prazos.", {})
async def legal_incidents_open(args: dict[str, Any]) -> dict[str, Any]:
    return ok(await db.fetch("SELECT id, kind, severity, title, status, notify_deadline, opened_at FROM legal_incidents WHERE status <> 'resolved' ORDER BY opened_at"))


@tool("review_text_for_legal_risk", "Jev lê um texto (contrato recebido, termo de parceiro, resposta pública, e-mail de reclamação) e sinaliza risco jurídico: cláusulas abusivas, promessa indevida, dado sensível, admissão de culpa, ameaça legal.", {"text": str, "context": str})
async def review_text_for_legal_risk(args: dict[str, Any]) -> dict[str, Any]:
    ans = await jev.decide({"context": args.get("context"), "text": args["text"][:8000]}, {
        "risk": {"type": "score", "instructions": "Risco jurídico/regulatório para a agência", "criteria": ["nenhum", "baixo", "médio", "alto", "crítico"]},
        "admits_liability": {"type": "noul", "instructions": "O texto admite culpa/responsabilidade da agência ou promete indenização?"},
        "unfair_clause": {"type": "noul", "instructions": "Há cláusula desequilibrada (exclusividade, multa desproporcional, responsabilidade ilimitada, foro estranho, pagamento sem prazo)?"},
        "sensitive_data": {"type": "noul", "instructions": "Contém dado sensível (passaporte, cartão, saúde) que não deveria estar ali?"},
        "legal_threat": {"type": "noul", "instructions": "Há ameaça de processo, denúncia a órgão regulador ou imprensa?"}})
    if not ans:
        return ok({"available": False})
    return ok({"risk": round(ans.score("risk"), 3), **{k: round(ans.noul(k), 2) for k in ("admits_liability", "unfair_clause", "sensitive_data", "legal_threat")}})


def server():
    return create_sdk_mcp_server(SERVER, "1.0.0", [contracts_list, draft_contract, set_contract_status, open_data_request, fulfil_data_request, open_data_requests,
                                                   sanctions_screen, open_legal_incident, legal_incidents_open, review_text_for_legal_risk])
