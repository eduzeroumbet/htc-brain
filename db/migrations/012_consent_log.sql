-- 012 — Consentimento auditável (consent_log), descadastro por palavra-chave e DSAR de exclusão aberto pelo próprio cliente.
-- Idempotente. Reversão em db/migrations_down/012_consent_log.sql (fora desta pasta: o `make migrate` roda tudo o que estiver aqui).

-- ───────────────────────── consent_log ─────────────────────────
-- Uma linha por consentimento dado. Revogar atualiza a mesma linha (status, revoked_at); novo opt-in depois da revogação = linha nova.
-- O estado vigente de (lead, canal, finalidade) é a linha mais recente.
CREATE TABLE IF NOT EXISTS consent_log (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  lead_id         uuid NOT NULL REFERENCES leads(id),
  channel         text NOT NULL,                    -- whatsapp, instagram, messenger, telegram, email, webchat
  recorded_at     timestamptz NOT NULL DEFAULT now(),  -- data e hora (UTC) do consentimento
  consent_text    text NOT NULL,                    -- texto exato apresentado/aceito (ou a mensagem de descadastro)
  consent_version text NOT NULL,                    -- versão do texto
  language        text,                             -- pt, en, ar, hi...
  source          text NOT NULL,                    -- record_consent, whatsapp_keyword, backfill_leads...
  purpose         text NOT NULL CHECK (purpose IN ('transactional', 'marketing')),
  status          text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked')),
  revoked_at      timestamptz,
  CHECK ((status = 'revoked') = (revoked_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS consent_log_lead_idx ON consent_log(lead_id);
CREATE INDEX IF NOT EXISTS consent_log_channel_idx ON consent_log(channel);
CREATE INDEX IF NOT EXISTS consent_log_purpose_idx ON consent_log(purpose);
CREATE INDEX IF NOT EXISTS consent_log_current_idx ON consent_log(lead_id, channel, purpose, recorded_at DESC);
-- no máximo um consentimento ativo por lead/canal/finalidade
CREATE UNIQUE INDEX IF NOT EXISTS consent_log_one_active_idx ON consent_log(lead_id, channel, purpose) WHERE status = 'active';

-- quem já tinha consent_marketing = true antes do log continua podendo receber marketing (sem isso a guarda bloquearia todos)
INSERT INTO consent_log (lead_id, channel, recorded_at, consent_text, consent_version, language, source, purpose)
SELECT l.id, l.channel, coalesce(l.consent_at, l.created_at), 'consentimento registrado em leads.consent_marketing antes do consent_log',
       'legacy', l.language, 'backfill_leads', 'marketing'
FROM leads l
WHERE l.consent_marketing
  AND NOT EXISTS (SELECT 1 FROM consent_log c WHERE c.lead_id = l.id AND c.purpose = 'marketing');

-- ───────────────────────── DSAR (data_requests, criada na 005) ─────────────────────────
-- Pedido de exclusão aberto pela própria mensagem do cliente: guarda o canal e o texto original; um só pedido aberto por lead e tipo.
ALTER TABLE data_requests ADD COLUMN IF NOT EXISTS channel text;
ALTER TABLE data_requests ADD COLUMN IF NOT EXISTS source_text text;
CREATE INDEX IF NOT EXISTS data_requests_lead_idx ON data_requests(lead_id);
CREATE INDEX IF NOT EXISTS data_requests_status_due_idx ON data_requests(status, due_at);
CREATE UNIQUE INDEX IF NOT EXISTS data_requests_one_open_idx ON data_requests(lead_id, kind)
  WHERE status NOT IN ('completed', 'refused');

-- rules não tem chave única: NOT EXISTS para não duplicar quando o `make migrate` roda de novo
INSERT INTO rules (scope, rule)
SELECT 'service', r FROM (VALUES
  ('Descadastro: PARAR, STOP, SAIR, UNSUBSCRIBE, ألغِ ou रोकें enviados como mensagem revogam o consentimento de marketing daquele canal (consent_log) antes de qualquer agente responder; o cliente recebe a confirmação no idioma dele. Nenhum follow-up, campanha ou template de marketing sai para quem revogou (guarda em channels.dispatch). Mensagens de reserva, pagamento e viagem continuam.'),
  ('Pedido de exclusão de dados recebido por mensagem (pt, en, ar, hi) abre um DSAR em data_requests com prazo de 15 dias corridos; a execução (fulfil_data_request) continua com o Jurídico.')
) AS v(r)
WHERE NOT EXISTS (SELECT 1 FROM rules WHERE rules.scope = 'service' AND rules.rule = v.r);
