-- Reversão da 013. Rodar manualmente (psql -v ON_ERROR_STOP=1 -f ...); fica fora de db/migrations para o `make migrate` não executá-la.
-- Suspensões abertas viram revogação (falha segura: quem pediu para parar não volta a receber marketing); as retomadas ('lifted')
-- são só histórico e saem. Exporte consent_log antes se ele já tiver dados reais.
BEGIN;
DELETE FROM rules WHERE scope = 'service' AND rule LIKE 'Descadastro fora da lista (config/descadastro.yaml)%';
UPDATE consent_log c SET status = 'revoked', revoked_at = now()
WHERE c.status = 'active' AND EXISTS (SELECT 1 FROM consent_log s WHERE s.status = 'suspended' AND s.lead_id = c.lead_id
                                        AND s.channel = c.channel AND s.purpose = c.purpose);
UPDATE consent_log SET status = 'revoked', revoked_at = now() WHERE status = 'suspended';
DELETE FROM consent_log WHERE status = 'lifted';
DROP INDEX IF EXISTS consent_log_awaiting_idx;
DROP INDEX IF EXISTS consent_log_one_suspended_idx;
ALTER TABLE consent_log DROP CONSTRAINT IF EXISTS consent_log_lifted_check;
ALTER TABLE consent_log DROP CONSTRAINT IF EXISTS consent_log_detection_class_check;
ALTER TABLE consent_log DROP COLUMN IF EXISTS reply_text;
ALTER TABLE consent_log DROP COLUMN IF EXISTS lifted_at;
ALTER TABLE consent_log DROP COLUMN IF EXISTS escalation_id;
ALTER TABLE consent_log DROP COLUMN IF EXISTS awaiting_until;
ALTER TABLE consent_log DROP COLUMN IF EXISTS detection_class;
ALTER TABLE consent_log DROP CONSTRAINT IF EXISTS consent_log_status_check;
ALTER TABLE consent_log ADD CONSTRAINT consent_log_status_check CHECK (status IN ('active', 'revoked'));
COMMIT;
