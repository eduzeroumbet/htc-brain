-- 013 — Descadastro fora dos seis termos: suspensão de marketing (caso ambíguo e pedido claro fora da lista) no próprio consent_log.
-- Idempotente. Reversão em db/migrations_down/013_descadastro_fora_da_lista.sql. Decisão: docs/decisoes/descadastro-fora-da-lista.md.
--
-- status:  active | revoked (012) + suspended (marketing bloqueado à espera de "sim"/"não" ou de revisão humana)
--          + lifted (suspensão encerrada com "não" ou por decisão humana; só histórico, a guarda ignora).
-- A guarda (consent.pode_enviar_marketing) continua: estado vigente = linha mais recente que não é 'lifted'; só 'active' libera.

ALTER TABLE consent_log DROP CONSTRAINT IF EXISTS consent_log_status_check;
ALTER TABLE consent_log ADD CONSTRAINT consent_log_status_check CHECK (status IN ('active', 'revoked', 'suspended', 'lifted'));

ALTER TABLE consent_log ADD COLUMN IF NOT EXISTS detection_class text;    -- lista | ambiguo | claro: classe da mensagem que suspendeu/revogou
ALTER TABLE consent_log ADD COLUMN IF NOT EXISTS awaiting_until timestamptz;  -- caso ambíguo: prazo da resposta à pergunta (7 dias)
ALTER TABLE consent_log ADD COLUMN IF NOT EXISTS escalation_id uuid REFERENCES escalations(id);  -- tarefa humana aberta para a suspensão
ALTER TABLE consent_log ADD COLUMN IF NOT EXISTS lifted_at timestamptz;
ALTER TABLE consent_log ADD COLUMN IF NOT EXISTS reply_text text;         -- resposta do cliente à pergunta ("sim", "não")
ALTER TABLE consent_log DROP CONSTRAINT IF EXISTS consent_log_detection_class_check;
ALTER TABLE consent_log ADD CONSTRAINT consent_log_detection_class_check
  CHECK (detection_class IS NULL OR detection_class IN ('lista', 'ambiguo', 'claro'));
ALTER TABLE consent_log DROP CONSTRAINT IF EXISTS consent_log_lifted_check;
ALTER TABLE consent_log ADD CONSTRAINT consent_log_lifted_check CHECK ((status = 'lifted') = (lifted_at IS NOT NULL));

-- no máximo uma suspensão aberta por lead/canal/finalidade (pedido repetido não abre outra nem repete a pergunta)
CREATE UNIQUE INDEX IF NOT EXISTS consent_log_one_suspended_idx ON consent_log(lead_id, channel, purpose) WHERE status = 'suspended';
-- varredura do silêncio (consent.vencer_confirmacoes)
CREATE INDEX IF NOT EXISTS consent_log_awaiting_idx ON consent_log(awaiting_until) WHERE status = 'suspended' AND escalation_id IS NULL;

INSERT INTO rules (scope, rule)
SELECT 'service', r FROM (VALUES
  ('Descadastro fora da lista (config/descadastro.yaml): frase ambígua (ex.: "STOP please?", "chega", "хватит") suspende o marketing na hora e recebe UMA pergunta de confirmação no idioma do cliente; "sim" revoga, "não" retoma, silêncio mantém suspenso e abre tarefa humana em 7 dias. Pedido claro fora da lista (ex.: "parar de mandar mensagem") suspende o marketing, avisa o cliente e abre tarefa humana (consent_review), sem revogar sozinho. Cortesia ("please", "por favor", "obrigado") não anula o descadastro.')
) AS v(r)
WHERE NOT EXISTS (SELECT 1 FROM rules WHERE rules.scope = 'service' AND rules.rule = v.r);
