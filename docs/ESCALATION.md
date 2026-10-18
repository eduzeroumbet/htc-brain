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


## Transbordo para humano: alerta à equipe, SLA e Camada 0

Além dos casos acima, cinco gatilhos abrem um evento de transbordo em `handoff_events` (`brain/core/handoff.py`) e avisam a equipe:

| Gatilho | Palavra-chave (pt, en, es, ar) | Modelo (triagem) | SLA (`config/handoff.yaml`) |
| --- | --- | --- | --- |
| Pedido de humano | "falar com um atendente", "talk to a human", "hablar con una persona", "خدمة العملاء"… | `escalate_human` ≥ 0,5 ou intenção `human_request` | 4 h |
| Proposta / orçamento | "orçamento", "quote", "presupuesto", "عرض سعر"… | intenção `quote_request` (obrigatória) | 30 min |
| Pagamento | "link de pagamento", "payment", "pagar", "الدفع"… | intenção `payment`/`refund` (obrigatória) | 2 h |
| Reclamação | "reclamação", "complaint", "queja", "شكوى"… | intenção `complaint` com sentimento ≤ −0,6 ou `severe_complaint` ≥ 0,5 | 1 h |
| Dados pessoais (DSAR) | acesso, exclusão ou revogação: "excluir meus dados", "withdraw my consent", "acceso a mis datos", "حذف بياناتي"… | `data_request` ≥ 0,7 | 15 dias |

- Proposta e pagamento são o fluxo normal de venda: a palavra sozinha não abre transbordo, só com o modelo confirmando a intenção.
- Descadastro simples (PARAR, STOP…) continua só no `consent_log`, sem acordar a equipe.
- **Deduplicação:** um evento por conversa e gatilho enquanto estiver na fila; mensagens repetidas só somam `occurrence_count`.
- **Alerta em até 1 minuto:** envio na hora, em segundo plano (não segura a resposta ao cliente), e varredura a cada 60 s para o que falhou. Canal e destinatários em `HANDOFF_ALERT_*`; se o canal principal falhar, o outro entra. Falha de envio nunca derruba o atendimento: fica em `last_alert_error` e aparece como "pendente" na Camada 0.
- **SLA vencido:** o relógio começa na detecção e não pausa; vencido sem humano, o evento vira `breached` e sai um alerta de escalonamento para `HANDOFF_ESCALATION_*` (uma vez).
- **Atendido:** primeira mensagem de humano (`author = 'human:<nome>'`) na conversa, botão **Assumir** na Camada 0 (`POST /api/handoffs/{id}/attend`) ou caso resolvido no painel.
- **Ao cliente:** no máximo um aviso neutro de que a equipe vai assumir (texto de referência por idioma em `config/handoff.yaml`), sem prazo novo.
- **Camada 0** (`GET /api/dashboard/layer0`, primeiro bloco do painel): fila aberta, maior espera, tempo médio, % dentro do SLA em 24 h e 7 dias. Tempo de espera = `coalesce(attended_at, agora) − created_at`; o % conta atendidos e os que já venceram na fila.

## Triagem pelo Jev (desde out/2026)

A primeira leitura de toda mensagem é do Jev (`brain/core/jev.py → triage`), em < 0,5 s: mercado, intenção, urgência, sentimento e as probabilidades `escalate_emergency`, `escalate_human`, `severe_complaint`, `compliance_risk`, `prompt_injection`, `vip_signal`. Limiares em `brain/agents/escalation_router.py`. Palavras-chave de `config/escalation.yaml` continuam valendo como rede de segurança; o Haiku só entra se o Jev não responder. Problemas operacionais (ingresso, hotel, transfer) não são escalonamento: viram `issues` do Operacional e, quando exigem presença física, programação para o pessoal de resolução (`assign_issue_to_staff`).
