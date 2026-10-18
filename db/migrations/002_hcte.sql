-- Operação de campo e administração da HCTE: frota, motoristas, guias, escala, renovações, inventário.
-- Idempotente.

CREATE TABLE IF NOT EXISTS vehicles (
  id              text PRIMARY KEY,                 -- escalade_2023, yukon_2025, gac_m8_2026
  name            text NOT NULL,
  plate           text,
  pax_capacity    smallint NOT NULL,
  bags_seats_up   smallint,                         -- malas grandes com todos os assentos em uso
  bags_row3_down  smallint,
  category        text NOT NULL,                    -- suv_luxury, suv, mpv, sedan, van, minibus, bus
  owned           boolean NOT NULL DEFAULT true,
  odometer_km     integer DEFAULT 0,
  last_service_km integer DEFAULT 0,
  service_interval_km integer DEFAULT 10000,
  registration_expiry date,                         -- Mulkiya
  insurance_expiry date,
  salik_tag       text,
  gps_device_id   text,
  active          boolean NOT NULL DEFAULT true,
  notes           text
);

CREATE TABLE IF NOT EXISTS drivers (
  id              text PRIMARY KEY,                 -- drv_abdul, drv_mumtaz
  name            text NOT NULL,
  whatsapp        text,
  languages       text[] DEFAULT '{}',
  license_expiry  date,
  visa_expiry     date,
  labour_card_expiry date,
  iloe_expiry     date,
  max_hours_per_day smallint DEFAULT 12,
  days_off_per_month smallint DEFAULT 4,
  extra_hour_rate_aed numeric(6,2) DEFAULT 35,
  base_salary_aed numeric(8,2),
  active          boolean NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS guides (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  name            text NOT NULL,
  whatsapp        text,
  languages       text[] DEFAULT '{}',
  tgd_license     text,
  tgd_expiry      date,
  rate_half_day_aed numeric(8,2),
  rate_full_day_aed numeric(8,2),
  rating          real DEFAULT 5.0,
  vip_cleared     boolean DEFAULT false,            -- pode fazer meet & greet de VIP
  active          boolean NOT NULL DEFAULT true,
  notes           text
);

-- Um serviço de campo = 1 linha: transfer, tour com motorista, tour com guia, meet & greet, compra, entrega de abaya
CREATE TABLE IF NOT EXISTS field_assignments (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  booking_id      uuid REFERENCES bookings(id),
  lead_id         uuid REFERENCES leads(id),
  service_date    date NOT NULL,
  start_time      time NOT NULL,
  end_time        time,
  kind            text NOT NULL,                    -- transfer_in, transfer_out, tour, meet_greet, errand, abaya
  pickup          text,
  dropoff         text,
  pax             smallint,
  bags            smallint,
  vehicle_id      text REFERENCES vehicles(id),
  driver_id       text REFERENCES drivers(id),
  guide_id        uuid REFERENCES guides(id),
  third_party_supplier uuid REFERENCES suppliers(id),
  client_name     text,
  client_phone_enc text,
  vip             boolean DEFAULT false,
  briefing        text,
  status          text NOT NULL DEFAULT 'planned',  -- planned, sent, confirmed_by_driver, en_route, onboard, done, cancelled, no_show
  driver_confirmed_at timestamptz,
  started_at      timestamptz,
  finished_at     timestamptz,
  odometer_start  integer,
  odometer_end    integer,
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS field_assignments_date_idx ON field_assignments(service_date, driver_id);

CREATE TABLE IF NOT EXISTS driver_hours (
  id              bigserial PRIMARY KEY,
  driver_id       text REFERENCES drivers(id),
  day             date NOT NULL,
  hours_regular   numeric(4,2) DEFAULT 0,
  hours_extra     numeric(4,2) DEFAULT 0,
  source          text DEFAULT 'gps',               -- gps, manual, assignments
  note            text,
  UNIQUE (driver_id, day)
);

CREATE TABLE IF NOT EXISTS vehicle_events (
  id              bigserial PRIMARY KEY,
  vehicle_id      text REFERENCES vehicles(id),
  kind            text NOT NULL,                    -- fine, service, fuel, salik_topup, darb_topup, damage, registration, insurance
  amount_aed      numeric(10,2),
  description     text,
  driver_id       text REFERENCES drivers(id),
  deduct_from_driver boolean DEFAULT false,
  event_date      date NOT NULL DEFAULT current_date,
  created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS renewals (
  id              text PRIMARY KEY,                 -- de config/renewals_hcte.yaml
  name            text NOT NULL,
  due             date,
  recurrence      text,
  owner           text,
  action          text,
  status          text NOT NULL DEFAULT 'pending',  -- pending, quoted, renewed, cancelled
  last_alert_days smallint,
  renewed_at      date,
  note            text
);

CREATE TABLE IF NOT EXISTS inventory (
  id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  category        text NOT NULL,                    -- gifts_adult, gifts_kids, gifts_vip, packaging, abaya, uniform, office
  item            text NOT NULL,
  qty             integer NOT NULL DEFAULT 0,
  min_qty         integer DEFAULT 5,
  location        text DEFAULT 'office',            -- office, storage, guide:<id>, laundry
  unit_cost_aed   numeric(8,2),
  supplier        text,
  updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS inventory_moves (
  id              bigserial PRIMARY KEY,
  inventory_id    uuid REFERENCES inventory(id),
  qty_delta       integer NOT NULL,
  reason          text,                             -- gift_booking:<ref>, abaya_out:<guide>, abaya_in, purchase, adjust
  booking_id      uuid REFERENCES bookings(id),
  created_at      timestamptz NOT NULL DEFAULT now()
);

-- seed da frota e dos motoristas (manual administrativo; horas e salários reais preencher no .env / banco)
INSERT INTO vehicles (id, name, plate, pax_capacity, bags_seats_up, bags_row3_down, category, registration_expiry, notes) VALUES
  ('escalade_2023', 'Cadillac Escalade 600 2023', 'B 74772', 7, 3, 6, 'suv_luxury', '2027-02-12', 'carro VIP padrão'),
  ('yukon_2025', 'GMC Yukon 2025', 'EE 65196', 7, 3, 5, 'suv', '2026-10-21', 'confirmar se XL (5–6 malas)'),
  ('gac_m8_2026', 'GAC M8 2026', 'G 27614', 7, 4, 9, 'mpv', '2027-03-30', NULL)
ON CONFLICT (id) DO NOTHING;

INSERT INTO drivers (id, name, languages, max_hours_per_day, days_off_per_month, extra_hour_rate_aed) VALUES
  ('drv_abdul', 'Abdul Rehman', '{en,ur,hi}', 12, 4, 35),
  ('drv_mumtaz', 'Mumtaz Khokhar', '{en,ur}', 12, 4, 35)
ON CONFLICT (id) DO NOTHING;
