-- 005 — Áreas que faltavam: Jurídico & Dados, Gestão de Parceiros B2B, Pessoas, Infra/SysOps, MICE & Eventos (HCB1), reputação.

-- ───────────── Jurídico, dados e regulatório ─────────────
CREATE TABLE IF NOT EXISTS contracts (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  kind            text NOT NULL,                    -- partner_agency|supplier|client_terms|mice|venue|freelancer|lease|insurance|other
  counterparty    text NOT NULL,
  partner_id      uuid REFERENCES partner_agencies(id),
  supplier_id     uuid REFERENCES suppliers(id),
  entity          text NOT NULL DEFAULT 'HCTE',     -- HCTE | HCB1
  template        text,                             -- nome do modelo usado
  status          text NOT NULL DEFAULT 'draft',    -- draft, sent, negotiating, signed, active, expired, terminated
  starts_at       date, ends_at date,
  auto_renew      boolean DEFAULT false,
  key_terms       jsonb DEFAULT '{}',               -- {commission_pct, payment_days, liability_cap, governing_law, data_clause}
  document_url    text,
  signed_by_ceo_at timestamptz,
  review_notes    text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS data_requests (          -- DSAR: acesso, correção, exclusão, portabilidade, oposição
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  lead_id         uuid REFERENCES leads(id),
  requester       text NOT NULL,                    -- identificador do canal/e-mail
  kind            text NOT NULL,                    -- access|rectification|erasure|portability|objection|consent_withdrawal
  jurisdiction    text,                             -- UAE_PDPL|LGPD|GDPR|UK_GDPR|DPDP|PDPL_KSA|CCPA
  received_at     timestamptz NOT NULL DEFAULT now(),
  due_at          timestamptz NOT NULL,             -- 15 dias (nossa política) ou prazo legal menor
  status          text NOT NULL DEFAULT 'open',     -- open, verifying_identity, in_progress, completed, refused
  actions         text,
  completed_at    timestamptz
);

CREATE TABLE IF NOT EXISTS sanctions_screenings (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  subject_kind    text NOT NULL,                    -- lead|partner|supplier
  subject_id      uuid,
  name_checked    text NOT NULL,
  country         text,
  lists           text[] NOT NULL,                  -- OFAC_SDN|EU|UK_HMT|UN|UAE_local
  result          text NOT NULL,                    -- clear|possible_match|match|error
  detail          jsonb,
  screened_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS legal_incidents (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  kind            text NOT NULL,                    -- data_breach|consumer_complaint|regulator_notice|accident|public_crisis|chargeback_dispute|other
  severity        text NOT NULL DEFAULT 'medium',
  title           text NOT NULL,
  detail          text,
  status          text NOT NULL DEFAULT 'open',     -- open, assessing, notified, resolved
  notify_deadline timestamptz,                      -- ex.: PDPL/GDPR 72h
  owner           text DEFAULT 'legal_compliance',
  decision_id     uuid REFERENCES decisions(id),
  opened_at       timestamptz NOT NULL DEFAULT now(),
  resolved_at     timestamptz
);

-- ───────────── Parceiros B2B ─────────────
ALTER TABLE quotes ADD COLUMN IF NOT EXISTS partner_id uuid REFERENCES partner_agencies(id);   -- cotação B2B (net rate)
ALTER TABLE quotes ADD COLUMN IF NOT EXISTS pricing_mode text DEFAULT 'retail';               -- retail | net | commissionable
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS partner_id uuid REFERENCES partner_agencies(id);
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS commission_usd numeric(10,2);
ALTER TABLE partner_agencies ADD COLUMN IF NOT EXISTS pricing_mode text DEFAULT 'commissionable';
ALTER TABLE partner_agencies ADD COLUMN IF NOT EXISTS payment_terms text;                     -- prepaid|net15|net30
ALTER TABLE partner_agencies ADD COLUMN IF NOT EXISTS portal_user text;                       -- login do portal B2B (sem senha aqui)
ALTER TABLE partner_agencies ADD COLUMN IF NOT EXISTS health_score numeric(4,3);              -- Jev: saúde da parceria 0–1
ALTER TABLE partner_agencies ADD COLUMN IF NOT EXISTS last_booking_at timestamptz;

CREATE TABLE IF NOT EXISTS commission_statements (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  partner_id      uuid NOT NULL REFERENCES partner_agencies(id),
  period          text NOT NULL,                    -- YYYY-MM
  bookings        jsonb NOT NULL,                   -- [{ref, travel_start, total_usd, commission_usd}]
  total_commission_usd numeric(10,2) NOT NULL,
  status          text NOT NULL DEFAULT 'draft',    -- draft, sent, approved_by_partner, paid
  payable_id      uuid REFERENCES payables(id),
  document_url    text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (partner_id, period)
);

-- ───────────── Pessoas (humanos que ficam) ─────────────
CREATE TABLE IF NOT EXISTS staff (
  id              text PRIMARY KEY,                 -- drv_abdul, ops_resolver_1, guide_<uuid>...
  name            text NOT NULL,
  role            text NOT NULL,                    -- driver|guide|resolver|duty_senior|contractor
  employment      text NOT NULL,                    -- employee|freelancer|contractor
  whatsapp_env    text,
  languages       text[],
  visa_expiry     date, labour_card_expiry date, passport_expiry date, licence_expiry date, tgd_expiry date,
  monthly_salary_aed numeric(10,2),
  days_off_per_month smallint DEFAULT 4,
  active          boolean NOT NULL DEFAULT true,
  notes           text,
  updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS staff_leave (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  staff_id        text NOT NULL REFERENCES staff(id),
  kind            text NOT NULL,                    -- day_off|annual|sick|unpaid|public_holiday
  starts_on       date NOT NULL, ends_on date NOT NULL,
  status          text NOT NULL DEFAULT 'planned',  -- planned, approved, taken, cancelled
  note            text,
  created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS staff_events (            -- avaliações, ocorrências, treinamentos, elogios de cliente
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  staff_id        text NOT NULL REFERENCES staff(id),
  kind            text NOT NULL,                    -- praise|complaint|warning|training|evaluation|accident|fine
  detail          text,
  score           numeric(4,2),                     -- avaliação 0–10 (do Auditor/concierge)
  booking_id      uuid REFERENCES bookings(id),
  created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS guide_pool (              -- candidatos a guia/tradutor freelancer
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  name            text NOT NULL,
  languages       text[] NOT NULL,
  licence_no      text, licence_expiry date,
  vip_cleared     boolean DEFAULT false,
  source          text,                             -- indicação|DET|linkedin|outro
  stage           text NOT NULL DEFAULT 'candidate', -- candidate, contacted, vetted, trial, active, inactive, rejected
  rate_aed_per_day numeric(10,2),
  notes           text,
  created_at      timestamptz NOT NULL DEFAULT now()
);

-- ───────────── Infra / SysOps ─────────────
CREATE TABLE IF NOT EXISTS health_checks (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  checked_at      timestamptz NOT NULL DEFAULT now(),
  component       text NOT NULL,                    -- db|redis|queue_inbound|queue_tasks|webhook_whatsapp|webhook_meta|webhook_telegram|email_poll|anthropic|jev|backup|tls|disk|tokens_budget
  status          text NOT NULL,                    -- ok|degraded|down|unknown
  value           numeric(14,2),
  detail          text
);
CREATE INDEX IF NOT EXISTS health_checks_idx ON health_checks (component, checked_at DESC);

CREATE TABLE IF NOT EXISTS incidents (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  component       text NOT NULL,
  severity        text NOT NULL,                    -- sev1 (clientes sem resposta) | sev2 | sev3
  title           text NOT NULL,
  detail          text,
  status          text NOT NULL DEFAULT 'open',     -- open, mitigated, resolved
  opened_at       timestamptz NOT NULL DEFAULT now(),
  resolved_at     timestamptz,
  postmortem      text
);

-- ───────────── MICE & Eventos (HCB1 Events Management LLC) ─────────────
CREATE TABLE IF NOT EXISTS mice_rfps (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  lead_id         uuid REFERENCES leads(id),
  partner_id      uuid REFERENCES partner_agencies(id),
  company         text,
  event_kind      text NOT NULL,                    -- incentive|conference|exhibition_visit|corporate_retreat|product_launch|wedding|gala
  fair_name       text,                             -- GITEX, Gulfood, ATM...
  pax             integer NOT NULL,
  dates           daterange,
  budget_pp_usd   numeric(10,2),
  requirements    jsonb DEFAULT '{}',               -- {hotel_near, venue, transfers, dinner, interpreter, badges, av, branding}
  status          text NOT NULL DEFAULT 'new',      -- new, qualifying, proposal_sent, negotiating, won, lost, delivered
  quote_id        uuid REFERENCES quotes(id),
  entity          text NOT NULL DEFAULT 'HCB1',
  decision_id     uuid REFERENCES decisions(id),
  owner           text DEFAULT 'mice_events',
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);

-- ───────────── Reputação ─────────────
CREATE TABLE IF NOT EXISTS public_reviews (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  platform        text NOT NULL,                    -- google|tripadvisor|trustpilot|facebook|instagram_comment|reclameaqui
  external_id     text,
  author          text,
  rating          smallint,
  body            text,
  language        text,
  market_code     text REFERENCES markets(code),
  booking_id      uuid REFERENCES bookings(id),
  jev_sentiment   numeric(4,3),
  status          text NOT NULL DEFAULT 'new',      -- new, replied, escalated, ignored
  reply           text,
  replied_at      timestamptz,
  received_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (platform, external_id)
);

-- seeds mínimos de staff a partir de humans.yaml (a máquina atualiza datas pelo people_ops)
INSERT INTO staff (id, name, role, employment, whatsapp_env, languages) VALUES
  ('drv_abdul', 'Abdul Rehman', 'driver', 'employee', 'DRIVER_ABDUL_WHATSAPP', ARRAY['en','ur','hi']),
  ('drv_mumtaz', 'Mumtaz Khokhar', 'driver', 'employee', 'DRIVER_MUMTAZ_WHATSAPP', ARRAY['en','ur']),
  ('ops_resolver_1', 'A DEFINIR (resolução)', 'resolver', 'employee', 'RESOLVER_1_WHATSAPP', ARRAY['en','pt','ar']),
  ('ops_resolver_2', 'A DEFINIR (plantão noturno)', 'resolver', 'contractor', 'RESOLVER_2_WHATSAPP', ARRAY['en','ar'])
ON CONFLICT (id) DO NOTHING;
