# dubai-ai-agency — o cérebro da High Class Travel Experiences (HCTE)

Uma máquina. Quinze papéis de IA, sete consultores por idioma. Dois motoristas, guias freelancers e um
plantão humano. Uma CEO no dashboard.

Este repositório é o scaffold operacional de dois documentos vivos no Claude:
- **Blueprint "Agência 100% IA — Dubai & EAU"**: https://claude.ai/code/artifact/bd693f1b-3c91-4031-845f-fbe3a71f4e8e
- **"HCTE — Análise da Operação e Transição para o Time de IA"** (dos 12 manuais):
  https://claude.ai/code/artifact/e0997291-e5a3-481f-86a3-b18aa8e44cd8 — resumo em `docs/OPERACAO_ATUAL_HCTE.md`.
- **"highclass.you — O que falta no site para ficar excelente"**: https://claude.ai/code/artifact/f44e9e3a-38d9-48e8-a781-b27d7fbd3a52 — integração em `docs/SITE_HIGHCLASS.md`.

Ele sobe, em uma única máquina, toda a infraestrutura e o código-base dos agentes que:

- produzem conteúdo diário por mercado (BR, IN, SA/GCC, GB, RU/KZ, DE, US);
- operam tráfego pago com teto diário e realocação automática por CAC;
- atendem leads e clientes como consultores locais, em WhatsApp, Instagram/Messenger,
  Telegram, e-mail e webchat, 24/7, em menos de 60 segundos;
- cotam, reservam, cobram e fazem o pós-venda com fornecedores licenciados pela DET;
- planejam o campo (3 carros, 2 motoristas, guias) e mandam a agenda por WhatsApp às 18h;
- cuidam de licenças, seguros, Mulkiyas, contratos, presentes e abayas sem equipe de escritório;
- escalam para humano só nas situações definidas em `config/escalation.yaml`;
- prospectam agências de viagens no mundo todo e abrem parcerias B2B;
- cuidam de cobrança, contas a pagar e a receber e fluxo de caixa;
- são auditados por um agente independente que mede SLAs e aponta a melhoria exata;
- reportam à CEO por um dashboard com **chat** (o CEO-agente responde com todos os dados e delega às áreas) e por WhatsApp.

Organização: **8 departamentos, 24 agentes** — CEO (gabinete), Marketing, Estratégia, Prospecção, Atendimento, Operacional, Auditor, Financeiro (`config/departments.yaml`, `docs/ORG.md`). Decisões tipadas (triagem, risco, moderação, scores) são do **Jev / TypeSafe AI** (`brain/core/jev.py`); texto e ferramentas são do Claude.

## Estrutura

```
dubai-ai-agency/
├── docker-compose.yml     # postgres+pgvector, redis, chatwoot, langfuse, minio, caddy, brain
├── Dockerfile             # imagem do serviço "brain" (Python 3.12 + Claude Agent SDK)
├── Makefile               # make up / down / migrate / seed / evals / logs
├── .env.example           # todas as chaves e limites (copie para .env)
├── config/
│   ├── agency.yaml        # identidade HCTE (licença 781806, IATA, HCB1), autonomia, protocolo VIP, políticas
│   ├── humans.yaml        # motoristas, guias/tradutores, plantão de suporte avançado, parceiros externos
│   ├── suppliers_hcte.yaml# prioridade de fornecedores (contratado → Turning Point/Connect World → Elevate...)
│   ├── renewals_hcte.yaml # calendário de licenças, seguros, Mulkiyas, contratos e inventário
│   ├── escalation.yaml    # os gatilhos que chamam um humano (6 do blueprint + MICE/VIP da HCTE)
│   ├── budgets.yaml       # orçamento de mídia e de tokens por agente/mercado
│   └── markets/*.yaml     # um arquivo por mercado: idioma, persona, canais, picos, objeções
├── knowledge/hcte/        # base de conhecimento extraída dos 4 treinamentos (sem credenciais)
├── prompts/               # um .md por agente + contexto compartilhado
├── brain/                 # código Python
│   ├── main.py            # FastAPI: webhooks dos canais, API do dashboard, scheduler
│   ├── core/              # base dos agentes (Claude Agent SDK), fila, agenda, banco, prompts
│   ├── agents/            # 24 agentes em 8 departamentos (consultor x7 idiomas)
│   ├── tools/             # MCP internas: crm, catalog, quotes, payments, handoff, knowledge, marketing, ops, fleet, admin,
│   │                      #   prospects (B2B), billing (A/R, A/P, caixa), resolution (problemas, emissão, programação), audit, company (CEO)
│   ├── channels/          # adaptadores WhatsApp Cloud, Meta DM, Telegram, e-mail, webchat
│   └── dashboard/         # API de KPIs + página do CEO
├── deploy/aws/            # Terraform + cloud-init: VM na AWS em 3 comandos (deploy/aws/README.md)
├── db/migrations/         # esquema SQL
├── evals/                 # casos de teste dos consultores e do roteador de escalonamento
├── scripts/               # bootstrap e dados de demonstração
└── docs/                  # AGENTS, RUNBOOK, ESCALATION, BLUEPRINT, OPERACAO_ATUAL_HCTE, SITE_HIGHCLASS
```

## Subindo em 15 minutos

Na AWS: `deploy/aws/README.md` cria a VM (m6i.2xlarge, eu-west-1, IP fixo, backups, alarmes) com `terraform apply`; depois siga os passos abaixo dentro dela.

Pré-requisitos: Docker + Docker Compose v2, uma chave `ANTHROPIC_API_KEY`, um domínio apontando
para a máquina (Caddy emite TLS) e, para os canais, as credenciais Meta/Telegram.

```bash
bash scripts/init_env.sh       # gera os segredos e pergunta só as suas chaves (ou: cp .env.example .env && nano .env)
make up                       # sobe tudo
make migrate                  # cria o esquema (001 blueprint + 002 frota/admin HCTE)
make ingest-knowledge         # treinamentos da HCTE → base de conhecimento
make sync-renewals            # calendário de renovações → tabela (já alerta a Mulkiya do Yukon, 21/10/2026)
make seed                     # (opcional) leads, reservas e KPIs de demonstração
open https://SEU_DOMINIO/     # dashboard do CEO
```

Webhooks a registrar (todos em `https://SEU_DOMINIO`):

| Canal | URL | Onde registrar |
| --- | --- | --- |
| WhatsApp Cloud API | `/webhooks/whatsapp` | Meta for Developers → app → WhatsApp → Configuration |
| Messenger + Instagram | `/webhooks/meta` | Meta for Developers → app → Webhooks |
| Telegram | `/webhooks/telegram` | `setWebhook` na Bot API (o `make telegram-webhook` faz isso) |
| Webchat | `/webhooks/webchat` | widget em `brain/channels/webchat.py` (snippet no final do arquivo) |
| E-mail | polling IMAP a cada 60 s | `.env` (`IMAP_*`, `SMTP_*`) |

## Como a máquina pensa

1. Toda mensagem vira um evento em Redis Streams (`inbound`).
2. O **Jev** classifica em < 0,5 s: mercado, intenção, urgência, sentimento, emergência, pedido de humano, risco de compliance, injeção de prompt, sinal VIP (Haiku 4.5 só como fallback).
3. Se não houver gatilho humano, o **Consultor** do mercado (Sonnet 5, persona fixa por idioma)
   responde com as ferramentas MCP: CRM, catálogo, cotação em PDF, link de pagamento, conhecimento.
4. Se houver gatilho, abre caso no Chatwoot com resumo e ação sugerida e avisa o CEO no WhatsApp.
5. Cron jobs instanciam os demais departamentos (ver `brain/core/scheduler.py`): Operacional confirma/emite a cada 30 min e resolve
   problemas a cada 15 min; Financeiro fecha às 23:00 e cobra às 09:00; Estratégia segunda 10:00; Prospecção 09:30; Auditor 02:00 e
   SLA a cada hora; CEO-agente briefing 07:00. Qualquer pedido da CEO no chat vira `delegate_task` na hora.
5b. Antes de qualquer ferramenta com efeito (pagamento, reembolso, envio, cancelamento), o **gate de risco do Jev** decide allow/confirm/block.
6. Toda chamada de modelo é rastreada no Langfuse com custo por agente e por mercado; o
   dashboard lê `kpis_daily` e `agent_runs`.

## Segurança e compliance (não pule)

- Nenhum dado de cartão passa pela máquina: pagamentos são links Stripe/Tap/Telr.
- Passaporte só é coletado quando necessário, criptografado (`FIELD_ENCRYPTION_KEY`) e apagado
  30 dias após a viagem (`make purge-pii` roda diariamente pelo scheduler).
- O número da licença DET aparece em todas as primeiras mensagens, PDFs e rodapés (`config/agency.yaml`).
- Todo conteúdo e anúncio passa pelo agente de Compliance antes de publicar.
- `.env` nunca vai para o git. Backups diários criptografados para S3/MinIO (`scripts/backup.sh`).

## Próximos passos após o `make up`

- Preencher `config/agency.yaml` com nome, licença DET, número do CEO e limites.
- Carregar fornecedores e produtos em `catalog_items` (CSV em `scripts/seed_catalog_template.csv`).
- Rodar `make evals` e só então ligar o primeiro canal em produção (Brasil, depois Índia).

Consulte `docs/RUNBOOK.md` para operação diária e `docs/AGENTS.md` para o papel de cada agente.
