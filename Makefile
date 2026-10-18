.PHONY: up down restart logs migrate seed evals shell psql telegram-webhook purge-pii backup status ingest-knowledge sync-renewals check jev-smoke

COMPOSE ?= docker compose

up:            ## sobe toda a máquina
	$(COMPOSE) up -d --build
	@echo "→ dashboard: https://$$(grep ^DOMAIN .env | cut -d= -f2)/   inbox: /inbox   langfuse: /langfuse"

down:          ## derruba (mantém volumes)
	$(COMPOSE) down

restart:       ## recria só o cérebro (relê o .env; "docker compose restart" não relê)
	$(COMPOSE) up -d --force-recreate brain

logs:          ## logs do cérebro
	$(COMPOSE) logs -f --tail=200 brain

status:        ## estado dos serviços
	$(COMPOSE) ps

migrate:       ## aplica as migrações SQL (idempotente)
	$(COMPOSE) exec -T postgres sh -c 'for f in /migrations/*.sql; do echo "== $$f"; psql -v ON_ERROR_STOP=1 -U $$POSTGRES_USER -d $$POSTGRES_DB -f $$f; done'
	$(COMPOSE) exec -T postgres psql -U $$(grep ^POSTGRES_USER .env | cut -d= -f2) -d postgres -c "CREATE DATABASE chatwoot" 2>/dev/null || true
	$(COMPOSE) exec -T postgres psql -U $$(grep ^POSTGRES_USER .env | cut -d= -f2) -d postgres -c "CREATE DATABASE langfuse" 2>/dev/null || true

seed:          ## dados de demonstração (leads, reservas, KPIs) para ver o dashboard vivo
	$(COMPOSE) exec brain python -m scripts.seed_demo

evals:         ## roda os casos de teste dos consultores e do roteador
	$(COMPOSE) exec brain python -m evals.run_evals

check:         ## revisão estática: agentes x departamentos x prompts x ferramentas x segredos (sem banco)
	$(COMPOSE) exec brain python -m scripts.check

jev-smoke:     ## testa a chave do Jev com uma triagem real (precisa de JEV_API_KEY no ambiente ou .env)
	$(COMPOSE) exec brain python -m scripts.jev_smoke

ingest-knowledge: ## grava knowledge/**/*.md em knowledge_chunks (treinamentos da HCTE)
	$(COMPOSE) exec brain python -m scripts.ingest_knowledge

sync-renewals: ## carrega config/renewals_hcte.yaml na tabela renewals e lista o que vence em 120 dias
	$(COMPOSE) exec brain python -m scripts.sync_renewals

shell:         ## shell python dentro do cérebro
	$(COMPOSE) exec brain python

psql:          ## psql no banco
	$(COMPOSE) exec postgres psql -U $$(grep ^POSTGRES_USER .env | cut -d= -f2) -d $$(grep ^POSTGRES_DB .env | cut -d= -f2)

telegram-webhook: ## registra o webhook do Telegram
	curl -s "https://api.telegram.org/bot$$(grep ^TELEGRAM_BOT_TOKEN .env | cut -d= -f2)/setWebhook?url=https://$$(grep ^DOMAIN .env | cut -d= -f2)/webhooks/telegram&secret_token=$$(grep ^TELEGRAM_WEBHOOK_SECRET .env | cut -d= -f2)"

purge-pii:     ## apaga PII vencida (também roda diariamente pelo scheduler)
	$(COMPOSE) exec brain python -c "import asyncio; from brain.core.db import purge_expired_pii; asyncio.run(purge_expired_pii())"

backup:        ## dump criptografado do banco para ./backups
	./scripts/backup.sh

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
