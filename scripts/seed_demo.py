"""Popula o banco com dados de demonstração (fornecedores, catálogo, leads, reservas, mídia, KPIs de 30 dias)
para o dashboard nascer vivo. Apague com `make psql` → TRUNCATE quando for para produção."""
from __future__ import annotations

import asyncio
import random
from datetime import date, timedelta

from brain.core import db

random.seed(7)
MARKETS = {"BR": 0.15, "IN": 0.35, "SA": 0.25, "GB": 0.25}
CPL = {"BR": 7, "IN": 4, "SA": 9, "GB": 11}
TICKET = {"BR": 2200, "IN": 1100, "SA": 2800, "GB": 2500}
_carry = {m: [0.0, 0.0] for m in MARKETS}  # reservas, escalonamentos (frações acumuladas)

CATALOG = [
    ("HTL-JBR-4", "hotel", "Hotel 4★ JBR beachfront (quarto duplo, café)", 95, 14, "per_room_night", ["family", "budget"]),
    ("HTL-DTN-5", "hotel", "Hotel 5★ Downtown vista Burj (quarto duplo, café)", 210, 14, "per_room_night", ["honeymoon", "luxury"]),
    ("HTL-PALM-5", "hotel", "Resort 5★ Palm Jumeirah (clube infantil, praia privativa)", 320, 14, "per_room_night", ["family", "luxury", "halal"]),
    ("EXP-BURJ-124", "experience", "Burj Khalifa At the Top (124/125) horário do pôr do sol", 48, 18, "per_person", ["honeymoon", "family"]),
    ("EXP-SAFARI-PREM", "experience", "Safari no deserto premium com jantar e show", 75, 18, "per_person", ["family", "honeymoon", "halal", "vegetarian"]),
    ("EXP-YACHT-2H", "experience", "Iate privado 2h Marina (até 10 pessoas)", 520, 18, "flat", ["honeymoon", "luxury"]),
    ("EXP-AQUAV", "experience", "Aquaventure Atlantis dia inteiro", 92, 18, "per_person", ["family"]),
    ("EXP-ABUDHABI-DAY", "experience", "Day trip Abu Dhabi: Grande Mesquita + Louvre", 110, 18, "per_person", ["family", "honeymoon"]),
    ("TRF-DXB-HTL", "transfer", "Transfer privado aeroporto ↔ hotel (sedan)", 32, 20, "per_vehicle", []),
    ("VISA-30", "visa", "Visto de turista EAU 30 dias (serviço)", 85, 30, "per_person", []),
    ("INS-7D", "insurance", "Seguro-viagem 7 dias cobertura USD 60k", 24, 30, "per_person", []),
]


async def main() -> None:
    await db.pool()
    sup = await db.fetchrow(
        """INSERT INTO suppliers (name, kind, det_license, det_license_valid_until, approved_by_ceo)
           VALUES ('DMC Parceira Demo', 'dmc', 'DET-DEMO-1', current_date + 300, true) RETURNING id""")
    for sku, kind, name, net, mk, basis, suit in CATALOG:
        await db.execute(
            """INSERT INTO catalog_items (supplier_id, sku, kind, name, description, net_price_usd, markup_pct, price_basis, suitable_for, availability_note)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) ON CONFLICT (sku) DO NOTHING""",
            sup["id"], sku, kind, name, {"pt": name}, net, mk, basis, suit, "low_occupancy" if sku == "HTL-DTN-5" else None)  # type: ignore[index]

    camp_ids = {}
    for m in MARKETS:
        row = await db.fetchrow("INSERT INTO campaigns (market_code, platform, name, objective, daily_budget_usd) VALUES ($1,$2,$3,'leads',$4) RETURNING id",
                                m, "meta" if m != "GB" else "google_search", f"{m} · leads · set/26", round(135 * MARKETS[m], 2))
        camp_ids[m] = row["id"]  # type: ignore[index]

    today = date.today()
    for i in range(30):
        d = today - timedelta(days=29 - i)
        ramp = 0.55 + 0.45 * i / 29  # recuperação
        for m, share in MARKETS.items():
            spend = round(135 * share * random.uniform(0.85, 1.05), 2)
            paid = spend / CPL[m] * random.uniform(0.8, 1.2)              # leads de mídia ao CPL-alvo
            organic = paid * (0.4 + ramp * 0.6)                           # conteúdo, SEO e indicações
            leads = max(1, round((paid + organic) * (0.75 + ramp * 0.35)))
            qualified = round(leads * random.uniform(0.38, 0.48))
            quotes = round(qualified * random.uniform(0.6, 0.7))
            _carry[m][0] += quotes * random.uniform(0.12, 0.18)
            bookings = int(_carry[m][0]); _carry[m][0] -= bookings
            revenue = round(bookings * TICKET[m] * random.uniform(0.9, 1.1), 2)
            margin = round(revenue * random.uniform(0.14, 0.19), 2)
            for _ in range(leads):
                lead = await db.fetchrow(
                    """INSERT INTO leads (market_code, channel, channel_user_id, display_name, stage, consent_marketing, created_at, updated_at)
                       VALUES ($1,$2,$3,$4,$5,true,$6,$6) RETURNING id""",
                    m, random.choice(["whatsapp", "instagram", "webchat", "telegram", "email"]), f"demo-{m}-{d}-{random.random()}",
                    f"Lead {m}", random.choice(["new", "qualifying", "qualified", "quoted", "nurture"]), d)
                conv = await db.fetchrow("INSERT INTO conversations (lead_id, channel, first_response_ms, csat, started_at, last_message_at) VALUES ($1,'whatsapp',$2,$3,$4,$4) RETURNING id",
                                         lead["id"], random.randint(8000, 55000), random.choice([None, 4, 5, 5, 5, 3]), d)  # type: ignore[index]
                if random.random() < 0.031:
                    await db.execute("INSERT INTO escalations (conversation_id, lead_id, trigger_id, severity, summary, status, opened_at, resolved_at) VALUES ($1,$2,$3,'medium','demo','resolved',$4,$4)",
                                     conv["id"], lead["id"], random.choice(["explicit_request", "low_confidence", "payment_threshold"]), d)  # type: ignore[index]
            for _ in range(bookings):
                lead = await db.fetchrow("SELECT id FROM leads WHERE market_code = $1 AND created_at::date = $2 ORDER BY random() LIMIT 1", m, d)
                if lead:
                    await db.execute("UPDATE leads SET stage = 'won' WHERE id = $1", lead["id"])
                    t = round(TICKET[m] * random.uniform(0.7, 1.3), 2)
                    await db.execute(
                        """INSERT INTO bookings (ref, lead_id, market_code, travel_start, travel_end, items, total_usd, net_cost_usd, margin_usd, paid_usd, payment_status, status, created_at)
                           VALUES ($1,$2,$3,$4,$5,'[]'::jsonb,$6,$7,$8,$6,'paid','confirmed',$9)""",
                        f"DXB-2026-{random.randint(100000, 999999)}", lead["id"], m, d + timedelta(days=random.randint(20, 90)),
                        d + timedelta(days=random.randint(91, 96)), t, round(t * 0.84, 2), round(t * 0.16, 2), d)
            await db.execute(
                """INSERT INTO ad_spend_daily (day, campaign_id, market_code, platform, spend_usd, impressions, clicks, leads, bookings, revenue_usd)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) ON CONFLICT (day, campaign_id) DO NOTHING""",
                d, camp_ids[m], m, "meta" if m != "GB" else "google_search", spend, int(spend * 900), int(spend * 14), leads, bookings, revenue)
            await db.execute(
                """INSERT INTO agent_runs (agent, market_code, trigger, status, cost_usd, duration_ms, started_at)
                   VALUES ('consultant', $1, 'event', 'ok', $2, 9000, $3)""", m, round(leads * 0.55 * random.uniform(0.8, 1.2), 3), d)
            for a, c in (("content_studio", 1.9), ("paid_media", 0.4), ("market_intel", 0.5), ("auditor", 0.6), ("ceo", 0.7), ("prospector", 0.5), ("strategist", 0.3), ("finance", 0.2)):
                await db.execute("INSERT INTO agent_runs (agent, market_code, trigger, status, cost_usd, duration_ms, started_at) VALUES ($1,$2,'cron','ok',$3,40000,$4)", a, m, round(c / len(MARKETS), 3), d)
            for _ in range(random.randint(3, 5)):
                await db.execute("INSERT INTO content_items (market_code, pillar, format, channel, status, published_at, created_at, metrics) VALUES ($1,'demo','post','instagram','published',$2,$2,$3)",
                                 m, d, {"reach": random.randint(800, 9000), "saves": random.randint(5, 120), "leads": random.randint(0, 6)})
        await db.rollup_kpis(d)

    await db.execute("""INSERT INTO decisions (kind, context, recommendation, requested_by, amount_usd, market_code) VALUES
        ('budget_increase', 'Índia com CAC USD 62 (meta 80) há 9 dias; teto diário limita. Pedido: +USD 30/dia por 14 dias.', 'Aprovar: +USD 420 → ~7 reservas extras (USD 7.700 receita).', 'ai:paid_media', 420, 'IN'),
        ('discount', 'Cotação 00000000-0000-0000-0000-000000000000 com desconto de 8% (margem 13.1%) — família saudita 8 pax, Eid.', 'Aprovar: margem acima de 12% e datas confirmadas.', 'ai:consultant', 9800, 'SA'),
        ('new_supplier', 'Rayna Tours pediu cadastro como fornecedor de experiências (licença DET válida até 2027-03).', 'Aprovar em teste com 3 produtos.', 'ai:suppliers_pricing', NULL, NULL)""")
    print("seed ok")
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
