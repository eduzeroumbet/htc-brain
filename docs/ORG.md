# Organograma da agência 100% IA (VM única, 24/7)

```
                         ┌──────────────────────────────┐
                         │   CEO humana (Larissa)       │  dashboard: chat + decisões · WhatsApp: briefing 07:00 + alertas
                         └──────────────┬───────────────┘
                                        │ fala / decide
                         ┌──────────────▼───────────────┐
                         │ CEO-agente + SysOps          │  company_snapshot · delegate_task · decide · pause_agent · health_cycle */5min
                         └──┬────┬────┬────┬────┬───┬───┘
        delega ↓           ↓    ↓    ↓    ↓    ↓   ↓                        (não delega ao Auditor)
 ┌────────────┐ ┌──────────┐ ┌──────────┐ ┌───────────┐ ┌───────────┐ ┌──────────┐      ┌─────────────────┐
 │ Marketing  │ │Estratégia│ │Prosp.&Par│ │Atendimento│ │Operacional│ │Financeiro│      │ Auditor & Compl.│
 │ content    │ │strategist│ │prospector│ │ router    │ │ booking/  │ │ finance  │      │ auditor         │
 │ social_mgr │ │market_   │ │partner_  │ │ consultant│ │  issuance/│ │          │      │ compliance      │
 │ paid_media │ │  intel   │ │  manager │ │ concierge │ │  resolution│ │          │      │ legal_          │
 │ seo_site   │ │ analyst  │ │          │ │ mice_evts │ │ suppliers │ └──────────┘      │  compliance     │
                                                        │ fleet     │                   └─────────────────┘
                                                        │ admin     │
                                                        │ people    │
                                                        └─────┬─────┘
                                      programação (WhatsApp de campo) ↓
                              motoristas · guias/tradutores · pessoal de resolução (humanos)
```

## Fluxos ponta a ponta

**Lead → venda (Atendimento).** Mensagem chega (WhatsApp/Telegram/IG/Messenger/webchat/e-mail) → `inbound` → **Jev triage** (< 0,5 s: mercado, intenção, urgência, sentimento, emergência, pedido de humano, compliance, injeção, VIP) → gatilho humano? mensagem-ponte + caso no Chatwoot : **Consultor** do mercado responde em segundos com persona local → qualifica (≤ 4 perguntas) → cota (`build_quote` + PDF ≤ 15 min) → link de pagamento → `accept_quote` cria a reserva → **Jev lead_score** atualiza fit/compra/segmento. Follow-ups D+1/3/7 só com consentimento.

**Reserva → viagem (Operacional).** `confirm_pending` a cada 30 min: fornecedor na prioridade HCTE → confirmação (e-mail classificado pelo Jev) → emissão (`request_issuance` → `record_issuance`) → vouchers → **Frota** monta a agenda D+1 às 18:00 (carro pela regra de bagagem, motorista ≤ 12 h, guia licenciado, presentes/abaya do Admin) e envia por WhatsApp → **Concierge** D-1 até o pós-retorno. **Financeiro** cria a fatura (30% / saldo D-14), cobra, baixa pelo webhook.

**Problema em viagem.** Qualquer agente abre `open_issue` (Jev: severidade e "precisa de alguém presencial?") → `resolve_issues` a cada 15 min: reemitir/trocar/fornecedor/reembolso na política/`assign_issue_to_staff` (programação ao funcionário de resolução) → cliente informado a cada mudança (nunca > 30 min sem notícia) → critical também escala para humano.

**Mercados novos (Analista + Social).** Para RU, IN, SA, DE, US o Analista parte de `knowledge/markets/<XX>.md` (base com itens [verificar]), confirma com fontes primárias, grava o playbook (`market_playbooks`) e propõe experimentos de 14 dias com budget mínimo, métrica, alvo e regra de kill. Dentro de `media.experiments` (25% do budget do mercado, 2 simultâneos) ele aprova e inicia sozinho; canal novo com conta/intermediário, mercado em onda 2 ou gasto acima do teto viram decisão da CEO. Veredito por número (Jev confirma): vencedor → Paid Media escala; perdedor → playbook registra o CPL real. O Gestor Social usa o mesmo playbook para calendário, formato e regras de cada rede (ex.: ERID em posts pagos na Rússia).

**Marketing & Estratégia.** Estrategista (seg 10:00) lê KPIs, campanhas, conteúdo, prospecção e "Dubai agora" → 3 apostas + realocação de tráfego → Paid Media executa dentro do teto; Content Studio produz por mercado → **Jev moderate** pré-aprova o limpo → Compliance decide o resto → publicação. Dia 1: pacotes novos (JSON → `product_proposals`, Jev pontua, CEO aprova).

**Prospecção B2B.** 09:30 por mercado: busca → cadastro (Jev fit) → sequência 1/D+4/D+10/D+30 no idioma da agência → respostas classificadas pelo Jev → call → parceira (comissão padrão 10%; acima → CEO). Agência que escreve em qualquer canal do Atendimento é roteada à Prospecção.

**Auditoria.** 02:00: 12 conversas (Jev âncora + rubrica), conformidade do fluxo por reserva, SLAs reais, departamentos silenciosos → achados com evidência e mudança exata → CEO decide. A cada hora: contadores duros, sem LLM se tudo ok. Domingo: melhorias da semana.

## Autonomia e humanos

| Decide sozinha | Vira decisão da CEO (dashboard) | Vai para humano (Chatwoot/WhatsApp) |
| --- | --- | --- |
| desconto ≤ 5% (consultor), 5–10% com margem ≥ 12% (CEO-agente); reembolso ≤ USD 500 na política; realocação de mídia no teto; fornecedor na ordem de prioridade; emissão; agenda de campo; cobrança; pausa de agente com erro | desconto > 10%; reserva ≥ USD 5.000; reembolso > USD 500; novo fornecedor/mercado; teto de mídia; comissão B2B > 10% ou exclusividade; mudança de persona/preço/escalonamento; MICE ≥ 20 pax; novo pacote | emergência em viagem; pedido explícito de pessoa; reclamação grave confirmada; risco de compliance; incerteza do agente; chegada VIP; problema que exige presença física |

Humanos que ficam e o que recebem da máquina: **motoristas** (agenda diária, briefing, botões a caminho/a bordo/concluído), **guias/tradutores** (briefing por reserva, TGD, abaya), **pessoal de resolução** (programação por problema: hora, local, 3 linhas do que fazer, OK/resolvido), **plantão de suporte avançado** (só os gatilhos), **contador/PRO/advogado** (relatórios prontos).

## Jev em uma tabela

| Decisão | Função (`brain/core/jev.py`) | Quem usa | Fallback sem Jev |
| --- | --- | --- | --- |
| Triagem completa da mensagem | `triage` | roteador | Haiku + regras de palavra-chave |
| Lead: fit, compra 30 d, segmento, faixa | `lead_score` | consultor | nenhum (campo fica nulo) |
| Risco de ferramenta antes de executar | `tool_risk` | todos (hook PreToolUse) | sem gate (política do prompt) |
| Moderação de peça/anúncio | `moderate` | compliance | Compliance lê tudo |
| Modelo por complexidade | `route_model` | CEO ao delegar | `work` |
| Notas da rubrica, fluxo seguido, alucinação | `audit_scores` | auditor | nota só do Opus |
| E-mail de fornecedor | `classify_supplier_reply` | operacional | agente lê |
| Sentimento, churn, upsell | `sentiment` | concierge | — |
| Fit de agência parceira | `prospect_fit` | prospector | fit nulo, contata todas com e-mail |
| Severidade de problema, presença humana | `decide` ad hoc | operacional | medium / não |
| Risco de inadimplência | `decide` ad hoc | financeiro | — |
| Atratividade de pacote | `decide` ad hoc | estrategista | — |

Custo: ~USD 0,42 por milhão de tokens de estado; orçamento diário em `config/budgets.yaml → jev_daily_cap_usd`. Pinar `JEV_MODEL` em produção.

## Áreas acrescentadas na validação final (out/2026)
Ver `docs/VALIDACAO_FINAL.md`. Em resumo: **SysOps** (saúde da máquina a cada 5 min, incidentes sev1–3, backups, segredos); **Gestor de Parceiras B2B** (onboarding, cotação net, extrato de comissão → A/P, saúde da relação); **MICE & Eventos** pela HCB1 (RFP, capacidade, proposta, feiras); **Pessoas** (escala, documentos, ocorrências, pool de guias, folha/WPS, PRO); **Jurídico, Dados & Regulatório** (contratos, DSAR, sanções, incidentes, protocolo de crise); **reputação** no Gestor Social (avaliações e comentários públicos). Prompts seguem o contrato comum `prompts/_shared/agent_contract.md`.
