-- 011 — Balcão de propostas: a Huda promete proposta em até 30 min; a máquina cumpre (ou escala antes de estourar).
CREATE TABLE IF NOT EXISTS proposal_requests (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  lead_id         uuid NOT NULL REFERENCES leads(id),
  conversation_id uuid REFERENCES conversations(id),
  summary         text NOT NULL,                       -- o que o cliente quer (datas, pax, hotel/voo/atrações, orçamento)
  requested_at    timestamptz NOT NULL DEFAULT now(),
  due_at          timestamptz NOT NULL,                -- requested_at + 30 min
  status          text NOT NULL DEFAULT 'requested',   -- requested, interim_sent, sent, escalated, late
  quote_id        uuid REFERENCES quotes(id),
  sent_at         timestamptz,
  escalated_at    timestamptz,
  notes           text
);
CREATE INDEX IF NOT EXISTS proposal_requests_open_idx ON proposal_requests (status, due_at) WHERE status IN ('requested','interim_sent');

INSERT INTO rules (scope, rule) VALUES
  ('service', 'Promessa de proposta: quando o cliente confirma interesse e passa os dados (datas ou mês, quem viaja, hotel/voo/atrações desejados), a Huda registra promise_proposal e diz que a proposta chega em até 30 minutos. O balcão (consultant.proposal_desk, a cada 5 min) monta e envia; se aos 20 min não houver proposta, escala para humano E avisa o cliente com previsão honesta. Nenhuma promessa de prazo sem registro.')
ON CONFLICT DO NOTHING;
