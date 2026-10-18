-- 013 — Eventos de transbordo para humano (pedido de humano, proposta, pagamento, reclamação, DSAR): fila, alerta à equipe e SLA.
-- Um evento por (conversa, gatilho) enquanto estiver na fila; nova ocorrência só soma occurrence_count (deduplicação).
-- created_at = detecção (criado_em) · alerted_at = alerta entregue à equipe (alertado_em) · attended_at = humano respondeu/assumiu (atendido_em).
-- Tempo de espera = coalesce(attended_at, agora) - created_at; dentro do SLA = espera <= sla_seconds.
-- Idempotente. Reversão em db/migrations_down/013_handoff_events.sql (fora desta pasta: o `make migrate` roda tudo o que estiver aqui).
CREATE TABLE IF NOT EXISTS handoff_events (
  id                 uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  conversation_id    uuid NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  lead_id            uuid REFERENCES leads(id) ON DELETE SET NULL,
  trigger            text NOT NULL CHECK (trigger IN ('human_request', 'proposal', 'payment', 'complaint', 'dsar')),
  trigger_subtype    text,                              -- dsar: access | erasure | revocation
  detected_by        text NOT NULL,                     -- keyword | model | keyword+model
  language           text,                              -- pt, en, es, ar (idioma da palavra-chave ou da triagem)
  sla_seconds        integer NOT NULL CHECK (sla_seconds > 0),
  status             text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'alerted', 'breached', 'attended', 'closed')),
  created_at         timestamptz NOT NULL DEFAULT now(),
  alerted_at         timestamptz,
  attended_at        timestamptz,
  attended_by        text,                              -- human:<nome> | ceo | painel
  breached_at        timestamptz,                       -- SLA venceu sem humano: escalonado
  escalated_at       timestamptz,                       -- alerta de escalonamento entregue
  closed_at          timestamptz,
  alert_channel      text,                              -- email | whatsapp | email+whatsapp
  alert_attempts     integer NOT NULL DEFAULT 0,
  last_alert_at      timestamptz,
  last_alert_error   text,                              -- sem destinatário, SMTP fora, Graph API recusou…
  occurrence_count   integer NOT NULL DEFAULT 1,
  last_occurrence_at timestamptz NOT NULL DEFAULT now(),
  details            jsonb NOT NULL DEFAULT '{}'::jsonb, -- termos que bateram, intenção e confiança do modelo (nunca o texto do cliente)
  updated_at         timestamptz NOT NULL DEFAULT now()
);
-- deduplicação: no máximo um evento na fila por conversa e gatilho
CREATE UNIQUE INDEX IF NOT EXISTS handoff_events_one_open_idx ON handoff_events (conversation_id, trigger)
  WHERE status IN ('open', 'alerted', 'breached', 'attended');
CREATE INDEX IF NOT EXISTS handoff_events_queue_idx ON handoff_events (status, created_at) WHERE status IN ('open', 'alerted', 'breached');
CREATE INDEX IF NOT EXISTS handoff_events_created_idx ON handoff_events (created_at);

INSERT INTO rules (scope, rule)
SELECT 'service', r FROM (VALUES
  ('Transbordo para humano: pedido de humano, proposta, pagamento, reclamação e pedido sobre dados pessoais (acesso, exclusão, revogação) abrem um evento em handoff_events e a equipe recebe alerta em até 1 minuto, uma vez por conversa e gatilho. SLA por gatilho em config/handoff.yaml; vencido sem humano, o alerta é escalonado. Ao cliente, no máximo um aviso neutro de que a equipe vai assumir.')
) AS v(r)
WHERE NOT EXISTS (SELECT 1 FROM rules WHERE rules.scope = 'service' AND rules.rule = v.r);
