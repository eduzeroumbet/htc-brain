-- 003 — Departamentos: Prospecção (B2B), Operacional (problemas/resolução, emissão), Financeiro (A/R, A/P, caixa),
--       Auditor (achados), CEO (chat do dashboard), Estratégia (propostas de produto). Jev: colunas de score.

-- ───────────── Atendimento / Jev ─────────────
ALTER TABLE leads ADD COLUMN IF NOT EXISTS jev_fit numeric(4,3);           -- 0–1 (lead_score.fit)
ALTER TABLE leads ADD COLUMN IF NOT EXISTS jev_buying_now numeric(4,3);    -- 0–1
ALTER TABLE leads ADD COLUMN IF NOT EXISTS budget_tier text;               -- low|mid|high|ultra|unknown
ALTER TABLE leads ADD COLUMN IF NOT EXISTS vip boolean NOT NULL DEFAULT false;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS jev jsonb;                   -- triagem completa da mensagem (auditável)
ALTER TABLE quotes ADD COLUMN IF NOT EXISTS pdf_rendered_at timestamptz;   -- SLA cotação→PDF (auditor)
ALTER TABLE quotes ADD COLUMN IF NOT EXISTS accepted_at timestamptz;
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS confirmed_at timestamptz;
-- agent_runs nasceu com started_at; as consultas dos departamentos usam created_at → coluna espelho (gerada)
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS created_at timestamptz GENERATED ALWAYS AS (started_at) STORED;
CREATE INDEX IF NOT EXISTS agent_runs_created_idx ON agent_runs (created_at DESC);
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS department text;
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS delegated_by text;         -- 'ceo' quando veio do gabinete

-- ───────────── Prospecção B2B ─────────────
CREATE TABLE IF NOT EXISTS partner_agencies (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  name            text NOT NULL,
  country         text NOT NULL,                    -- ISO-2
  market_code     text REFERENCES markets(code),    -- mercado que atende (BR, IN, ...)
  city            text,
  website         text,
  type            text,                             -- retail_agency|tour_operator|luxury_advisor|mice_agency|ota|other
  sells_middle_east boolean,
  contact_name    text,
  contact_role    text,
  contact_email   text,
  contact_phone   text,
  linkedin        text,
  source          text,                             -- onde foi encontrada (feira, diretório, busca)
  jev_fit         numeric(4,3),
  stage           text NOT NULL DEFAULT 'identified', -- identified, contacted, replied, call_scheduled, proposal_sent, partner, declined, dormant
  commission_pct  numeric(5,2),
  agreement_url   text,
  notes           text,
  next_action_at  timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (name, country)
);
CREATE INDEX IF NOT EXISTS partner_agencies_stage_idx ON partner_agencies (stage, next_action_at);

CREATE TABLE IF NOT EXISTS outreach (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  partner_id      uuid NOT NULL REFERENCES partner_agencies(id) ON DELETE CASCADE,
  direction       text NOT NULL,                    -- out|in
  channel         text NOT NULL,                    -- email|linkedin|whatsapp|phone|form
  subject         text,
  body            text,
  sequence_step   smallint,                         -- 1 primeiro contato, 2 D+4, 3 D+10, 4 D+30
  jev_reply_class text,                             -- interested|later|not_interested|question|bounce
  sent_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS outreach_partner_idx ON outreach (partner_id, sent_at DESC);

-- ───────────── Operacional: problemas e resolução ─────────────
CREATE TABLE IF NOT EXISTS issues (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  booking_id      uuid REFERENCES bookings(id),
  lead_id         uuid REFERENCES leads(id),
  kind            text NOT NULL,                    -- ticket|attraction|hotel|transfer|flight|payment|document|other
  severity        text NOT NULL DEFAULT 'medium',   -- low|medium|high|critical
  title           text NOT NULL,
  detail          text,
  status          text NOT NULL DEFAULT 'open',     -- open, in_progress, waiting_supplier, assigned_human, resolved, cancelled
  owner_agent     text,                             -- booking_payments|concierge|fleet_dispatcher
  assigned_human  text,                             -- id em config/humans.yaml quando precisa de alguém presencial
  resolution      text,
  client_informed boolean NOT NULL DEFAULT false,
  due_at          timestamptz,
  opened_at       timestamptz NOT NULL DEFAULT now(),
  resolved_at     timestamptz
);
CREATE INDEX IF NOT EXISTS issues_status_idx ON issues (status, severity, due_at);

-- Emissões (ingressos, vouchers, e — quando o IATA estiver ativo — bilhetes aéreos)
CREATE TABLE IF NOT EXISTS issuances (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  booking_id      uuid NOT NULL REFERENCES bookings(id),
  catalog_item_id uuid REFERENCES catalog_items(id),
  kind            text NOT NULL,                    -- ticket|voucher|air|insurance|esim|visa
  provider        text,                             -- emaar_portal|turning_point|connect_world|elevate|gds|direct
  provider_ref    text,
  status          text NOT NULL DEFAULT 'requested', -- requested, issued, failed, reissued, cancelled
  document_url    text,
  pax_count       smallint,
  service_date    date,
  issued_at       timestamptz,
  error           text,
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS issuances_booking_idx ON issuances (booking_id, status);

-- field_assignments passa a aceitar kind = issue_resolution (funcionário de resolução) — sem constraint de enum, só documentação.
ALTER TABLE field_assignments ADD COLUMN IF NOT EXISTS staff_id text;      -- id em humans.yaml → advanced_support/resolution_staff
ALTER TABLE field_assignments ADD COLUMN IF NOT EXISTS issue_id uuid REFERENCES issues(id);

-- ───────────── Financeiro ─────────────
CREATE TABLE IF NOT EXISTS receivables (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  booking_id      uuid REFERENCES bookings(id),
  partner_id      uuid REFERENCES partner_agencies(id),   -- faturas B2B
  lead_id         uuid REFERENCES leads(id),
  invoice_no      text UNIQUE,                      -- HC-2026-000123
  description     text,
  amount_usd      numeric(10,2) NOT NULL,
  currency        text NOT NULL DEFAULT 'USD',
  amount_local    numeric(12,2),
  due_at          date NOT NULL,
  status          text NOT NULL DEFAULT 'open',     -- open, partially_paid, paid, overdue, written_off, cancelled
  paid_usd        numeric(10,2) NOT NULL DEFAULT 0,
  payment_link    text,
  invoice_url     text,
  reminders_sent  smallint NOT NULL DEFAULT 0,
  last_reminder_at timestamptz,
  jev_risk        numeric(4,3),                     -- risco de inadimplência 0–1
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS receivables_status_idx ON receivables (status, due_at);

CREATE TABLE IF NOT EXISTS payables (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  supplier_id     uuid REFERENCES suppliers(id),
  booking_id      uuid REFERENCES bookings(id),
  category        text NOT NULL,                    -- supplier|payroll|rent|licence|insurance|media|tokens|fuel|other
  description     text,
  amount_usd      numeric(10,2) NOT NULL,
  currency        text NOT NULL DEFAULT 'AED',
  amount_local    numeric(12,2),
  due_at          date NOT NULL,
  status          text NOT NULL DEFAULT 'open',     -- open, scheduled, paid, overdue, disputed, cancelled
  paid_at         timestamptz,
  reference       text,
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS payables_status_idx ON payables (status, due_at);

CREATE TABLE IF NOT EXISTS cashflow_daily (
  day             date PRIMARY KEY,
  opening_usd     numeric(12,2),
  inflow_usd      numeric(12,2) NOT NULL DEFAULT 0,
  outflow_usd     numeric(12,2) NOT NULL DEFAULT 0,
  closing_usd     numeric(12,2),
  forecast_30d_usd numeric(12,2),
  notes           text
);

-- ───────────── Auditor ─────────────
CREATE TABLE IF NOT EXISTS audit_findings (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  day             date NOT NULL DEFAULT current_date,
  area            text NOT NULL,                    -- customer_care|operations|marketing|finance|prospecting|strategy|ceo_office
  flow            text,                             -- ex.: 'briefing→cotação→pdf→pagamento'
  severity        text NOT NULL DEFAULT 'medium',   -- low|medium|high|critical
  title           text NOT NULL,
  evidence        text,                             -- ids e trechos literais
  recommendation  text,                             -- mudança exata proposta (prompt, regra, processo)
  status          text NOT NULL DEFAULT 'open',     -- open, accepted, rejected, implemented
  decision_id     uuid REFERENCES decisions(id),
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS audit_findings_day_idx ON audit_findings (day DESC, severity);

CREATE TABLE IF NOT EXISTS qa_scores (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  target_kind     text NOT NULL,                    -- conversation|content|booking
  target_id       text NOT NULL,
  score           numeric(4,2) NOT NULL,            -- 0–10
  issues          text,
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS qa_scores_created_idx ON qa_scores (created_at DESC);

CREATE TABLE IF NOT EXISTS sla_checks (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  checked_at      timestamptz NOT NULL DEFAULT now(),
  metric          text NOT NULL,                    -- first_response_s|quote_pdf_min|escalation_ack_min|supplier_confirm_min|issue_resolution_h
  window_hours    smallint NOT NULL,
  value           numeric(10,2),
  target          numeric(10,2),
  breached        boolean NOT NULL,
  detail          jsonb
);

-- ───────────── CEO: chat do dashboard ─────────────
CREATE TABLE IF NOT EXISTS ceo_chat (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  role            text NOT NULL,                    -- user|assistant
  body            text NOT NULL,
  session_id      text,                             -- sessão do SDK para continuidade
  cost_usd        numeric(8,4),
  delegations     jsonb,                            -- [{agent, task, market_code}] disparadas por esta resposta
  created_at      timestamptz NOT NULL DEFAULT now()
);

-- ───────────── Estratégia: propostas de produto ─────────────
CREATE TABLE IF NOT EXISTS product_proposals (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  name            text NOT NULL,
  market_codes    text[] NOT NULL,
  segment         text,
  nights          smallint,
  price_from_usd  numeric(10,2),
  est_margin_pct  numeric(5,2),
  rationale       text,
  items           jsonb,                            -- [{catalog_item_id|sku, qty}]
  jev_attractiveness numeric(4,3),
  status          text NOT NULL DEFAULT 'proposed', -- proposed, approved, in_catalog, rejected
  decision_id     uuid REFERENCES decisions(id),
  created_at      timestamptz NOT NULL DEFAULT now()
);

-- Views usadas pelo dashboard e pelo CEO-agente
CREATE OR REPLACE VIEW v_departments_today AS
SELECT department, count(*) AS runs, sum(cost_usd) AS cost_usd,
       count(*) FILTER (WHERE status <> 'ok') AS errors, max(created_at) AS last_run
FROM agent_runs WHERE started_at >= current_date GROUP BY department;

CREATE OR REPLACE VIEW v_receivables_open AS
SELECT r.*, (current_date - r.due_at) AS days_overdue, l.display_name, l.market_code AS lead_market
FROM receivables r LEFT JOIN leads l ON l.id = r.lead_id
WHERE r.status IN ('open', 'partially_paid', 'overdue');
