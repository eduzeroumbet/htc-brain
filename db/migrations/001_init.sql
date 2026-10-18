-- Esquema do cérebro. Idempotente: pode rodar várias vezes.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ───────────────────────── mercados e leads ─────────────────────────
CREATE TABLE IF NOT EXISTS markets (
  code            text PRIMARY KEY,                 -- BR, IN, SA, GB, RU, DE, US
  name            text NOT NULL,
  language        text NOT NULL,
  currency        text NOT NULL,
  timezone        text NOT NULL,
  active          boolean NOT NULL DEFAULT false,
  wave            smallint NOT NULL DEFAULT 1,
  config          jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS leads (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  market_code     text REFERENCES markets(code),
  channel         text NOT NULL,                    -- whatsapp, instagram, messenger, telegram, email, webchat
  channel_user_id text NOT NULL,                    -- wa_id, ig_scoped_id, tg chat id, email
  display_name    text,
  phone           text,
  email           text,
  language        text,
  stage           text NOT NULL DEFAULT 'new',      -- new, qualifying, qualified, quoted, negotiating, won, lost, nurture
  segment         text,
  travel_dates    daterange,
  pax_adults      smallint,
  pax_children    smallint,
  budget_usd_min  numeric(10,2),
  budget_usd_max  numeric(10,2),
  occasion        text,
  source_campaign text,
  utm             jsonb DEFAULT '{}'::jsonb,
  consent_marketing boolean NOT NULL DEFAULT false,
  consent_at      timestamptz,
  opt_in_whatsapp boolean NOT NULL DEFAULT false,
  score           smallint DEFAULT 0,
  human_owner     text,                              -- preenchido durante handoff
  notes           text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (channel, channel_user_id)
);
CREATE INDEX IF NOT EXISTS leads_market_stage_idx ON leads(market_code, stage);
CREATE INDEX IF NOT EXISTS leads_created_idx ON leads(created_at);

CREATE TABLE IF NOT EXISTS conversations (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  lead_id         uuid NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  channel         text NOT NULL,
  status          text NOT NULL DEFAULT 'ai',       -- ai, human, closed
  chatwoot_conversation_id bigint,
  agent_session_id text,                             -- sessão do Claude Agent SDK para retomar contexto
  escalation_trigger text,
  first_response_ms integer,
  csat            smallint,
  started_at      timestamptz NOT NULL DEFAULT now(),
  last_message_at timestamptz NOT NULL DEFAULT now(),
  closed_at       timestamptz
);
CREATE INDEX IF NOT EXISTS conversations_lead_idx ON conversations(lead_id);

CREATE TABLE IF NOT EXISTS messages (
  id              bigserial PRIMARY KEY,
  conversation_id uuid NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  direction       text NOT NULL,                    -- in, out
  author          text NOT NULL,                    -- client, ai:<agent>, human:<name>, system
  body            text,
  media_url       text,
  channel_message_id text,
  language        text,
  intent          text,
  sentiment       real,
  risk_flags      text[] DEFAULT '{}',
  tokens_in       integer,
  tokens_out      integer,
  cost_usd        numeric(10,5),
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS messages_conv_idx ON messages(conversation_id, created_at);

-- ───────────────────────── catálogo e fornecedores ─────────────────────────
CREATE TABLE IF NOT EXISTS suppliers (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  name            text NOT NULL,
  kind            text NOT NULL,                    -- dmc, hotel, platform, transfer, guide, insurance, visa
  det_license     text,
  det_license_valid_until date,
  contact         jsonb DEFAULT '{}'::jsonb,
  api             jsonb DEFAULT '{}'::jsonb,        -- tipo de integração e credenciais (ref ao .env)
  payment_terms   text,
  confirmation_sla_minutes integer DEFAULT 120,
  reliability_score real DEFAULT 1.0,
  active          boolean NOT NULL DEFAULT true,
  approved_by_ceo boolean NOT NULL DEFAULT false,
  created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS catalog_items (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  supplier_id     uuid REFERENCES suppliers(id),
  sku             text UNIQUE,
  kind            text NOT NULL,                    -- hotel, experience, transfer, package, visa, insurance, esim
  name            text NOT NULL,
  description     jsonb NOT NULL DEFAULT '{}'::jsonb,   -- {"pt": "...", "en": "...", "ar": "..."}
  location        text,
  duration_hours  numeric(5,2),
  nights          smallint,
  star_rating     numeric(2,1),
  net_price_usd   numeric(10,2) NOT NULL,
  markup_pct      numeric(5,2) NOT NULL,
  sell_price_usd  numeric(10,2) GENERATED ALWAYS AS (round(net_price_usd * (1 + markup_pct/100), 2)) STORED,
  price_basis     text NOT NULL DEFAULT 'per_person', -- per_person, per_room_night, per_vehicle, flat
  seasonality     jsonb DEFAULT '{}'::jsonb,        -- {"2026-12-20/2027-01-05": 1.35}
  availability_note text,
  suitable_for    text[] DEFAULT '{}',              -- family, honeymoon, luxury, budget, halal, vegetarian
  markets         text[] DEFAULT '{}',              -- vazio = todos
  media           jsonb DEFAULT '[]'::jsonb,
  cancellation_hours integer DEFAULT 72,
  active          boolean NOT NULL DEFAULT true,
  updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS catalog_kind_idx ON catalog_items(kind) WHERE active;

-- ───────────────────────── cotações e reservas ─────────────────────────
CREATE TABLE IF NOT EXISTS quotes (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  lead_id         uuid NOT NULL REFERENCES leads(id),
  market_code     text REFERENCES markets(code),
  title           text,
  items           jsonb NOT NULL,                   -- [{catalog_item_id, qty, date, unit_sell_usd, unit_net_usd}]
  subtotal_usd    numeric(10,2) NOT NULL,
  discount_pct    numeric(5,2) DEFAULT 0,
  total_usd       numeric(10,2) NOT NULL,
  total_local     numeric(12,2),
  local_currency  text,
  margin_usd      numeric(10,2),
  margin_pct      numeric(5,2),
  pdf_url         text,
  valid_until     date,
  status          text NOT NULL DEFAULT 'sent',     -- draft, sent, accepted, expired, rejected
  approved_by     text,                             -- ai, chief_of_staff, ceo (quando desconto > limite)
  created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bookings (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  ref             text UNIQUE,                      -- ex.: DXB-2026-000123
  lead_id         uuid NOT NULL REFERENCES leads(id),
  quote_id        uuid REFERENCES quotes(id),
  market_code     text REFERENCES markets(code),
  travel_start    date,
  travel_end      date,
  pax             jsonb,                            -- [{name_enc, passport_enc, dob, nationality}]
  items           jsonb NOT NULL,
  total_usd       numeric(10,2) NOT NULL,
  net_cost_usd    numeric(10,2),
  margin_usd      numeric(10,2),
  paid_usd        numeric(10,2) DEFAULT 0,
  payment_status  text NOT NULL DEFAULT 'pending',  -- pending, deposit, paid, refunded, partial_refund, disputed
  status          text NOT NULL DEFAULT 'confirming', -- confirming, confirmed, in_trip, completed, cancelled
  supplier_confirmations jsonb DEFAULT '[]'::jsonb,
  vouchers        jsonb DEFAULT '[]'::jsonb,
  pii_purge_after date,                             -- travel_end + 30 dias
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS bookings_market_created_idx ON bookings(market_code, created_at);

CREATE TABLE IF NOT EXISTS payments (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  booking_id      uuid REFERENCES bookings(id),
  gateway         text NOT NULL,                    -- stripe, tap, telr, pix
  gateway_ref     text,
  amount_usd      numeric(10,2) NOT NULL,
  amount_local    numeric(12,2),
  currency        text,
  kind            text NOT NULL,                    -- charge, refund, chargeback
  status          text NOT NULL,
  created_at      timestamptz NOT NULL DEFAULT now()
);

-- ───────────────────────── marketing ─────────────────────────
CREATE TABLE IF NOT EXISTS content_items (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  market_code     text REFERENCES markets(code),
  pillar          text,
  format          text NOT NULL,                    -- post, reel_script, blog, email, landing, ad_creative
  channel         text,
  language        text,
  title           text,
  body            text,
  media           jsonb DEFAULT '[]'::jsonb,
  status          text NOT NULL DEFAULT 'draft',    -- draft, compliance_review, approved, scheduled, published, rejected
  compliance_notes text,
  scheduled_for   timestamptz,
  published_at    timestamptz,
  external_id     text,
  metrics         jsonb DEFAULT '{}'::jsonb,        -- reach, likes, saves, clicks, leads
  created_by      text DEFAULT 'ai:content_studio',
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS content_market_status_idx ON content_items(market_code, status);

CREATE TABLE IF NOT EXISTS campaigns (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  market_code     text REFERENCES markets(code),
  platform        text NOT NULL,                    -- meta, google_search, tiktok, snapchat, yandex_direct, vk, youtube
  external_id     text,
  name            text,
  objective       text,
  daily_budget_usd numeric(10,2),
  status          text NOT NULL DEFAULT 'active',   -- active, paused, ended
  created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ad_spend_daily (
  day             date NOT NULL,
  campaign_id     uuid REFERENCES campaigns(id),
  market_code     text REFERENCES markets(code),
  platform        text,
  spend_usd       numeric(10,2) NOT NULL DEFAULT 0,
  impressions     integer DEFAULT 0,
  clicks          integer DEFAULT 0,
  leads           integer DEFAULT 0,
  bookings        integer DEFAULT 0,
  revenue_usd     numeric(10,2) DEFAULT 0,
  PRIMARY KEY (day, campaign_id)
);

-- ───────────────────────── operação dos agentes ─────────────────────────
CREATE TABLE IF NOT EXISTS agent_runs (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  agent           text NOT NULL,
  market_code     text,
  trigger         text NOT NULL,                    -- cron, event, manual
  input_summary   text,
  output_summary  text,
  status          text NOT NULL,                    -- ok, error, budget_exceeded, escalated
  model           text,
  tokens_in       integer DEFAULT 0,
  tokens_out      integer DEFAULT 0,
  cost_usd        numeric(10,5) DEFAULT 0,
  duration_ms     integer,
  langfuse_trace_id text,
  error           text,
  started_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS agent_runs_agent_day_idx ON agent_runs(agent, started_at);

CREATE TABLE IF NOT EXISTS escalations (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  conversation_id uuid REFERENCES conversations(id),
  lead_id         uuid REFERENCES leads(id),
  trigger_id      text NOT NULL,
  severity        text NOT NULL,
  summary         text,
  suggested_action text,
  chatwoot_conversation_id bigint,
  notified_ceo    boolean DEFAULT false,
  status          text NOT NULL DEFAULT 'open',     -- open, acknowledged, resolved
  resolved_by     text,
  outcome         text,
  opened_at       timestamptz NOT NULL DEFAULT now(),
  acknowledged_at timestamptz,
  resolved_at     timestamptz
);

CREATE TABLE IF NOT EXISTS decisions (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  kind            text NOT NULL,                    -- discount, budget_increase, new_supplier, new_market, refund, content_campaign, prompt_change
  context         text NOT NULL,
  recommendation  text NOT NULL,
  requested_by    text NOT NULL,                    -- ai:<agent>
  amount_usd      numeric(10,2),
  market_code     text,
  status          text NOT NULL DEFAULT 'pending',  -- pending, approved, rejected, expired
  decided_by      text,
  decided_at      timestamptz,
  becomes_rule    boolean DEFAULT false,
  created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rules (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  scope           text NOT NULL,                    -- pricing, media, content, escalation, supplier
  rule            text NOT NULL,
  origin_decision_id uuid REFERENCES decisions(id),
  active          boolean NOT NULL DEFAULT true,
  created_at      timestamptz NOT NULL DEFAULT now()
);

-- ───────────────────────── conhecimento (RAG) ─────────────────────────
CREATE TABLE IF NOT EXISTS knowledge_chunks (
  id              bigserial PRIMARY KEY,
  market_code     text,                             -- NULL = global
  topic           text NOT NULL,                    -- safety_2026, visa_process, rules_for_visitors, hotel:<id>, ...
  source_url      text,
  source_date     date,
  language        text,
  content         text NOT NULL,
  embedding       vector(1024),
  valid_until     date,
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS knowledge_embedding_idx ON knowledge_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS knowledge_topic_idx ON knowledge_chunks(topic, market_code);

-- ───────────────────────── KPIs diários (lidos pelo dashboard) ─────────────────────────
CREATE TABLE IF NOT EXISTS kpis_daily (
  day             date NOT NULL,
  market_code     text NOT NULL DEFAULT 'ALL',
  leads_new       integer DEFAULT 0,
  leads_qualified integer DEFAULT 0,
  quotes_sent     integer DEFAULT 0,
  bookings        integer DEFAULT 0,
  revenue_usd     numeric(12,2) DEFAULT 0,
  margin_usd      numeric(12,2) DEFAULT 0,
  ad_spend_usd    numeric(10,2) DEFAULT 0,
  token_cost_usd  numeric(10,2) DEFAULT 0,
  conversations   integer DEFAULT 0,
  escalations     integer DEFAULT 0,
  first_response_p50_s real,
  csat_avg        real,
  content_published integer DEFAULT 0,
  PRIMARY KEY (day, market_code)
);

-- ───────────────────────── views ─────────────────────────
CREATE OR REPLACE VIEW v_funnel_30d AS
SELECT
  m.code AS market_code,
  count(l.*) FILTER (WHERE l.created_at > now() - interval '30 days') AS leads,
  count(l.*) FILTER (WHERE l.stage IN ('qualified','quoted','negotiating','won') AND l.created_at > now() - interval '30 days') AS qualified,
  (SELECT count(*) FROM quotes q WHERE q.market_code = m.code AND q.created_at > now() - interval '30 days') AS quotes,
  (SELECT count(*) FROM bookings b WHERE b.market_code = m.code AND b.created_at > now() - interval '30 days' AND b.status <> 'cancelled') AS bookings,
  (SELECT coalesce(sum(total_usd),0) FROM bookings b WHERE b.market_code = m.code AND b.created_at > now() - interval '30 days' AND b.status <> 'cancelled') AS revenue_usd,
  (SELECT coalesce(sum(spend_usd),0) FROM ad_spend_daily a WHERE a.market_code = m.code AND a.day > current_date - 30) AS ad_spend_usd
FROM markets m LEFT JOIN leads l ON l.market_code = m.code
GROUP BY m.code;

-- ───────────────────────── funções utilitárias ─────────────────────────
CREATE OR REPLACE FUNCTION touch_updated_at() RETURNS trigger AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END $$ LANGUAGE plpgsql;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'leads_touch') THEN
    CREATE TRIGGER leads_touch BEFORE UPDATE ON leads FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'bookings_touch') THEN
    CREATE TRIGGER bookings_touch BEFORE UPDATE ON bookings FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
  END IF;
END $$;

-- seed dos mercados (config detalhada vem dos YAML em config/markets)
INSERT INTO markets (code, name, language, currency, timezone, active, wave) VALUES
  ('BR', 'Brasil', 'pt-BR', 'BRL', 'America/Sao_Paulo', true, 1),
  ('IN', 'Índia', 'en-IN', 'INR', 'Asia/Kolkata', true, 1),
  ('SA', 'Arábia Saudita e GCC', 'ar-SA', 'SAR', 'Asia/Riyadh', true, 1),
  ('GB', 'Reino Unido', 'en-GB', 'GBP', 'Europe/London', true, 1),
  ('RU', 'Rússia e Cazaquistão', 'ru', 'RUB', 'Europe/Moscow', false, 2),
  ('DE', 'Alemanha (DACH)', 'de', 'EUR', 'Europe/Berlin', false, 2),
  ('US', 'Estados Unidos', 'en-US', 'USD', 'America/New_York', false, 2)
ON CONFLICT (code) DO NOTHING;
