-- 007 — Validação global: o atendimento multilíngue já existe (Huda, WhatsApp +55 11 95502-6224, 7 idiomas),
-- então a fase de validação da Dubai Explore roda em TODOS os mercados de config/markets (radar) e não só no BR.
-- Também registra a Huda como atendente externa: o cérebro não responde a esses clientes, só recebe lead/handoff em /webhooks/huda.

-- a página Dubai Explore passa a cobrir todos os mercados
UPDATE social_accounts SET market_codes = ARRAY['BR','IN','RU','GB','DE','SA','US'] WHERE id IN ('fb_dubai_explore','ig_dubai_explore');

-- substitui a regra de mídia "BR primeiro" pela regra global em duas camadas
DELETE FROM rules WHERE scope = 'media' AND rule LIKE 'Fase de validação (out/2026)%';
INSERT INTO rules (scope, rule) VALUES
  ('media', 'Fase de validação (out/2026), camada 1 — RADAR: um criativo universal (visual forte, pouco texto, legenda no idioma do mercado) rodando em paralelo nos 7 mercados (BR, IN, RU, GB, DE, SA, US) pela página Dubai Explore, objetivo mensagens/Click-to-WhatsApp para o número da Huda, ~USD 40 por mercado em 7 dias. Métricas: CPM, CTR, custo por conversa iniciada e jev_fit dos leads. Nenhuma campanha fora de um experimento registrado (kind=paid_channel, name "RADAR-<mercado>").'),
  ('media', 'Fase de validação (out/2026), camada 2 — CONVERSÃO: no dia 8 o Analista de Mercado ordena os mercados pelo radar (custo por lead com jev_fit ≥ 0,6) e os 2 melhores recebem experimentos de oferta concreta (Click-to-WhatsApp, "a partir de", o que inclui) por 14 dias; os outros 5 ficam só com conteúdo orgânico até a próxima rodada. Veredito pelo Jev; vencedor escala +30%/semana enquanto CPL ≤ alvo do mercado.'),
  ('media', 'Em mídia paga, RU usa Meta só como radar; se o radar RU der sinal, a camada 2 em RU roda em Yandex Direct/VK/Telegram Ads (Meta tem alcance limitado na Rússia). SA/GCC: considerar Snapchat/TikTok na camada 2.'),
  ('service', 'Atendimento de primeiro contato no WhatsApp é da Huda (sistema externo, 7 idiomas, número +55 11 95502-6224). O cérebro NÃO responde a clientes desse número; recebe lead e handoff pelo webhook /webhooks/huda e segue a partir daí (Operacional, Financeiro, CRM). Enquanto o gateway da Huda estiver fora do ar (Evolution/Cloudfy), NENHUM anúncio com destino WhatsApp pode ser ativado — o Paid Media verifica no início do ciclo.')
ON CONFLICT DO NOTHING;

-- marca leads atendidos pela Huda (utm.attended_by = 'huda') para a visão de experimentos
CREATE OR REPLACE VIEW v_leads_by_attendant AS
SELECT COALESCE(utm->>'attended_by', 'brain') AS attended_by, market_code, source_campaign,
       count(*) AS leads, count(*) FILTER (WHERE jev_fit >= 0.6) AS qualified_leads,
       count(*) FILTER (WHERE stage IN ('quoted','negotiating','won')) AS quoted_or_better,
       min(created_at) AS first_lead, max(created_at) AS last_lead
FROM leads GROUP BY 1, 2, 3;
