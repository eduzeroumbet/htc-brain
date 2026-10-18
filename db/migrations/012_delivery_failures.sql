-- 012 — Falhas permanentes de entrega do WhatsApp (erro 130497 da Meta: conta restrita para o país do contato).
-- Categoria própria, sem dado pessoal: nada de telefone, texto, nome ou payload bruto; só lead_id, código e mercado.
-- category: wa_country_restricted (erro real da Meta) | wa_br_paused_by_flag (guarda local WA_BR_DELIVERY_ENABLED=false)
-- Reverter (make migrate roda todo *.sql desta pasta, por isso o down fica aqui comentado):
--   DROP TABLE IF EXISTS delivery_failure_events;
CREATE TABLE IF NOT EXISTS delivery_failure_events (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  occurred_at     timestamptz NOT NULL DEFAULT now(),   -- UTC; o dashboard exibe em UTC+4
  channel         text NOT NULL DEFAULT 'whatsapp',
  error_code      integer,                              -- 130497; NULL no bloqueio local
  category        text NOT NULL,
  market_code     text NOT NULL,                        -- BR, AE, IN… | ambiguous | unknown (sem FK de propósito)
  country_prefix  text,                                 -- +55
  source          text NOT NULL,                        -- sync | webhook | guard
  outbound_ref    text NOT NULL,                        -- wamid ou hash do envio: chave de idempotência
  lead_id         uuid REFERENCES leads(id) ON DELETE SET NULL,
  wamid           text,
  fbtrace_id      text,
  retryable       boolean NOT NULL DEFAULT false CHECK (retryable = false),
  delivery_status text NOT NULL DEFAULT 'failed_permanent',
  alt_route_status  text,                               -- dispatched | skipped_* | unreachable | not_applicable_market
  alt_route_channel text,
  UNIQUE (outbound_ref, category)
);
CREATE INDEX IF NOT EXISTS delivery_failure_events_day_idx ON delivery_failure_events (occurred_at, category, market_code);
