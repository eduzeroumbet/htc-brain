# highclass.you — integração do site com a máquina (resumo técnico)

Documento completo (auditoria, inventário, sitemap, textos por página, conversão, SEO, legal, backlog):
**https://claude.ai/code/artifact/f44e9e3a-38d9-48e8-a781-b27d7fbd3a52**

## Estado em 22/09/2026

Next.js no Manus, servido em highclass.you, PT/EN/ES/AR. Problemas que bloqueiam conversão e SEO:
placeholders `[[...]]` visíveis; botões de WhatsApp apontando para /contato; formulários com `method=GET`
sem backend; canonical/hreflang/sitemap/JSON-LD apontando para `*.manus.space`; sem GA4/pixels.

## O que o site passa a chamar na máquina

| Uso no site | Endpoint do cérebro | Observação |
| --- | --- | --- |
| Chat do consultor (botão flutuante) | `POST /webhooks/webchat` + `GET /webchat/stream/{session_id}` (SSE) | Snippet em `brain/channels/webchat.py`; `market` = pt→BR, en→GB (com escolha IN/US), ar→SA, es→BR |
| Formulários de contato e empresarial | `POST /webhooks/webchat` com `{session_id, text, market, page, name, email}` | O consultor responde na tela em segundos; lead criado com `source_campaign` da UTM |
| Bloco "Dubai em 2026" na home | `GET /public/dubai-now.json` (sem auth, CORS aberto, cache 1 h) | Alimentado pelo Market Intel (topic `dubai_now`) |
| Botões de WhatsApp | `https://wa.me/<número da Cloud API>?text=<mensagem por página>&utm_...` | Mesmo número dos anúncios click-to-WhatsApp |
| "Personalizar este roteiro" / "Incluir no meu roteiro" | chat com `?itinerary=<slug>` ou `?items=<skus>` | O consultor recebe o contexto na primeira mensagem |

## Onda 1 (esta semana) — checklist

- [ ] Preencher marcadores: 2010 · High Class Experiences Travel LLC · licença 781806 · IATA 96029802 · e-mail e WhatsApp públicos · equipe (ou remover seção)
- [ ] WhatsApp → `wa.me` em todos os botões, com texto por página e UTM
- [ ] Formulários → `POST` para o cérebro; mensagem de sucesso com a primeira resposta do consultor
- [ ] Base URL pública no builder: canonical, hreflang (x-default = EN), sitemap, og:image, JSON-LD
- [ ] GA4 + Google Ads + Meta Pixel (+ TikTok/Snap para SA, Yandex para RU) via gerenciador de tags com consentimento
- [ ] Search Console + Bing no domínio público; reenviar sitemap
- [ ] Corrigir links de Experiências (Abu Dhabi, Eventos e camarotes) e a tabela de feiras em /negocios
- [ ] Rodapé de confiança: razão social, licença, IATA, endereço, telefone, e-mail, horário 24/7
- [ ] Confirmar ou remover a certificação Fifty Shades Greener

## Ondas 2–4

Ver o doc: completar a oferta (frota, durações, hotéis por perfil, voos, vistos/seguro/eSIM, serviços especiais,
6 roteiros "a partir de", legal PDPL/LGPD, cancelamento, cookies), destinos e catálogo de 49 experiências,
avaliações, idiomas HI/RU/DE e artigos por mercado. O Content Studio gera os textos a partir do doc; o
Compliance revisa; o SEO & Site acompanha semanalmente.
