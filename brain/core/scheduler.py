"""Agenda dos agentes (APScheduler). Horários em Asia/Dubai, salvo indicação. A agência é 24/7: o atendimento é por evento
(webhooks → stream inbound); o cron cobre o trabalho de bastidores.

CEO (gabinete)
  07:00  briefing do CEO (3 números, 3 decisões, 1 risco) · */2h aprova dentro das regras · */6h gestão dos agentes
Marketing
  06:00  Content Studio — lote diário por mercado · */6h Paid Media · Seg 08:00 SEO & Site
  Dom 16:00 Gestor Social — calendário da semana por mercado · */30min publica o que venceu · 22:00 métricas dos posts
Estratégia
  05:00  Market Intel por mercado · Seg 10:00 estratégia da semana · dia 1 09:00 revisão de produto
  Ter 10:00 Analista de Mercado — ciclo de experimentos (encerra, aprende, propõe, realoca)
Prospecção
  09:30  prospecção diária por mercado · */4h follow-ups vencidos
Atendimento
  evento inbound (Jev → consultor) · */15min Concierge em viagem · follow-ups D+1/3/7 pela fila
Operacional
  */30min confirma reservas e emite · */15min resolve problemas · 09:00 catálogo/preços · 18:00 campo de amanhã (motoristas, guias, resolução)
  Seg 08:30 frota · último dia 17:00 folha motoristas · Ter 09:30 renovações · 08:15 presentes
Auditor
  02:00 auditoria diária · */1h SLA (sem LLM quando tudo ok) · Dom 20:00 melhorias da semana · Compliance após cada lote de conteúdo
Financeiro
  23:00 fechamento do dia · 09:00 cobrança e A/R · Seg 09:15 fluxo de caixa semanal
Parcerias · MICE · Pessoas · Jurídico · Reputação
  Qua 11:00 parceiras · dia 3 extratos de comissão · Qui 11:00 pipeline MICE · Seg 11:00 pessoas · dia 25 folha · Sex 10:00 jurídico · 12:00 avaliações públicas
Infra
  */5min SysOps health_cycle (sem LLM; sev1 → diagnose) · Seg 08:00 relatório de infra · 03:30 purge PII · */30min rollup KPIs · */60s poll e-mail
18:00  Frota & Motoristas  — agenda do dia seguinte para carros, motoristas e guias (HCTE)
Seg 08:30 Frota            — multas RTA, horas, revisões (HCTE)
Último dia 17:00 Frota     — insumo da folha dos motoristas (HCTE)
Ter 09:30 Admin & Renov.   — renovações, cotações, inventário e compras (HCTE)
08:15  Admin & Renov.      — presentes e abayas para chegadas em ≤ 2 dias (HCTE)
"""
from __future__ import annotations

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from brain.core import bus, db
from brain.settings import active_markets, agency_config

log = structlog.get_logger(__name__)
TZ = agency_config()["agency"].get("hq_timezone", "Asia/Dubai")


async def enqueue(agent: str, task: str, market_code: str | None = None, **payload: object) -> None:
    await bus.publish(bus.TASKS, {"agent": agent, "task": task, "market_code": market_code, **payload})


async def _fan_out(agent: str, task: str) -> None:
    for code in active_markets():
        await enqueue(agent, task, market_code=code)


def build() -> AsyncIOScheduler:
    s = AsyncIOScheduler(timezone=TZ)

    s.add_job(_fan_out, CronTrigger(hour=5, minute=0), args=["market_intel", "daily_refresh"], id="market_intel")
    s.add_job(_fan_out, CronTrigger(hour=6, minute=0), args=["content_studio", "daily_batch"], id="content_daily")
    s.add_job(enqueue, IntervalTrigger(hours=6), args=["paid_media", "optimize"], id="paid_media")
    # CEO (gabinete)
    s.add_job(enqueue, CronTrigger(hour=7, minute=0), args=["ceo", "ceo_briefing"], id="ceo_briefing")
    s.add_job(enqueue, IntervalTrigger(hours=2), args=["ceo", "approve_within_rules"], id="ceo_approve")
    s.add_job(enqueue, IntervalTrigger(hours=6), args=["ceo", "manage_agents"], id="ceo_manage")
    # Estratégia
    s.add_job(enqueue, CronTrigger(day_of_week="mon", hour=10, minute=0), args=["strategist", "weekly_strategy"], id="strategy_weekly")
    s.add_job(enqueue, CronTrigger(day=1, hour=9, minute=0), args=["strategist", "monthly_product_review"], id="strategy_products")
    s.add_job(enqueue, CronTrigger(day_of_week="tue", hour=10, minute=0), args=["market_analyst", "weekly_experiments"], id="growth_experiments")
    # Marketing — social
    s.add_job(_fan_out, CronTrigger(day_of_week="sun", hour=16, minute=0), args=["social_manager", "weekly_calendar"], id="social_calendar")
    s.add_job(enqueue, IntervalTrigger(minutes=30), args=["social_manager", "publish_cycle"], id="social_publish")
    s.add_job(enqueue, CronTrigger(hour=22, minute=0), args=["social_manager", "daily_metrics"], id="social_metrics")
    # Prospecção
    s.add_job(_fan_out, CronTrigger(hour=9, minute=30), args=["prospector", "daily_outreach"], id="prospect_daily")
    s.add_job(enqueue, IntervalTrigger(hours=4), args=["prospector", "followups_due"], id="prospect_followups")
    # Operacional — reservas, emissão e resolução
    s.add_job(enqueue, IntervalTrigger(minutes=30), args=["booking_payments", "confirm_pending"], id="ops_confirm")
    s.add_job(enqueue, IntervalTrigger(minutes=15), args=["booking_payments", "resolve_issues"], id="ops_resolve")
    # Financeiro
    s.add_job(enqueue, CronTrigger(hour=9, minute=0), args=["finance", "receivables_alerts"], id="finance_ar")
    s.add_job(enqueue, CronTrigger(day_of_week="mon", hour=9, minute=15), args=["finance", "weekly_cashflow"], id="finance_cash")
    # Infra
    s.add_job(enqueue, IntervalTrigger(minutes=5), args=["sysops", "health_cycle"], id="sysops_health")
    s.add_job(enqueue, CronTrigger(day_of_week="mon", hour=8, minute=0), args=["sysops", "weekly_report"], id="sysops_weekly")
    # Parcerias, MICE, Pessoas, Jurídico, Reputação
    s.add_job(enqueue, CronTrigger(day_of_week="wed", hour=11, minute=0), args=["partner_manager", "weekly_care"], id="partners_care")
    s.add_job(enqueue, CronTrigger(day=3, hour=10, minute=0), args=["partner_manager", "monthly_statements"], id="partners_statements")
    s.add_job(enqueue, CronTrigger(day_of_week="thu", hour=11, minute=0), args=["mice_events", "weekly_pipeline"], id="mice_pipeline")
    s.add_job(enqueue, CronTrigger(day_of_week="mon", hour=11, minute=0), args=["people_ops", "weekly_people"], id="people_weekly")
    s.add_job(enqueue, CronTrigger(day=25, hour=10, minute=0), args=["people_ops", "monthly_payroll"], id="people_payroll")
    s.add_job(enqueue, CronTrigger(day_of_week="fri", hour=10, minute=0), args=["legal_compliance", "weekly_review"], id="legal_weekly")
    s.add_job(enqueue, CronTrigger(hour=12, minute=0), args=["social_manager", "reviews_and_comments"], id="social_reputation")
    s.add_job(enqueue, CronTrigger(hour=9, minute=0), args=["suppliers_pricing", "refresh_catalog"], id="suppliers")
    s.add_job(_fan_out, CronTrigger(day_of_week="mon", hour=8, minute=0), args=["seo_site", "weekly_review"], id="seo")
    s.add_job(enqueue, CronTrigger(hour=23, minute=0), args=["finance", "daily_close"], id="finance")
    # Auditor (independente)
    s.add_job(enqueue, CronTrigger(hour=2, minute=0), args=["auditor", "daily_audit"], id="audit_daily")
    s.add_job(enqueue, IntervalTrigger(hours=1), args=["auditor", "sla_check"], id="audit_sla")
    s.add_job(enqueue, CronTrigger(day_of_week="sun", hour=20, minute=0), args=["auditor", "weekly_improvements"], id="audit_weekly")
    s.add_job(db.purge_expired_pii, CronTrigger(hour=3, minute=30), id="purge_pii")
    s.add_job(db.rollup_kpis, IntervalTrigger(minutes=30), id="kpis_rollup")
    s.add_job(enqueue, IntervalTrigger(minutes=15), args=["concierge", "in_trip_sweep"], id="concierge")
    s.add_job(enqueue, IntervalTrigger(minutes=5), args=["consultant", "proposal_desk"], id="proposal_desk")   # promessa de 30 min
    s.add_job(enqueue, IntervalTrigger(seconds=60), args=["_channels", "poll_email"], id="poll_email")

    # HCTE — campo e administração
    s.add_job(enqueue, CronTrigger(hour=18, minute=0), args=["fleet_dispatcher", "plan_tomorrow"], id="fleet_plan")
    s.add_job(enqueue, CronTrigger(day_of_week="mon", hour=8, minute=30), args=["fleet_dispatcher", "weekly_fleet_admin"], id="fleet_weekly")
    s.add_job(enqueue, CronTrigger(day="last", hour=17, minute=0), args=["fleet_dispatcher", "monthly_payroll_input"], id="fleet_payroll")
    s.add_job(enqueue, CronTrigger(day_of_week="tue", hour=9, minute=30), args=["admin_renewals", "weekly_review"], id="admin_weekly")
    s.add_job(enqueue, CronTrigger(hour=8, minute=15), args=["admin_renewals", "gifts_for_arrivals"], id="admin_gifts")

    log.info("scheduler_built", jobs=[j.id for j in s.get_jobs()], tz=TZ)
    return s
