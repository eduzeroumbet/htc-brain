# Escalonamento humano — quando a IA para e uma pessoa entra

A regra é simples: **a IA resolve tudo, exceto seis situações.** Elas estão codificadas em `config/escalation.yaml` e avaliadas pelo Roteador (Haiku) em toda mensagem, antes do consultor responder. Meta: menos de 4% das conversas.

| # | Gatilho | Como é detectado | Severidade / SLA | Quem | Aviso ao CEO |
| --- | --- | --- | --- | --- | --- |
| 1 | Emergência em viagem | palavras de saúde/acidente/polícia/documento em 6 idiomas; cliente em viagem sem resposta do fornecedor por 30 min | crítica / imediato | CEO ou plantão | WhatsApp + ligação |
| 2 | Pagamento ou reembolso acima do limite | reserva ≥ USD 5.000; reembolso > USD 500; chargeback | alta / 2h | CEO | WhatsApp |
| 3 | Reclamação grave | 2 mensagens negativas seguidas (sentimento ≤ −0,6); ameaça de denúncia/avaliação pública; palavras-chave | alta / 1h | CEO | WhatsApp |
| 4 | Pedido explícito de humano | "quero falar com uma pessoa" em 6 idiomas; mesma pergunta 3 vezes | média / 4h (horário comercial) | CEO ou atendente | não |
| 5 | Risco de compliance | visto de trabalho, "visto garantido", menor desacompanhado, atividade proibida, dado sensível não solicitado (cartão, passaporte, saúde) | alta / 4h | Compliance humano | WhatsApp |
| 6 | Incerteza do modelo | preço/disponibilidade fora do catálogo; fornecedor sem resposta por 4h; confiança < 0,6 em preço/política; pergunta de política não coberta | média / 4h | CEO | não |

## O que acontece no handoff

1. O consultor envia a **mensagem-ponte** do gatilho (definida no YAML: curta, no idioma do cliente, com prazo).
2. `escalate_to_human` abre a conversa no **Chatwoot** (inbox "Humanos") com: perfil do lead, últimas 10 mensagens, cotações/reservas abertas, resumo e **ação sugerida** — tudo em português.
3. A conversa muda para `status = 'human'`. A IA continua respondendo perguntas simples (horário, endereço), mas fica **muda em preço, reembolso e reclamação** até o humano resolver.
4. Se `notify_ceo`, o CEO-agente manda o alerta no WhatsApp do CEO (e, em emergência, liga).
5. O humano resolve no Chatwoot (celular) e marca resolvido no dashboard ou no próprio Chatwoot → a conversa volta para a IA e o motivo/resultado ficam registrados em `escalations`.

## Ajustando

- Escalonamento acima de 8%? Provavelmente palavras-chave amplas demais (ex.: "polícia" em uma pergunta sobre segurança). Restrinja no YAML ou mova para `intent == emergency` apenas.
- Abaixo de 1% com reclamações chegando por fora? Baixe o limiar de sentimento para −0,5 ou adicione palavras do mercado.
- Toda mudança no YAML exige `make restart` e observação de 24h; o QA reporta a taxa diária.


## Triagem pelo Jev (desde out/2026)

A primeira leitura de toda mensagem é do Jev (`brain/core/jev.py → triage`), em < 0,5 s: mercado, intenção, urgência, sentimento e as probabilidades `escalate_emergency`, `escalate_human`, `severe_complaint`, `compliance_risk`, `prompt_injection`, `vip_signal`. Limiares em `brain/agents/escalation_router.py`. Palavras-chave de `config/escalation.yaml` continuam valendo como rede de segurança; o Haiku só entra se o Jev não responder. Problemas operacionais (ingresso, hotel, transfer) não são escalonamento: viram `issues` do Operacional e, quando exigem presença física, programação para o pessoal de resolução (`assign_issue_to_staff`).
