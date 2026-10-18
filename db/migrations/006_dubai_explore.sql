-- 006 — "Dubai Explore": página editorial de topo de funil (Facebook id 61594438771399) usada para iniciar anúncios e validar estratégias.
-- A marca comercial continua High Class Travel Experiences; todo anúncio/post identifica a agência e a licença DET (regra abaixo).
INSERT INTO social_accounts (id, platform, handle, market_codes, language, external_id, token_env) VALUES
  ('fb_dubai_explore', 'facebook',  'Dubai Explore (profile.php?id=61594438771399)', ARRAY['BR','US','GB','IN'], 'multi', '61594438771399', 'FB_DUBAIEXPLORE_TOKEN'),
  ('ig_dubai_explore', 'instagram', 'dubaiexplore (a confirmar)',                     ARRAY['BR','US','GB','IN'], 'multi', NULL,             'IG_DUBAIEXPLORE_TOKEN')
ON CONFLICT (id) DO NOTHING;

INSERT INTO rules (scope, rule) VALUES
  ('content', 'Dubai Explore é marca editorial de topo de funil. Toda peça e todo anúncio publicados por ela trazem, no texto ou na legenda, "por High Class Travel Experiences · licença DET 781806" e o CTA leva ao WhatsApp/webchat da agência. Nunca apresentar Dubai Explore como agência ou vendedora.'),
  ('media',   'Fase de validação (out/2026): anúncios só pela página Dubai Explore, mercado BR primeiro, objetivo Click-to-WhatsApp; teto por experimento conforme experiments.*; nenhuma campanha fora de um experimento registrado.')
ON CONFLICT DO NOTHING;
