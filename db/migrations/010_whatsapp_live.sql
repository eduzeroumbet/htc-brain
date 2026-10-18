-- 010 — WhatsApp oficial no ar (Cloud API, número +971 58 515 3946, WABA 1032855926426525, phone_number_id 1337957899403844).
-- A Huda passa a ser a persona do consultor do cérebro em todos os mercados (config/markets/*.yaml); o sistema Manus/Evolution é aposentado.
DELETE FROM rules WHERE scope = 'service' AND rule LIKE 'WhatsApp em STAND-BY%';
DELETE FROM rules WHERE scope = 'media' AND rule LIKE 'Enquanto o WhatsApp estiver em stand-by%';
INSERT INTO rules (scope, rule) VALUES
  ('service', 'WhatsApp oficial (+971 58 515 3946, Cloud API) é o canal principal de atendimento e o destino dos anúncios. Quem atende é a Huda — a persona do consultor do cérebro, em todos os idiomas. O número brasileiro (+55 11 95502-6224, Manus/Evolution) está aposentado: não ofereça, não cite. Messenger e Instagram continuam atendidos pela mesma Huda.'),
  ('media',   'Destino dos anúncios da validação: Click-to-WhatsApp para +971 58 515 3946 (preferido, pois converte melhor) ou Click-to-Messenger da Dubai Explore; o Analista registra o destino em cada experimento. Antes de ativar, o Paid Media confirma que o canal respondeu a uma mensagem de teste nas últimas 24 h.')
ON CONFLICT DO NOTHING;

-- 10/10/2026: entrega para +55 bloqueada pela Meta (erro 130497) até a verificação da empresa. Regra temporária:
INSERT INTO rules (scope, rule) VALUES
  ('media', 'PENDÊNCIA (10/10/2026): a conta do WhatsApp ainda não é verificada pela Meta e NÃO entrega mensagens para alguns países (erro 130497; confirmado para o Brasil). Até a verificação da empresa concluir, nenhum anúncio Click-to-WhatsApp para BR; use Click-to-Messenger nesses mercados. O SysOps remove esta regra quando um envio de teste para +55 for entregue.')
ON CONFLICT DO NOTHING;
