# knowledge/ — base de conhecimento versionada

Arquivos Markdown com front matter (`topic`, `market_code`, `language`, `source`, `valid_days`) que o
script `scripts/ingest_knowledge.py` grava em `knowledge_chunks` (com embedding quando houver
`VOYAGE_API_KEY`). O Market Intel atualiza os topics voláteis (`safety_2026`, `airlines_status`,
`incentives`) sozinho; os arquivos aqui são o conhecimento estável da casa.

- `hcte/attractions_uae.md` — 49 atrações e experiências com duração, público e regras (treinamento de maio/2026).
- `hcte/hotels_guide.md` — perguntas de qualificação, noites mínimas, hotéis por perfil, tipos de quarto, termos.
- `hcte/fleet_and_vehicles.md` — frota própria, capacidade de bagagem, regra de escolha do carro.
- `hcte/workflow_and_policies.md` — quem somos, 9 estados da viagem, regras de ouro, pagamento, KPIs.

**Regra absoluta:** nenhuma credencial, senha, login ou número de conta entra aqui. Os manuais originais
contêm esse tipo de dado e por isso NÃO devem ser ingeridos brutos. Segredos ficam no cofre e no `.env`.

Ingestão: `docker compose exec brain python -m scripts.ingest_knowledge` (idempotente por topic + fonte).
