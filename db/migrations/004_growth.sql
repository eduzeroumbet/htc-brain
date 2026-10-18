-- 004 — Marketing: Gestor de Conteúdo Social (calendário, publicação, métricas por post) e
--       Analista de Marketing & Tráfego (playbooks por mercado, experimentos test-and-learn dentro do budget).

-- ───────────── Social ─────────────
ALTER TABLE content_items ADD COLUMN IF NOT EXISTS platform text;          -- instagram|facebook|telegram|vk|youtube|tiktok|snapchat|linkedin|x|dzen
ALTER TABLE content_items ADD COLUMN IF NOT EXISTS hashtags text[];
ALTER TABLE content_items ADD COLUMN IF NOT EXISTS media_brief text;       -- o que a imagem/vídeo precisa mostrar (sem rosto de cliente)
ALTER TABLE content_items ADD COLUMN IF NOT EXISTS repurposed_from uuid REFERENCES content_items(id);
ALTER TABLE content_items ADD COLUMN IF NOT EXISTS jev_quality numeric(4,3); -- social/post-analyze: potencial da peça 0–1
ALTER TABLE content_items ADD COLUMN IF NOT EXISTS experiment_id uuid;

CREATE TABLE IF NOT EXISTS social_accounts (
  id              text PRIMARY KEY,                 -- ex.: ig_highclass_br, tg_highclass_ru
  platform        text NOT NULL,
  handle          text NOT NULL,
  market_codes    text[] NOT NULL,
  language        text,
  external_id     text,                             -- page id / channel id
  token_env       text,                             -- nome da variável de ambiente com o token (nunca o token)
  followers       integer,
  active          boolean NOT NULL DEFAULT true,
  updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS post_metrics_daily (
  day             date NOT NULL,
  content_id      uuid NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
  impressions     integer DEFAULT 0,
  reach           integer DEFAULT 0,
  likes           integer DEFAULT 0,
  comments        integer DEFAULT 0,
  saves           integer DEFAULT 0,
  shares          integer DEFAULT 0,
  clicks          integer DEFAULT 0,
  leads           integer DEFAULT 0,                -- leads com source_content_id = content_id
  PRIMARY KEY (day, content_id)
);
ALTER TABLE leads ADD COLUMN IF NOT EXISTS source_content_id uuid REFERENCES content_items(id);
ALTER TABLE leads ADD COLUMN IF NOT EXISTS source_campaign_id uuid REFERENCES campaigns(id);
ALTER TABLE leads ADD COLUMN IF NOT EXISTS source_experiment_id uuid;

-- ───────────── Analista de mercado ─────────────
CREATE TABLE IF NOT EXISTS market_playbooks (
  market_code     text PRIMARY KEY REFERENCES markets(code),
  version         smallint NOT NULL DEFAULT 1,
  knowledge_level text NOT NULL DEFAULT 'low',      -- low|medium|high — quanto a máquina já sabe deste mercado
  b2c_channels    jsonb NOT NULL DEFAULT '[]',      -- [{channel, status: available|restricted|blocked, role, est_cpl_usd, notes, verified_at}]
  b2b_channels    jsonb NOT NULL DEFAULT '[]',      -- [{channel, kind: association|fair|directory|operator|media, how, notes}]
  legal_notes     text,                             -- rotulagem de anúncios, dados, sanções, proibições
  payment_notes   text,
  creative_norms  text,                             -- idioma, formatos, horários, o que funciona/evitar
  seasonality     text,
  competitors     jsonb DEFAULT '[]',
  open_questions  text[],                           -- o que ainda não sabemos e como vamos descobrir (experimento)
  sources         jsonb DEFAULT '[]',               -- [{url, title, fetched_at}]
  updated_by      text,
  updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS experiments (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  market_code     text REFERENCES markets(code),
  name            text NOT NULL,
  hypothesis      text NOT NULL,                    -- "Se X então Y porque Z"
  kind            text NOT NULL,                    -- paid_channel|creative|audience|landing|offer|b2b_outreach|organic_format
  channel         text,                             -- yandex_direct|vk_ads|telegram_ads|meta|google_search|youtube|influencer|...
  campaign_id     uuid REFERENCES campaigns(id),
  budget_usd      numeric(10,2) NOT NULL,           -- teto do experimento (dentro do budget do mercado)
  daily_budget_usd numeric(10,2),
  duration_days   smallint NOT NULL DEFAULT 14,
  success_metric  text NOT NULL,                    -- cpl_usd|cac_usd|lead_quality|reply_rate|ctr
  success_target  numeric(10,2) NOT NULL,
  kill_rule       text,                             -- "CPL > 2x alvo após USD 40" etc.
  status          text NOT NULL DEFAULT 'proposed', -- proposed, approved, running, paused, won, lost, inconclusive, cancelled
  jev_promise     numeric(4,3),                     -- probabilidade de sucesso estimada pelo Jev
  spend_usd       numeric(10,2) NOT NULL DEFAULT 0,
  result          jsonb,                            -- {leads, cpl, bookings, cac, learning}
  learning        text,                             -- o que aprendemos (vai para o playbook)
  decision_id     uuid REFERENCES decisions(id),
  started_at      timestamptz,
  ended_at        timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS experiments_status_idx ON experiments (status, market_code);
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS experiment_id uuid REFERENCES experiments(id);

CREATE OR REPLACE VIEW v_experiment_results AS
SELECT e.*, coalesce(sum(a.spend_usd),0) AS spend_actual_usd, coalesce(sum(a.leads),0) AS leads, coalesce(sum(a.bookings),0) AS bookings,
       CASE WHEN coalesce(sum(a.leads),0) > 0 THEN round(coalesce(sum(a.spend_usd),0)/sum(a.leads), 2) END AS cpl_usd,
       CASE WHEN coalesce(sum(a.bookings),0) > 0 THEN round(coalesce(sum(a.spend_usd),0)/sum(a.bookings), 2) END AS cac_usd
FROM experiments e LEFT JOIN campaigns c ON c.experiment_id = e.id LEFT JOIN ad_spend_daily a ON a.campaign_id = c.id
GROUP BY e.id;

-- Contas sociais da agência (tokens ficam em variáveis de ambiente; aqui só o nome da variável)
INSERT INTO social_accounts (id, platform, handle, market_codes, language, token_env) VALUES
  ('ig_highclass',    'instagram', 'highclasstravelexperiences', ARRAY['BR','IN','GB','US','DE','SA'], 'multi', 'IG_HIGHCLASS_TOKEN'),
  ('fb_highclass',    'facebook',  'highclasstravelexperiences', ARRAY['BR','IN','GB','US'],           'multi', 'FB_HIGHCLASS_TOKEN'),
  ('tg_highclass_ru', 'telegram',  '@highclass_dubai_ru',        ARRAY['RU'],                          'ru',    'TG_HIGHCLASS_RU_BOT_TOKEN'),
  ('vk_highclass',    'vk',        'highclass_dubai',            ARRAY['RU'],                          'ru',    'VK_HIGHCLASS_TOKEN'),
  ('li_highclass',    'linkedin',  'high-class-travel-experiences', ARRAY['BR','IN','GB','US','DE','SA','RU'], 'en', NULL)
ON CONFLICT (id) DO NOTHING;

-- Playbooks iniciais (a base narrativa está em knowledge/markets/*.md; aqui só o nível para o Analista começar)
INSERT INTO market_playbooks (market_code, knowledge_level, open_questions, updated_by) VALUES
  ('RU', 'low',    ARRAY['intermediário para Yandex Direct/VK Ads com ERID', 'estado do YouTube/Instagram na Rússia', 'operadoras russas que aceitam DMC novo', 'pagamento: cartões KZ/AM/GE no gateway'], 'seed'),
  ('IN', 'medium', ARRAY['faixas TCS/LRS vigentes', 'visa on arrival para indianos com vistos de terceiros', 'CPL real por cidade/idioma', 'gateway com EMI'], 'seed'),
  ('SA', 'low',    ARRAY['Snapchat/TikTok Ads a partir de Dubai para KSA: custo e regras', 'agências sauditas que vendem EAU', 'conteúdo e horários no Ramadã'], 'seed'),
  ('DE', 'low',    ARRAY['Pauschalreise: a agência é organizadora? seguro de insolvência', 'Google/Meta CPL em alemão', 'DRV e feiras (ITB)'], 'seed'),
  ('US', 'low',    ARRAY['Virtuoso/ASTA: como entrar', 'CPL em busca para "Dubai trip cost"', 'seller of travel registration (CA/FL/WA/HI)'], 'seed')
ON CONFLICT (market_code) DO NOTHING;
