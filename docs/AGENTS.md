# Os 24 agentes em 8 departamentos (o consultor em 7 instâncias, uma por idioma)

Organograma e missão por departamento: `config/departments.yaml` e `docs/ORG.md`. Decisões tipadas (classificação, score, sim/não) são do **Jev** (`brain/core/jev.py`); texto, planejamento e uso de ferramentas são do Claude.

| Dep. | Agente | Arquivo / prompt | Modelo | Gatilho | Ferramentas MCP | Onde o Jev entra |
| --- | --- | --- | --- | --- | --- | --- |
| CEO | CEO-agente | `ceo.py` / `ceo.md` | Opus 5 | chat do dashboard (`POST /api/ceo/chat`); 07:00 briefing; */2h aprova dentro das regras; */6h gere agentes | company, ops, handoff | `route_model` ao delegar |
| CEO | SysOps | `sysops.py` / `.md` | Haiku 4.5 (checagem sem LLM) | */5min health_cycle; diagnose em sev1; seg 08:00 relatório | sysops, handoff | — |
| Marketing | Content Studio | `content_studio.py` / `.md` | Sonnet 5 (Opus p/ blog) | 06:00 por mercado; sob delegação | knowledge, marketing | — (moderação no Compliance) |
| Marketing | Gestor de Conteúdo Social (+ reputação) | `social_manager.py` / `.md` | Sonnet 5 | dom 16:00 calendário por mercado; */30min publica (sem LLM); 22:00 métricas; 12:00 avaliações públicas | social, marketing, knowledge, handoff | `plan_post`: qualidade, gancho, CTA, risco → agenda direto se ≥ 0,8 |
| Marketing | Paid Media | `paid_media.py` / `.md` | Sonnet 5 | */6h; após estratégia semanal | marketing, ops, handoff | — |
| Marketing | SEO & Site | `seo_site.py` / `.md` | Sonnet 5 | seg 08:00 por mercado | knowledge, marketing | — |
| Estratégia | Estrategista | `strategist.py` / `.md` | Opus 5 | seg 10:00; dia 1 09:00; cenário sob demanda | ops, marketing, catalog, knowledge, prospects, handoff | atratividade de cada pacote proposto |
| Estratégia | Analista de Marketing & Tráfego | `market_analyst.py` / `.md` | Opus 5 | ter 10:00 ciclo de experimentos; `research_market` / `market_entry_plan` sob delegação | growth, marketing, knowledge, prospects, handoff | promessa da hipótese; veredito won/lost/inconclusive |
| Estratégia | Market Intel | `market_intel.py` / `.md` | Sonnet 5 | 05:00 por mercado | knowledge | — |
| Prospecção | Prospector B2B | `prospector.py` / `.md` | Sonnet 5 | 09:30 por mercado; */4h follow-ups; mensagem de agência recebida | prospects, knowledge, handoff | `prospect_fit`; classificação da resposta |
| Prospecção & Parcerias | Gestor de Parceiras B2B | `partner_manager.py` / `.md` | Sonnet 5 | qua 11:00 cuidado; dia 3 extratos; cotação B2B sob demanda | partners, quotes, catalog, knowledge, handoff | health_score da parceria |
| Atendimento | Roteador | `escalation_router.py` / `.md` | **Jev** (Haiku 4.5 só fallback) | toda mensagem inbound | — | `triage`: mercado, intenção, urgência, sentimento, emergência, pedido de humano, compliance, **injeção de prompt**, VIP |
| Atendimento | Consultor (x7) | `consultant.py` / `.md` + `config/markets/XX.yaml` | Sonnet 5 | toda mensagem; follow-ups D+1/3/7 | crm, catalog, quotes, payments, knowledge, handoff | `lead_score` após cada troca (fit, compra em 30 d, segmento, faixa) |
| Atendimento | Concierge | `concierge.py` / `.md` | Sonnet 5 | */15min em viagem; pós-viagem | ops, crm, catalog, knowledge, handoff | `sentiment`: CSAT, churn, upsell |
| Atendimento | MICE & Eventos (HCB1) | `mice_events.py` / `.md` | Sonnet 5 | evento `mice` roteado; qui 11:00 pipeline e feiras | mice, crm, catalog, quotes, knowledge, handoff | probabilidade de fechar; viabilidade de datas |
| Operacional | Reservas, Emissão & Resolução | `booking_payments.py` / `.md` | Sonnet 5 | */30min confirma+emite; */15min resolve; e-mail de fornecedor; webhook de pagamento | ops, payments, resolution, crm, handoff | `classify_supplier_reply`; severidade do problema; presença humana? |
| Operacional | Fornecedores & Preços | `suppliers_pricing.py` / `.md` | Sonnet 5 | 09:00 | catalog, knowledge, ops | — |
| Operacional | Frota, Motoristas & Resolução em campo | `fleet_dispatcher.py` / `.md` | Sonnet 5 | 18:00 agenda D+1 (motoristas, guias, pessoal de resolução); seg 08:30; último dia | fleet, ops, crm, resolution, handoff | — |
| Operacional | Admin & Renovações | `admin_renewals.py` / `.md` | Haiku 4.5 | ter 09:30; 08:15 presentes | admin, ops, handoff | — |
| Operacional | Pessoas | `people_ops.py` / `.md` | Sonnet 5 | seg 11:00 rotina; dia 25 folha | people, knowledge, prospects, handoff | — |
| Auditor | Auditor (independente) | `auditor.py` / `.md` | Opus 5 | 02:00 diária; */1h SLA (sem LLM se ok); dom 20:00 melhorias | audit, ops, marketing, handoff | `audit_scores` por dimensão, `flow_followed`, `hallucination` |
| Auditor | Compliance | `compliance.py` / `.md` | Sonnet 5 | após cada lote de conteúdo/anúncios | marketing | `moderate` pré-triagem: allow sem flags aprova sozinho |
| Auditor & Compliance | Jurídico, Dados & Regulatório | `legal_compliance.py` / `.md` | Opus 5 | sex 10:00 revisão; review_document / handle_crisis sob demanda | legal, knowledge, prospects, handoff | `review_text_for_legal_risk`: risco, cláusula abusiva, admissão de culpa, ameaça |
| Financeiro | Financeiro | `finance.py` / `.md` | Sonnet 5 | 23:00 fechamento; 09:00 cobrança/A/R; seg 09:15 caixa; webhook de pagamento | ops, marketing, billing, handoff | risco de inadimplência por fatura |

Em todos: **gate de risco** (`agent_base.RISKY_TOOLS` → `jev.tool_risk` no hook PreToolUse) antes de pagamento, reembolso, envio ao cliente, cancelamento, pausa de campanha, agenda de campo, decisão.

## Como adicionar ou mudar um agente

1. Prompt em `prompts/<nome>.md` (Jinja2; recebe `agency`, `autonomy`, `policies`, `products`, `kpis`, `market`, `today` e `shared_*` — inclua `{{ shared_agency_context }}` no topo).
2. Classe em `brain/agents/<nome>.py` herdando `BaseAgent`: `name`, `department`, `tier`, `allowed`, `tools()` e os métodos que o scheduler/orquestrador/CEO chamam.
3. Registre em `brain/core/registry.py`, em `config/departments.yaml` (departamento e, se o CEO-agente pode delegar, em `delegation.ceo`) e em `brain/tools/company.py → DELEGABLE`; se periódico, em `brain/core/scheduler.py`.
4. Orçamento em `config/budgets.yaml → tokens.per_agent_daily_cap_usd`.
5. Rode `make evals` e `make check` antes de subir.

## Como adicionar um mercado

Copie `config/markets/GB.yaml`, ajuste persona/idioma/moeda/objeções/picos/compliance, adicione o código em `budgets.yaml → split_pct` e `markets` no banco (`001_init.sql` seeds). O consultor, o prospector e o conteúdo passam a rodar para ele automaticamente.
