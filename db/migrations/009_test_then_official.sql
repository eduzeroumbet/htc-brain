-- 009 — Decisão de 10/10/2026: TODOS os anúncios nascem na conta de teste (portfólio Dubai Explore: página 1253783911161807,
-- conta act_4488704318017176, app High Class Brain 1135462119431461). Só depois de aprovados — resultado do experimento + Compliance +
-- decisão da CEO (kind='promote_to_official') — são replicados na conta oficial da High Class (META_OFFICIAL_* no .env).
INSERT INTO rules (scope, rule) VALUES
  ('media', 'Ambiente de TESTE = portfólio Dubai Explore (META_ADS_ACCOUNT_ID=act_4488704318017176, página 1253783911161807). Toda campanha e todo criativo são criados primeiro aqui, dentro de um experimento. Replicar na conta oficial da High Class (META_OFFICIAL_ADS_ACCOUNT_ID / META_OFFICIAL_PAGE_ID) só com: experimento com status won, aprovação do Compliance registrada e decisão da CEO kind=promote_to_official aprovada. Sem os três, a conta oficial não recebe nada.'),
  ('content', 'Posts e criativos de teste saem pela página Dubai Explore; a página oficial da High Class só recebe o que a CEO promover (promote_to_official). Nunca publicar o mesmo criativo nas duas páginas ao mesmo tempo.')
ON CONFLICT DO NOTHING;
