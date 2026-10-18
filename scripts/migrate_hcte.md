# Migração dos sistemas atuais da HCTE para a máquina

Ordem: exportar → importar → validar em sombra → desligar. Nunca desligar antes de 2 semanas de sombra.

| Origem | O que exportar | Para onde | Como |
| --- | --- | --- | --- |
| HCTE System (Cloudways) | Clientes, propostas com status, price list | `leads`, `quotes`, `catalog_items` | Exportar CSV pelo painel ou dump do banco; mapear status → `leads.stage` (Requested proposal→new, For quotation→qualifying, Sent proposal→quoted, Approved to be paid→negotiating, Under invoice/To be booked→won, Booking confirmation→confirmed, Customer in house→in_trip, Client feedback/Completed→completed) |
| Zoho | Contatos e números de referência | `leads` (`notes` guarda a referência antiga) | Exportar contatos CSV |
| Excel — HCTE Price List | Tarifas líquidas por fornecedor, markup | `suppliers`, `catalog_items` (`net_price_usd`, `markup_pct`) | Preencher `scripts/seed_catalog_template.csv` e importar com `\copy` |
| Excel — comparação de fornecedores (treinamento) | Fontes por item | `catalog_items.supplier_id` + `config/suppliers_hcte.yaml` | Manual, uma vez |
| Excel — Updated Inventory 2026 | Presentes, abayas, uniformes, ativos | `inventory` | CSV → `INSERT` |
| Excel — Employee Database | Só os motoristas (salário base, vencimentos de visto/labour/ILOE) | `drivers` | `UPDATE drivers SET base_salary_aed=..., visa_expiry=...` |
| Manual Admin — veículos | Placas, Mulkiya, odômetro atual, última revisão | `vehicles` (já semeado) | `UPDATE vehicles SET odometer_km=..., last_service_km=...` |
| OneDrive — vouchers e confirmações de viagens futuras | PDFs | MinIO `docs/` + `bookings.vouchers` | Upload em lote; manter OneDrive como arquivo histórico |
| WhatsApp dos cargos (16 iPhones) | Grupos com fornecedores e clientes em viagem | Número de campo e número de clientes da Cloud API | Avisar fornecedores do novo número; encerrar grupos antigos ao fim de cada viagem |
| Trello | Tarefas em aberto | Nada — virar `decisions`/`renewals` se ainda relevantes | Revisar uma vez com a equipe |
| Logins 2026.xlsx | — | Cofre de segredos (1Password/Bitwarden) | Rotacionar TODAS as senhas antes; apagar a planilha |

Depois da sombra: cancelar Cloudways, Zoho e Trello; reduzir Microsoft 365 a 2–3 caixas de serviço; manter
domínios na Locaweb e migrar o site.
