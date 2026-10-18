-- Reversão da 012. Rodar manualmente (psql -v ON_ERROR_STOP=1 -f ...); fica fora de db/migrations para o `make migrate` não executá-la.
-- Apaga o histórico de consentimentos: exporte consent_log antes se ele já tiver dados reais.
BEGIN;
DELETE FROM rules WHERE scope = 'service' AND (rule LIKE 'Descadastro: PARAR, STOP, SAIR%' OR rule LIKE 'Pedido de exclusão de dados recebido por mensagem%');
DROP INDEX IF EXISTS data_requests_one_open_idx;
DROP INDEX IF EXISTS data_requests_status_due_idx;
DROP INDEX IF EXISTS data_requests_lead_idx;
ALTER TABLE data_requests DROP COLUMN IF EXISTS source_text;
ALTER TABLE data_requests DROP COLUMN IF EXISTS channel;
DROP TABLE IF EXISTS consent_log;
COMMIT;
