-- 013 — Balcão de propostas: uma única proposta (cotação) e um único PDF por solicitação, mesmo com dois workers.
-- O lease (locked_by, locked_until, fencing_token, attempts) já vem da 012_security_gate.sql. Aqui fica a última barreira
-- no banco para o worker "zumbi" (lease vencido que ainda roda): a chave de idempotência é o proposal_request_id.
-- quotes.proposal_request_id — UNIQUE: build_quote com o mesmo pedido devolve a cotação que já existe.
-- quote_pdfs                 — uma linha por cotação: quem insere gera o PDF; os demais reaproveitam a URL.
--                              Reivindicação parada há mais de 10 min (worker morreu no meio) pode ser assumida.
-- Reverter (make migrate roda todo *.sql desta pasta, por isso o down fica aqui comentado):
--   DROP TABLE IF EXISTS quote_pdfs;
--   DROP INDEX IF EXISTS quotes_proposal_request_uq;
--   ALTER TABLE quotes DROP COLUMN IF EXISTS proposal_request_id;
ALTER TABLE quotes ADD COLUMN IF NOT EXISTS proposal_request_id uuid REFERENCES proposal_requests(id);
CREATE UNIQUE INDEX IF NOT EXISTS quotes_proposal_request_uq ON quotes (proposal_request_id) WHERE proposal_request_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS quote_pdfs (
  quote_id     uuid PRIMARY KEY REFERENCES quotes(id) ON DELETE CASCADE,
  claimed_by   text NOT NULL,                        -- worker que está gerando
  claimed_at   timestamptz NOT NULL DEFAULT now(),
  url          text,                                 -- NULL = em geração
  rendered_at  timestamptz
);
