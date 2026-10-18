-- 012 — Gate de segurança da Fase 2: idempotência do webhook de pagamento e lease com fencing no balcão de propostas.

-- Webhook de pagamento: cada evento do provedor é aplicado uma única vez (inserção na mesma transação do efeito).
CREATE TABLE IF NOT EXISTS payment_webhook_events (
  provider     text NOT NULL,
  event_id     text NOT NULL,
  event_type   text,
  received_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (provider, event_id)
);

-- Balcão de propostas: lease (locked_by/locked_until) + fencing token monotônico.
ALTER TABLE proposal_requests ADD COLUMN IF NOT EXISTS locked_by     text;
ALTER TABLE proposal_requests ADD COLUMN IF NOT EXISTS locked_until  timestamptz;
ALTER TABLE proposal_requests ADD COLUMN IF NOT EXISTS fencing_token bigint NOT NULL DEFAULT 0;
ALTER TABLE proposal_requests ADD COLUMN IF NOT EXISTS attempts      int NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS proposal_requests_lease_idx ON proposal_requests (due_at, locked_until)
  WHERE status IN ('requested','interim_sent');
