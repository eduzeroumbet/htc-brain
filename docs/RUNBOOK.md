# Runbook — operação diária da máquina

## Dia 1 (provisionar)

1. VM na AWS pelo Terraform em `deploy/aws/` (m6i.2xlarge 8 vCPU / 32 GB, 300 GB gp3, eu-west-1, IP fixo, snapshots diários, alarmes). O cloud-init já instala Docker, swap, ufw, fail2ban e Tailscale (se a auth key for dada). Ver `deploy/aws/README.md`.
2. DNS: `brain.suaagencia.ae → IP`. Portas 80/443 abertas; tudo o mais fechado.
3. `git clone` → `cp .env.example .env` → gere os segredos (`openssl rand -hex 32`, Fernet para `FIELD_ENCRYPTION_KEY`).
4. `make up` → `make migrate` → `make seed` (opcional, para ver o dashboard vivo) → abra `https://brain.suaagencia.ae/`.
5. Chatwoot: crie a conta admin em `/inbox`, uma inbox "Humanos" (API channel), um agente-bot; copie `CHATWOOT_API_TOKEN` e `CHATWOOT_HUMAN_INBOX_ID` para o `.env`; instale o app do Chatwoot no celular do CEO.
6. Langfuse: crie o projeto em `/langfuse`, copie as chaves para o `.env`. `make restart`.
7. **Jev (TypeSafe AI)**: crie a chave em https://jevtypesafeai.com (ou a oficial em typesafe.ai), preencha `JEV_API_KEY` e pine `JEV_MODEL`. Teste com `make jev-smoke` — sem a chave a máquina funciona em modo degradado (Haiku + regras; gates de risco desligados). Nunca coloque a chave em prompt ou doc.
8. Humanos: preencha em `.env` os WhatsApps dos motoristas, do pessoal de resolução (`RESOLVER_*`) e do plantão; a programação de campo e de resolução sai por `FIELD_WHATSAPP_NUMBER_ID`.
9. `make check` — revisão estática (agentes, departamentos, prompts, ferramentas, segredos). Deve terminar em "OK".

## Dia 2 (canais)

1. **WhatsApp Cloud API**: app Meta → produto WhatsApp → número verificado (o número da agência, não pessoal) → webhook `https://.../webhooks/whatsapp` com `WA_VERIFY_TOKEN` → assine `messages`. Cadastre templates por idioma (boas-vindas, follow-up, voucher, lembrete D-1) — necessários fora da janela de 24h.
2. **Instagram/Messenger**: mesmo app → Messenger + Instagram → webhook `/webhooks/meta` → assine `messages`, `messaging_postbacks`. A conta IG precisa ser profissional e conectada à página.
3. **Telegram**: @BotFather → token → `make telegram-webhook`.
4. **E-mail**: caixa `hello@` com IMAP/SMTP (Google Workspace ou Zoho). Preencha `IMAP_*`/`SMTP_*`.
5. **Webchat**: cole o snippet de `brain/channels/webchat.py` no site, um por idioma (`market`).
6. Teste cada canal com uma mensagem real. Veja o fluxo em `make logs` e no Langfuse.

## Dia 3 (catálogo e conhecimento)

1. Fornecedores: `INSERT INTO suppliers` (nome, tipo, licença DET, validade, termos) com `approved_by_ceo = true` só após o CEO aprovar.
2. Catálogo: preencha `scripts/seed_catalog_template.csv` e importe (`\copy` no `make psql`) ou insira via SQL. Mínimo para lançar: 8 hotéis (3★–5★, 3 áreas), 12 experiências, 2 transfers, visto, seguro.
3. Rode manualmente `POST /api/tasks/market_intel/daily_refresh?market_code=BR` (e para IN, SA, GB) e verifique `knowledge_chunks`.
4. Preencha as respostas às objeções (`answer_key` dos mercados) — o Market Intel gera a primeira versão; revise.

## Dia 4 (evals e go-live)

1. `make evals` — todos os casos passam? Corrija prompts até passar.
2. Ative só o Brasil (`config/markets/BR.yaml → active: true`, os outros `false`). Coloque os leads atuais da agência para conversar.
3. Depois de 3 dias com escalonamento < 6% e QA ≥ 7, ative a Índia com mídia. Semanas 5–6: Arábia Saudita e Reino Unido.

## Rotina da CEO — 10 min/dia
- Dashboard → **Fale com a sua empresa**: pergunte ("como foi ontem?", "problemas abertos?", "caixa?") e peça ("marketing, campanha X"; "estratégia, cenário Y"; "prospecção, foque no Reino Unido"). O CEO-agente responde com os dados e delega.
- Decisões pendentes: aprovar/recusar; marque "virar regra" para a mesma pergunta não voltar.
- Domingo 20:00: relatório de melhorias do Auditor no WhatsApp; aceite/rejeite os achados no painel.

## Rotina do operador (Edu) — 20 min/dia

- 07:05 — leia o briefing do CEO (chega no WhatsApp do CEO; copie-se).
- Dashboard → Saúde da máquina: erros, `budget_hits`, filas, fornecedores sem resposta.
- Langfuse → traces com erro ou custo anômalo.
- `make logs` se algo parecer preso. `make restart` resolve 90% dos casos.
- Sexta: `make backup`, revisar `evals/last_report.json`, aplicar sugestões de prompt aprovadas pelo QA/CEO, rodar `make evals`, `make restart`.

## Incidentes

| Sintoma | Causa provável | Ação |
| --- | --- | --- |
| Leads sem resposta > 2 min | worker travado / orçamento de tokens | `make logs`; veja `budget_exceeded` em `agent_runs`; aumente `per_agent_daily_cap_usd.consultant` ou `make restart` |
| WhatsApp "template required" | janela de 24h fechou | cadastre/aprove template; o consultor envia via `template` no outbound |
| Erro 401 no webhook Meta | `*_APP_SECRET` errado | corrija no `.env`, `make restart` |
| Preço errado numa cotação | item de catálogo desatualizado | corrija `catalog_items`, invalide a cotação (`status='expired'`), peça ao consultor recotar |
| Escalonamentos > 8% | gatilho amplo demais (palavra-chave) | ajuste `config/escalation.yaml`, `make restart`, observe 24h |
| Custo de tokens > USD 60/dia | conversas longas / loops | veja Langfuse; reduza `max_turns` do consultor; ative cache de prompt |
| Banco cheio | mensagens/logs | `VACUUM`; arquive `messages` > 180 dias |
| Triagem lenta (> 2 s) ou `engine=haiku` em todas as mensagens | Jev indisponível / 401 / 402 (crédito) | `make jev-smoke`; cheque `JEV_API_KEY`, crédito e `JEV_TIMEOUT_S`; a máquina continua no fallback |
| Ferramenta "bloqueada pelo gate de risco" em ação legítima | Jev conservador para aquele caso | veja `jev_tool_gate` nos logs; ajuste a instrução em `jev.tool_risk` ou crie regra via decisão da CEO; nunca remova a ferramenta de `RISKY_TOOLS` para pagamentos/reembolsos |
| Problema sem dono > prazo | `resolve_issues` falhou ou pessoal de resolução não respondeu | `/api/issues`; `POST /api/tasks/booking_payments/resolve_issues`; confira `RESOLVER_*` no `.env` |
| A/R vencido sem lembrete | `receivables_alerts` sem rodar ou lead sem canal | `POST /api/tasks/finance/receivables_alerts`; veja `v_receivables_open` |

## Segurança

- `.env` só na máquina; backup do `.env` no gerenciador de senhas do CEO.
- Acesso SSH só via Tailscale; `ufw` bloqueando tudo exceto 80/443.
- `make backup` diário via cron do host (`0 4 * * * /opt/dubai-ai-agency/scripts/backup.sh`).
- Rotacione `WA_ACCESS_TOKEN` (token de sistema, nunca de usuário) e `ANTHROPIC_API_KEY` a cada 90 dias.
- PII: `make purge-pii` roda às 03:30; confira mensalmente que `bookings.pax` de viagens antigas está vazio.

## Mercados novos (Rússia, Índia, Golfo, DACH, EUA) — como a máquina aprende a anunciar

1. `make ingest-knowledge` carrega `knowledge/markets/<XX>.md` (base com itens **[verificar]**).
2. No chat do dashboard: "Analista de mercado: pesquise a Rússia" → `market_analyst.research_market` confirma com fontes, grava o playbook e propõe até 3 experimentos.
3. Experimentos dentro de `config/budgets.yaml → media.experiments` (25% do budget do mercado, 2 simultâneos, kill automático) rodam sozinhos; canal novo com intermediário (ex.: Yandex Direct com ERID) e mercados de onda 2 aparecem como decisão para a CEO.
4. Terça 10:00 o Analista fecha/propõe/realoca; vencedores vão para o Paid Media; o Gestor Social usa o playbook para o calendário de cada rede (Telegram/VK na Rússia, Reels/WhatsApp na Índia, Snapchat/TikTok no Golfo).
5. Tokens das redes em `.env` (`IG_*`, `FB_*`, `TG_*`, `VK_*`); sem token a peça sai como "pacote manual" no painel Conteúdo e em alerta.
