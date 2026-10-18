# Validação final da empresa — áreas, cobertura e lacunas (out/2026)

Método: lista de tudo o que uma agência receptiva/emissiva licenciada em Dubai (DMC + eventos, com frota própria) precisa fazer para operar 24/7 sem equipe de escritório, cruzada com os manuais da HCTE (organograma, RH, administrativo, treinamentos) e com o que a máquina já faz. Cada linha diz quem cobre, o que faltava e o que foi feito nesta rodada.

## 1. Matriz por área

| Área | Funções essenciais | Cobertura antes | Lacuna | Decisão nesta rodada |
| --- | --- | --- | --- | --- |
| **Direção** | metas, decisões, prestação de contas, gestão da equipe | `ceo` (chat, briefing, aprovações, pausa de agentes) | nenhuma | — |
| **Marketing** | conteúdo, redes, mídia paga, SEO, **reputação (avaliações e comentários públicos)** | content_studio, social_manager, paid_media, seo_site | ninguém respondia a avaliações Google/Tripadvisor e comentários públicos; crise pública sem dono | `social_manager.reviews_and_comments` (diário) + protocolo de crise no Jurídico |
| **Estratégia** | produto, preço, cenários, inteligência de mercado, mercados novos | strategist, market_intel, market_analyst | nenhuma | — |
| **Vendas B2C** | triagem, consultoria, cotação, fechamento, follow-up | escalation_router (Jev), consultant x7, concierge | nenhuma | — |
| **Vendas B2B** | prospecção, **gestão da parceira depois de fechada** (onboarding, net rates, cotações para agências, extrato de comissão, material white-label) | prospector | prospector só abria a porta; cotação B2B e comissão não tinham dono | **novo `partner_manager`** (Prospecção & Parcerias) |
| **MICE & eventos (HCB1 Events Management LLC)** | RFP, grupos ≥ 20 pax, feiras (DWTC/Expo City), venues, credenciamento, faturamento pela HCB1 | consultor abria decisão `mice` para a CEO; nada mais | linha de receita inteira sem fluxo próprio | **novo `mice_events`** (Atendimento) |
| **Operações** | reservas, emissão, confirmação, vouchers, problemas, visto, seguro, eSIM | booking_payments, suppliers_pricing | nenhuma | — |
| **Campo** | motoristas, guias, carros, pessoal de resolução, presentes/abaya | fleet_dispatcher, admin_renewals | nenhuma | — |
| **Pessoas (humanos que ficam)** | folgas/escala, horas e extras, visto/labour dos motoristas via PRO, **recrutamento e vetting de guias freelancers**, treinamento, WPS, documentos a vencer, ocorrências disciplinares | fleet (horas/folha) + admin (renovações) parcialmente | ninguém geria o quadro humano como quadro: escala de folgas, pool de guias, avaliações, labour law | **novo `people_ops`** (Operacional) |
| **Financeiro** | caixa, A/R, A/P, cobrança, fechamento, contador, VAT/CT | finance | comissões a pagar a parceiras entram em A/P? (sim, via partner_manager → `record_payable`) | — |
| **Jurídico, dados e regulatório** | contratos (parceiras, fornecedores, clientes/termos), **PDPL/LGPD/GDPR/DPDP — pedidos de titulares (DSAR)**, incidentes de dados, **screening de sanções** (RU/CIS), obrigações DET/licença, reclamações formais (DET Consumer), seguro de responsabilidade | compliance (só conteúdo/anúncios); regras nos prompts | área inteira sem dono operacional | **novo `legal_compliance`** (Auditor & Compliance) |
| **Qualidade e auditoria** | SLAs, fluxo, notas, melhorias | auditor | nenhuma | — |
| **Infra da máquina** | saúde de banco/filas/webhooks, backups verificados, certificados, quotas de API, rotação de segredos, custo de tokens, incidentes | `ceo.manage_agents` (erros/custo) + runbook humano | sem monitor próprio; um webhook caído = clientes sem resposta sem ninguém saber | **novo `sysops`** (gabinete; sem LLM na maior parte) |
| **Comunicação de crise** | eventos geopolíticos, acidente com cliente, imprensa | market_intel (fatos) + "resposta pública → CEO" | sem protocolo escrito de quem redige, quem aprova, em quanto tempo | protocolo em `prompts/_shared/crisis_protocol.md`, dono: `legal_compliance`, aprovação: CEO humana |

Áreas consideradas e **não** criadas (cobertas ou fora de escopo): recrutamento de equipe de escritório (não haverá), contabilidade formal (contador externo recebe o pacote do Financeiro), emissão aérea (fase 2, `products.sell_air`), desenvolvimento do site (documento SITE_HIGHCLASS + SEO & Site), tradução (consultores nativos por mercado + guias humanos).

## 2. Resultado

8 departamentos permanecem; **5 agentes novos** entram em departamentos existentes (24 agentes). Prospecção vira **Prospecção & Parcerias**; Auditor vira **Auditor & Compliance** (conteúdo + jurídico/dados).

| Departamento | Agentes |
| --- | --- |
| CEO (gabinete) | ceo, **sysops** |
| Marketing | content_studio, social_manager (+ reputação), paid_media, seo_site |
| Estratégia | strategist, market_intel, market_analyst |
| Prospecção & Parcerias | prospector, **partner_manager** |
| Atendimento | escalation_router, consultant ×7, concierge, **mice_events** |
| Operacional | booking_payments, suppliers_pricing, fleet_dispatcher, admin_renewals, **people_ops** |
| Auditor & Compliance | auditor, compliance, **legal_compliance** |
| Financeiro | finance |

## 3. Prompts definitivos — o contrato comum

Todo prompt agora é montado sobre `prompts/_shared/agency_context.md` (identidade, regras invioláveis, políticas) + `departments.md` (organograma, Jev, 24/7) + **`agent_contract.md`** (como todo agente trabalha: lê antes de agir, nunca inventa, trata falha de ferramenta, respeita o Jev e o gate de risco, formato de saída, o que nunca faz) e segue a mesma espinha: **Missão → O que você recebe → Como trabalha → O que decide sozinho / o que vai para a CEO → Saída → Nunca**. Os prompts de mercado (consultor, content, social, SEO, analista) recebem `config/markets/XX.yaml`.

## 4. Verificação

`make check`: 24 agentes · 8 departamentos · todas as ferramentas em `allowed` existem · todos os prompts renderizam para os 7 mercados · scheduler aponta para métodos existentes · orçamentos de tokens para todos · zero credenciais no repositório. Casos de eval: 15 (consultor + roteador). Dashboard: departamentos, chat da CEO, experimentos, operação & finanças, prospecção, auditoria.

## 5. O que ainda depende de humanos (e está certo que dependa)

Assinatura de contratos e decisões fora da política (CEO), motoristas, guias/tradutores, pessoal de resolução presencial, PRO (vistos/labour), contador, advogado para casos em andamento. A máquina prepara, agenda, cobra e documenta; essas pessoas executam o que só uma pessoa pode.
