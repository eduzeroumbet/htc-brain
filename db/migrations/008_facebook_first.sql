-- 008 — Decisão de 05/10/2026: cadastrar o Facebook (Dubai Explore) primeiro; WhatsApp/Huda em stand-by.
-- Destino dos anúncios na validação passa a ser Click-to-Messenger: quem responde é o consultor do cérebro (canal messenger, /webhooks/meta),
-- na persona do mercado detectado pelo Jev. Quando a Huda voltar, a regra abaixo é trocada e o destino volta a ser WhatsApp.
DELETE FROM rules WHERE scope = 'service' AND rule LIKE 'Atendimento de primeiro contato no WhatsApp é da Huda%';
INSERT INTO rules (scope, rule) VALUES
  ('service', 'WhatsApp em STAND-BY (05/10/2026): a Huda (sistema externo, +55 11 95502-6224) está fora do ar e não é destino de nada por enquanto. Primeiro contato vindo de anúncios acontece no Messenger da página Dubai Explore e é respondido pelo consultor do cérebro na persona do mercado (Camila BR, etc.), apresentando-se pela High Class. Não ofereça WhatsApp ao cliente até esta regra mudar; ofereça continuar aqui ou e-mail.'),
  ('media',   'Enquanto o WhatsApp estiver em stand-by, o destino de todo anúncio da validação é Click-to-Messenger (página Dubai Explore) ou tráfego para highclass.you — nunca Click-to-WhatsApp. O identificador legal e o CTA ("manda DUBAI aqui no Messenger") continuam obrigatórios.')
ON CONFLICT DO NOTHING;

-- ID real da página na Graph API (o 61594438771399 é só o id do perfil/URL): confirmado no Business Manager em 05/10/2026.
UPDATE social_accounts SET external_id = '1253783911161807', handle = 'Dubai Explore (page id 1253783911161807 · url profile.php?id=61594438771399)' WHERE id = 'fb_dubai_explore';
