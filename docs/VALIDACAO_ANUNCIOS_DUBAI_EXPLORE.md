# Dubai Explore — validação global de anúncios (7 mercados, 21 dias)

Página: facebook.com/profile.php?id=61594438771399 · **Page ID (Graph API): 1253783911161807** · portfólio "Dubai Explore" (business_id 4437228899926551, adicionada em 05/10/2026) · estado em 04/10/2026: 1 seguidor, sem capa, sem site, sem endereço, bio em inglês, categoria *Tourist Information Center*, nenhuma publicação além da foto de perfil.

Papel na máquina: **marca editorial de topo de funil**. Ela atrai e qualifica; quem vende é a High Class. Codificado em `rules` (migrações 006 e 007), nos prompts do Compliance (item 9), Gestor Social, Paid Media e Analista de Mercado.

Quem atende: **Huda** — a consultora de WhatsApp que já existe (site highclass.you, Manus WebDev + Evolution API, número +55 11 95502-6224), responde em PT, EN, ES, AR, HI, RU e DE, qualifica o lead e transfere para humano em pagamento/reembolso/cancelamento/emergência. Por isso o teste não precisa ficar no Brasil: o atendimento multilíngue existe, então o que falta descobrir é **em que mercado o lead qualificado custa menos**.

## Decisão de 05/10/2026 — Facebook primeiro, WhatsApp em stand-by

Enquanto a Huda não volta, os anúncios da validação usam **Click-to-Messenger** na página Dubai Explore e quem responde é o **consultor do cérebro** (canal `messenger`, webhook `/webhooks/meta`, persona do mercado detectado pelo Jev, apresentando-se pela High Class). Regras na migração 008. Vantagens: zero dependência da Cloudfy, nenhum risco de banimento de número, e a máquina mede tudo nativamente (lead, Jev fit, cotação). Custo: Messenger converte um pouco pior que WhatsApp em BR/IN; aceitável para um radar. Quando a Huda voltar, troca-se a regra e o destino volta ao WhatsApp. Leia a seção 0 só como pendência, não como bloqueio.

## 0. Pendência: a Huda está fora do ar

O inventário da Huda de 04/10 (12h25 UTC) mostra: site 200, webhook 401 (ok), mas **Evolution API e painel da instância na Cloudfy respondendo 404**. Última mensagem recebida 30/09, última enviada 25/09. Ou seja, hoje um anúncio Click-to-WhatsApp mandaria gente para um número que não responde.

Antes de qualquer real: (1) entrar na Cloudfy e ver se a instância `high-class-dubai` foi suspensa, movida ou apagada; (2) recuperar a mesma sessão (não ligar a contingência em paralelo); (3) testar de outro número: texto, áudio e um handoff; (4) conferir no aparelho se contatos em modo `human` escreveram enquanto o gateway esteve fora. A regra `service` da migração 007 proíbe o Paid Media de ativar campanha com destino WhatsApp enquanto isso não estiver resolvido.

Dois riscos estruturais para decidir com a Larissa, não urgentes mas reais: a Huda usa Evolution/Baileys (WhatsApp Web não oficial) — sob volume de anúncios o risco de banimento do número sobe, e a Meta só liga Click-to-WhatsApp a um número de WhatsApp Business vinculado à página/portfólio; e o número é +55, o que para indiano, russo ou saudita parece estranho (funciona, mas custa confiança). O caminho de médio prazo é migrar a Huda para a Cloud API oficial com número +971 — a máquina já tem esse canal pronto (`/webhooks/whatsapp`).

## 1. Integração Huda → cérebro (um webhook, lado Manus)

A Huda continua sendo a voz; o cérebro recebe os dados para medir e operar. O lado Manus faz `POST https://brain.highclass.you/webhooks/huda` com header `X-Huda-Token: <HUDA_WEBHOOK_SECRET>` em dois momentos: ao atualizar o perfil do lead (`event: lead_updated`) e ao transferir (`event: handoff`). Payload documentado em `brain/channels/huda.py` (telefone, nome, e-mail, idioma, país de residência, destino, pax, datas, `stage`, `summary`, `referral` do Click-to-WhatsApp quando a Evolution entregar).

O que o cérebro faz com isso: cria/atualiza o lead no CRM com `market_code` deduzido do país/idioma e `utm.attended_by='huda'`; o Jev dá `jev_fit` e segmento (mesma régua dos experimentos); em `handoff`, `booking_payments.handle_huda_handoff` prepara o caso (reserva, política de reembolso, briefing de 5 linhas) e escala ao humano no Chatwoot — sem escrever ao cliente, porque a Huda já avisou. A view `v_leads_by_attendant` cruza leads × mercado × campanha para o Analista.

Segredo: `openssl rand -hex 24` → mesmo valor no cofre do WebDev e em `HUDA_WEBHOOK_SECRET` no `.env` da VM → `make restart`.

## 2. Antes do primeiro real gasto (1–2 dias, humano no painel da Meta)

| Item | Onde | Observação |
| --- | --- | --- |
| Capa + foto + bio EN com tradução PT/AR/RU/HI/DE | Página → Editar | base EN: "Dubai beyond the skyline — places, backstage and what nobody tells you. Content by High Class Travel Experiences · DET licence 781806." |
| Site | Editar detalhes | `https://highclass.you` (o site já escolhe o idioma) |
| Botão de ação | Adicionar botão | **Enviar mensagem** (Messenger) enquanto o WhatsApp estiver em stand-by |
| Categoria | Editar detalhes | manter *Tourist Information Center*; **não** mudar para Travel Agency (a agência é a High Class) |
| 6–8 posts orgânicos | Gestor Social (`campaign_social`) | mídia EN com legendas localizadas; 2 dias de feed antes do anúncio |
| Business Portfolio | business.facebook.com | página, conta de anúncios, WhatsApp Business (número da Huda) e pixel **no mesmo portfólio** da High Class |
| Verificação da empresa | Portfolio → Segurança | documentos da High Class Experiences Travel LLC; destrava limites e Click-to-WhatsApp |
| Pixel + Conversions API | Gerenciador de Eventos | `META_PIXEL_ID`; evento *Lead* disparado pelo cérebro quando o lead da Huda vira `qualified` |
| Token de sistema | Portfolio → Usuários do sistema | `pages_manage_posts, pages_read_engagement, ads_read, ads_management` → `FB_DUBAIEXPLORE_TOKEN`, `META_ADS_ACCESS_TOKEN`, `META_ADS_ACCOUNT_ID` |

## 3. Camada 1 — radar (dias 1–7, 7 mercados, USD 280)

Um criativo universal (Reels 15 s sem fala + imagem única; visual forte, pouco texto), legenda e texto primário no idioma do mercado, objetivo mensagens (Click-to-Messenger enquanto o WhatsApp estiver em stand-by), ~USD 40 por mercado (USD 5–6/dia). Um experimento por mercado: `RADAR-BR`, `RADAR-IN`, `RADAR-RU`, `RADAR-GB`, `RADAR-DE`, `RADAR-SA`, `RADAR-US`.

| Mercado | Público (Meta) | Idioma | O que esperar (hipótese do playbook) |
| --- | --- | --- | --- |
| BR | 28–55, SP/RJ/BH/CWB/POA, Emirates/Dubai/luxo | PT-BR | CPM baixo, CTR alto, muita conversa; qualidade média |
| IN | 25–45, Mumbai/Delhi/Bangalore/Hyderabad, lua de mel/família | EN-IN + HI | CPM muito baixo, volume alto; fit varia muito — o Jev é essencial |
| RU | 28–55, Moscou/SPb + Almaty | RU | alcance limitado na Meta; serve só de sinal, camada 2 iria para Yandex/VK/Telegram |
| GB | 30–60, Londres/Manchester/Birmingham, "dubai holidays" | EN-GB | CPM alto, CTR médio, ticket alto |
| DE | 30–60, Munique/Frankfurt/Hamburgo/Zurique/Viena | DE | CPM alto, conversa lenta, decisão longa |
| SA/GCC | 28–55 famílias, Riade/Jeddah/Dammam/Kuwait/Doha | AR | CPM médio, forte em família e vídeo; camada 2 pode ir para Snapchat/TikTok |
| US | 30–60, NY/LA/Miami/Houston, viagem internacional | EN-US | CPM mais alto de todos; sinal de ticket, não de volume |

Métrica do radar: **custo por lead qualificado** = gasto ÷ leads com `jev_fit ≥ 0,6` que responderam à 2ª mensagem da Huda. Secundárias: CPM, CTR, custo por conversa iniciada, idioma real das conversas (a Huda detecta). Regra de kill no radar: nenhuma — USD 40 é o mínimo de julgamento; o que se corta é no dia 8.

## 4. Camada 2 — conversão (dias 8–21, 2 mercados, USD 240)

No dia 8 o Analista roda `experiment_results` dos 7, ordena por custo por lead qualificado e propõe 2 experimentos de **oferta concreta** nos 2 melhores (USD 120 cada, 14 dias): "Dubai <segmento vencedor do Jev> 5 noites a partir de USD X pp, sem aéreo — o que inclui", 2 criativos por mercado, Click-to-WhatsApp, kill CPL > 2× alvo após USD 40. Os outros 5 mercados viram `inconclusive` com aprendizado registrado (CPM, CTR, custo por conversa) e seguem só com orgânico até a rodada seguinte.

Veredito pelo Jev na terça 10:00; vencedor escala +30%/semana enquanto CPL ≤ alvo (`cpl_target` por mercado em `config/budgets.yaml`); o Auditor confere o fluxo. Total da validação: **USD 520 em 21 dias**. Tudo dentro de `media.experiments`, exceto o teto diário de mídia, que hoje é zero e precisa de uma frase da CEO no chat: *"libere USD 40/dia para a validação da Dubai Explore nos 7 mercados"*.

## 5. Como disparar (chat do dashboard)

1. *"Analista de mercado: registre os 7 experimentos RADAR da Dubai Explore conforme docs/VALIDACAO_ANUNCIOS_DUBAI_EXPLORE.md"* → `propose_experiment` × 7.
2. *"Marketing: criativo universal + legendas nos 7 idiomas para o radar da Dubai Explore"* → `content_studio.campaign_brief` + `social_manager.campaign_social`.
3. *"Marketing: pacote social de aquecimento da Dubai Explore, multilíngue"* → 6–8 posts para você publicar até o token existir.
4. Dia 8: *"Analista de mercado: feche o radar e proponha a camada 2"*.

## 6. Limites que não mudam

Sem promessa de visto, sem "garantido", preço sempre "a partir de" com o que inclui, identificação da High Class e da licença em todo anúncio em qualquer idioma, nenhum dado de cliente em criativo, pausa imediata se o Compliance reprovar ou se a Huda cair. Segmentação nunca por religião, saúde ou etnia. RU: rotulagem "Реклама" + ERID em qualquer post pago em canal de terceiros.
