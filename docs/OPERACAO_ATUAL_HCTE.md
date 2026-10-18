# HCTE — operação atual e o que muda (resumo)

Análise completa, viva e comentável: **https://claude.ai/code/artifact/e0997291-e5a3-481f-86a3-b18aa8e44cd8**

Fonte: os 12 manuais da pasta HTC (organograma 2026, workflow 09/07/2026, manuais administrativo e de RH 2026,
processo de entrada, sales kit, portfólio, 4 treinamentos). Credenciais presentes nos manuais foram omitidas
e **não devem** ser ingeridas na base de conhecimento.

## A empresa

High Class Experiences Travel LLC (HCTE), Dubai desde 2010. Licença de operador inbound/outbound **781806**
(renova 2/mai), **IATA 96029802**, HCB1 Events Management LLC (eventos, licença 1309916). Frota própria:
Cadillac Escalade 2023, GMC Yukon 2025, GAC M8 2026. Parceiros em Omã, Catar e Arábia Saudita. Base de clientes
brasileiros de alta renda e celebridades. Sala 1701, Burj Al Salam Tower (contrato e Ejari com decisão pendente).

## Quem faz o quê hoje → quem faz depois

| Cargo hoje | Depois |
| --- | --- |
| COO | CEO-agente + Auditor + Fornecedores & Preços; contratos anuais: CEO |
| RH, Admin e assistente da CEO | Admin & Renovações (novo) + CEO-agente |
| Finanças e Admin | Financeiro + Reservas & Pagamentos + Frota & Motoristas (novo) |
| Business Development | Paid Media + Content Studio + SEO + Consultor; feiras: CEO |
| Customer Service & Ops (2) | Consultor por idioma + Reservas & Pagamentos + Concierge + Frota |
| Chauffeur / fleet control (2) | **Ficam** — recebem a agenda do Frota & Motoristas |
| Guias e tradutores (freelancers) | **Ficam** — escalados e briefados pelo Frota; TGD por reserva |
| Suporte avançado | **Novo papel humano**: CEO + 1 sênior em plantão semanal, acionado só pelos gatilhos |

## O fluxo de 9 etapas → estados da máquina

| # | Etapa HCTE | Estado (`leads.stage` / `bookings.status`) | SLA antes → depois |
| --- | --- | --- | --- |
| 1 | Client requested proposal | `new` → `qualifying` | < 3 h → < 60 s |
| 2 | Build an itinerary | `qualified` | 24–48 h → 5–15 min |
| 3 | Send & update proposal | `quoted` → `negotiating` | 5 dias de follow-up → D+1/D+3/D+7 |
| 4 | Invoice & payment | `won` + `bookings.payment_status` | dias → webhook |
| 5 | Bookings & reservations | `confirming` | 24–48 h → 2 h |
| 6 | Confirmation of bookings | `confirmed` | — → automático |
| 7 | Final information | `confirmed` (D-2, grupo WhatsApp) | D-2 |
| 8 | Customer in house | `in_trip` | diário, 24/7 |
| 9 | Client feedback / completed | `completed` | D+1 do retorno |

## Onde cada coisa dos manuais foi parar no scaffold

| Assunto | Arquivo |
| --- | --- |
| Identidade, licença, IATA, HCB1, protocolo VIP, política de pagamento (PIX/12x, link ≤ USD 10k), noites mínimas | `config/agency.yaml` |
| Motoristas, guias, plantão, parceiros externos | `config/humans.yaml` |
| Prioridade de fornecedores (contratado → Turning Point/Connect World → Elevate/Passage; hotéis direto → Elevate → Travolgo → Desert Gate) | `config/suppliers_hcte.yaml`, `prompts/suppliers_pricing.md` |
| Calendário de renovações (licenças, seguros, Ejari, Mulkiyas, PO Box, contratos) e inventário | `config/renewals_hcte.yaml` |
| Gatilhos de negócio (MICE > 20 pax, contrato anual, imprensa) e chegada de VIP | `config/escalation.yaml` |
| Mercado Brasil com segmentos VIP e perguntas de qualificação do treinamento de hotéis | `config/markets/BR.yaml` |
| Conhecimento dos 4 treinamentos (49 atrações, hotéis por perfil, capacidade dos carros, regras de ouro) | `knowledge/hcte/*.md` + `scripts/ingest_knowledge.py` |
| Frota, motoristas, guias, escala diária, horas, multas, renovações, inventário | `db/migrations/002_hcte.sql`, `brain/tools/fleet.py`, `brain/tools/admin.py` |
| Agente Frota & Motoristas (18h agenda; seg multas/horas; fim do mês folha) | `brain/agents/fleet_dispatcher.py`, `prompts/fleet_dispatcher.md` |
| Agente Admin & Renovações (ter revisão; 08:15 presentes/abayas) | `brain/agents/admin_renewals.py`, `prompts/admin_renewals.md` |
| Painel "Campo & renovações" no dashboard (substitui o quadro branco) | `brain/dashboard/api.py` (`/api/field`, `/api/renewals`), `static/` |
| Toque HCTE no pós-venda (grupo D-2, presentes, abaya, comissão da agência) | `prompts/concierge.md` |

## Migração de dados (antes de desligar os sistemas antigos)

Ver `scripts/migrate_hcte.md`: HCTE System e Zoho → `leads`/`quotes`; price list e planilhas de fornecedores →
`suppliers`/`catalog_items`; inventário → `inventory`; frota → já semeada em `002_hcte.sql`; treinamentos →
`make ingest-knowledge`; renovações → `make sync-renewals`.

## Primeiras ações (semana 1)

1. Rotacionar todas as credenciais listadas nos manuais; cofre de segredos; UAE Pass nunca compartilhado.
2. `make up && make migrate && make ingest-knowledge && make sync-renewals` — o dashboard já mostra a Mulkiya do Yukon (21/10/2026).
3. Exportar HCTE System, Zoho e planilhas; importar catálogo.
4. Definir a pessoa sênior do plantão e a data-alvo da saída formal (dezembro, após a sombra de outubro).
