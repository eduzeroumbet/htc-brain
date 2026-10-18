> **Atualização (out/2026):** a máquina foi reorganizada em **8 departamentos e 17 agentes** (CEO, Marketing, Estratégia, Prospecção, Atendimento, Operacional, Auditor, Financeiro) com o **Jev / TypeSafe AI** tomando as decisões tipadas. O organograma vigente está em `docs/ORG.md` e `config/departments.yaml`; este blueprint permanece como base estratégica (mercados, dados, metas).

# Blueprint (resumo) — Agência 100% IA para Dubai & EAU

Versão completa e viva (dados, mercados, ofertas, equipe, fluxos, arquitetura, compliance, economia, roadmap):
**https://claude.ai/code/artifact/bd693f1b-3c91-4031-845f-fbe3a71f4e8e**

## A tese em um parágrafo

Uma agência licenciada pela DET em Dubai, operada por 13 papéis de IA (19 agentes contando os 7 consultores por idioma) em uma única máquina, vendendo Dubai e Abu Dhabi para os seis maiores mercados emissores além do Brasil — Índia, Arábia Saudita/GCC, Reino Unido (onda 1); Rússia/CIS, Alemanha, EUA (onda 2) — com atendimento autônomo 24/7 em 7 idiomas e o CEO gerindo por dashboard. O momento é uma janela: Dubai fechou 2025 com recorde de 19,59 milhões de visitantes, a guerra EUA/Israel–Irã derrubou a chegada em 44% no acumulado de 2026, e a recuperação (869 mil visitantes em agosto, ocupação 36% → 66%) vem com incentivos do governo, preços baixos e concorrência enfraquecida.

## Números que sustentam a estratégia

| Dado | Valor | Fonte |
| --- | --- | --- |
| Visitantes internacionais Dubai 2025 | 19,59 mi (+5%) | DET |
| Regiões 2025 | Europa Ocidental 21% · GCC 15% · CIS 15% · Sul da Ásia 15% · MENA 11% · NE/SE Ásia 9% · Américas 7% | DET |
| Maiores países (est. 2023) | Índia 2,2 mi · Omã 1,6 mi · Arábia Saudita 1,45 mi · Reino Unido 1,25 mi · Rússia 0,9 mi · EUA 0,7 mi · Alemanha 0,5 mi | DET 2022 + GMI |
| Jan–Ago 2026 | 6,97 mi (−44%); agosto 869 mil; ocupação 66% | DET, 14/09/2026 |
| Resposta do governo | AED 2,5 bi; taxa municipal 7% zerada; Tourism Dirham suspensa (luxo); A Dubai Invite | DET, GDMO |
| Companhias suspensas | 15 (BA, Lufthansa, KLM, Air France, Singapore, Cathay, Air Canada…) retomam out/2026–2027 | Time Out Dubai |
| Brasil | +18% em 2025 vs +5% global; Emirates diária GRU e GIG; +82% reservas (Civitatis) | DET/ABAV, Panrotas |
| Abu Dhabi 2025 | 26,6 mi visitação; 5,9 mi hóspedes de hotel | DCT Abu Dhabi |

## Metas

90 dias: 5 mercados no ar, 1.500 leads qualificados/mês, 60 reservas/mês, ticket USD 1.400, margem 16%, CAC < USD 120, escalonamento < 4%, primeira resposta < 60 s. Ponto de equilíbrio: ~45 reservas/mês.

## Como este repositório implementa o blueprint

| Blueprint | No código |
| --- | --- |
| Mercados-alvo e personas | `config/markets/*.yaml` |
| Equipe de 13 papéis de IA | `brain/agents/`, `prompts/` |
| Fluxos (conteúdo, tráfego, vendas, pós-venda) | `brain/core/scheduler.py`, `brain/core/orchestrator.py` |
| Escalonamento humano (6 gatilhos) | `config/escalation.yaml`, `brain/tools/handoff.py`, Chatwoot |
| Autonomia e aprovações do CEO | `config/agency.yaml → autonomy`, tabela `decisions`, dashboard |
| Orçamentos de mídia e tokens | `config/budgets.yaml`, `brain/core/agent_base.py` |
| Arquitetura da máquina | `docker-compose.yml`, `Dockerfile`, `deploy/Caddyfile` |
| Dashboard do CEO | `brain/dashboard/` |
| Compliance | `prompts/compliance.md`, notas por mercado, `purge_expired_pii` |
| Economia | `prompts/finance.md`, `kpis_daily`, `v_funnel_30d` |
