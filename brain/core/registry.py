"""Registro dos 24 agentes em 8 departamentos (config/departments.yaml). `get(name)` devolve uma instância pronta."""
from __future__ import annotations

from functools import lru_cache

from brain.agents.admin_renewals import AdminRenewalsAgent
from brain.agents.auditor import AuditorAgent
from brain.agents.booking_payments import BookingPaymentsAgent
from brain.agents.ceo import CEOAgent
from brain.agents.compliance import ComplianceAgent
from brain.agents.concierge import ConciergeAgent
from brain.agents.consultant import ConsultantAgent
from brain.agents.content_studio import ContentStudioAgent
from brain.agents.escalation_router import EscalationRouterAgent
from brain.agents.finance import FinanceAgent
from brain.agents.fleet_dispatcher import FleetDispatcherAgent
from brain.agents.market_analyst import MarketAnalystAgent
from brain.agents.legal_compliance import LegalComplianceAgent
from brain.agents.market_intel import MarketIntelAgent
from brain.agents.mice_events import MiceEventsAgent
from brain.agents.paid_media import PaidMediaAgent
from brain.agents.partner_manager import PartnerManagerAgent
from brain.agents.people_ops import PeopleOpsAgent
from brain.agents.prospector import ProspectorAgent
from brain.agents.seo_site import SeoSiteAgent
from brain.agents.social_manager import SocialManagerAgent
from brain.agents.strategist import StrategistAgent
from brain.agents.suppliers_pricing import SuppliersPricingAgent
from brain.agents.sysops import SysOpsAgent
from brain.core.agent_base import BaseAgent

ROSTER: dict[str, type[BaseAgent]] = {
    # CEO (gabinete)
    "ceo": CEOAgent,
    "sysops": SysOpsAgent,
    # Marketing
    "content_studio": ContentStudioAgent,
    "paid_media": PaidMediaAgent,
    "seo_site": SeoSiteAgent,
    "social_manager": SocialManagerAgent,
    # Estratégia
    "strategist": StrategistAgent,
    "market_intel": MarketIntelAgent,
    "market_analyst": MarketAnalystAgent,
    # Prospecção
    "prospector": ProspectorAgent,
    "partner_manager": PartnerManagerAgent,
    # Atendimento
    "escalation_router": EscalationRouterAgent,
    "consultant": ConsultantAgent,
    "concierge": ConciergeAgent,
    "mice_events": MiceEventsAgent,
    # Operacional
    "booking_payments": BookingPaymentsAgent,
    "suppliers_pricing": SuppliersPricingAgent,
    "fleet_dispatcher": FleetDispatcherAgent,
    "admin_renewals": AdminRenewalsAgent,
    "people_ops": PeopleOpsAgent,
    # Auditor
    "auditor": AuditorAgent,
    "compliance": ComplianceAgent,
    "legal_compliance": LegalComplianceAgent,
    # Financeiro
    "finance": FinanceAgent,
}

DEPARTMENT_OF: dict[str, str] = {name: cls.department for name, cls in ROSTER.items()}


@lru_cache
def get(name: str) -> BaseAgent:
    try:
        return ROSTER[name]()
    except KeyError as exc:
        raise ValueError(f"agente desconhecido: {name}. Válidos: {', '.join(ROSTER)}") from exc
