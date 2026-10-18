-- Reversão da 013. Rodar manualmente (psql -v ON_ERROR_STOP=1 -f ...); fica fora de db/migrations para o `make migrate` não executá-la.
-- Apaga o histórico de transbordos: exporte handoff_events antes se ele já tiver dados reais.
BEGIN;
DELETE FROM rules WHERE scope = 'service' AND rule LIKE 'Transbordo para humano: pedido de humano, proposta%';
DROP TABLE IF EXISTS handoff_events;
COMMIT;
