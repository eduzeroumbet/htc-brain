# Descadastro fora da lista de termos no WhatsApp

Data: 18/10/2026 · Estado: decidido, implementado em branch própria (sem merge na main).
Código: `brain/core/descadastro.py` (classificador), `config/descadastro.yaml` (lista por idioma),
`brain/core/consent.py` (suspensão, retomada, tarefa humana), `brain/core/orchestrator.py` (`_handle_consent`),
`db/migrations/013_descadastro_fora_da_lista.sql`.

## Contexto

O entregável anterior criou o `consent_log`, a guarda única de marketing (`consent.pode_enviar_marketing`, chamada em
`channels.dispatch`) e a revogação imediata por seis termos: PARAR, STOP, SAIR, UNSUBSCRIBE, ألغِ e रोकें. Esta decisão trata do
que o cliente escreve fora desses seis termos.

## Três classes

| Classe | Quando | O que acontece |
| --- | --- | --- |
| **lista** | A mensagem inteira é termo da lista (os seis originais + a lista ampliada), com ou sem cortesia e pontuação, **sem "?"** | Revoga na hora e confirma no idioma do cliente (comportamento atual). |
| **ambiguo** | Termo da lista com "?" (`parar?`, `STOP please?`); termo ambíguo (`chega`, `basta`, `بس`, `बस`, `хватит`, `genug`); termo seguido de número (`ألغ ١`); pedido claro em forma de pergunta sem marcador de pedido educado (`parar de mandar mensagem?`) | Suspende o marketing na hora, envia **uma** pergunta de confirmação e só revoga com "sim". |
| **claro** | Frase de descadastro fora da lista, ou pedido de parar + objeto (mensagens, ofertas, promoções...) a até 6 palavras, em qualquer ordem; pergunta educada com objeto (`could you stop sending me offers?`) | Suspende o marketing, avisa o cliente que pausou e que a equipe vai confirmar, e abre tarefa humana (`consent_review`). **Não revoga sozinho.** |

Antes de tudo, a **negação** dentro da mesma oração anula o pedido (`não pare de me mandar as fotos`, `don't stop`,
`Hör nicht auf`, `stop mat karo`): nenhuma ação. A vírgula separa orações: `não, pare de me mandar mensagens` é pedido claro.

## Decisão dos dois casos do critério de pronto

| Mensagem | Classe | Revoga? | Alerta humano? | Fica como está? | Motivo |
| --- | --- | --- | --- | --- | --- |
| `parar de mandar mensagem` | claro | **Não** | **Sim**, tarefa `consent_review` aberta na hora | **Não**: marketing suspenso na hora; o cliente recebe aviso de pausa | O pedido é inequívoco, mas não é termo curto da lista. A guarda já bloqueia todo marketing, então não há risco de envio indevido; a revogação definitiva fica com uma pessoa, que confirma e registra. Reclassificar como revogação direta só com registro novo de decisão. |
| `STOP please?` | ambiguo | **Não** (só com "sim") | **Não** por padrão; só se não houver resposta em 7 dias ou se vier depois um pedido claro | **Não**: marketing suspenso na hora; o cliente recebe uma pergunta de confirmação | "please" é cortesia e não anula o descadastro, mas o "?" pode indicar pergunta ("STOP? o que é isso?"). Suspender e perguntar protege o cliente e não cala uma venda por engano. |

**Cortesia não anula o descadastro**: `STOP please`, `PARAR por favor`, `UNSUBSCRIBE obrigado`, `abbestellen danke`,
`стоп пожалуйста` são classe **lista** e revogam. O que muda a classe é o "?" (em qualquer escrita: `?`, `？`, `؟`, `¿`).

## Resposta à pergunta (caso ambíguo)

| Resposta | Ação |
| --- | --- |
| "sim" (`sim`, `yes`, `نعم`, `हाँ`, `да`, `ja`... até 6 palavras, a expressão abre a mensagem) | Revoga (`origem whatsapp_confirmacao`, classe `ambiguo`, `reply_text` guardado) e confirma o descadastro. |
| "não" (`não`, `no`, `لا`, `नहीं`, `нет`, `nein`...) | Encerra a suspensão (`lifted`) e o estado volta ao de antes: com consentimento ativo o marketing volta; sem consentimento continua bloqueado. Responde "mantivemos tudo como estava". |
| Silêncio | Marketing segue suspenso. Passados **7 dias** (`prazo_confirmacao_dias` no YAML), o job horário `consent.vencer_confirmacoes` abre uma tarefa humana; depois disso "sim"/"não" soltos não valem mais. |
| Termo da lista | Revoga. |
| Nova mensagem ambígua | Nada novo: sem segunda pergunta. |
| Pedido claro | Abre a tarefa humana (uma só), sem nova mensagem. |
| Qualquer outra mensagem | Segue para o consultor normalmente; marketing continua suspenso. |

## Registro e guarda

- A suspensão é uma linha `status = 'suspended'` no `consent_log`, com `source = 'whatsapp_fora_da_lista'`, `detection_class`
  (`lista`, `ambiguo`, `claro`), `awaiting_until` (prazo da pergunta), `escalation_id` (tarefa humana), `reply_text` e `lifted_at`.
- A guarda continua a mesma: estado vigente = linha mais recente que não é `lifted`; só `active` libera marketing. Suspensão bloqueia
  follow-up, campanha e template de marketing; mensagens de reserva, pagamento e viagem continuam.
- Idempotência: no máximo uma suspensão aberta por lead/canal (índice único), uma pergunta e uma tarefa humana por suspensão.
- Revogar com suspensão aberta revoga a suspensão e o consentimento ativo por baixo dela, para um novo opt-in futuro funcionar.
- A pessoa que atende a tarefa decide: revogar (`consent.revogar_marketing`, origem `revisao_humana`) ou retomar
  (`consent.retomar_marketing`).

## Normalização

NFKC, minúsculas, sem pontuação e emoji, sem caracteres invisíveis (ZWJ, marca RTL), dígitos árabes e devanágari → 0-9,
3 ou mais letras iguais → 1 (`stooop` → `stop`; `stoop` fica). Diacríticos: o entregável anterior já removia acentos latinos,
tashkeel árabe e matras do devanágari; mantivemos, porque a lista e a mensagem passam pela mesma normalização e isso é o que faz
`ألغِ`, `ألغ` e `الغ` baterem.

## Desvios em relação à proposta da etapa 3 (e motivo)

| Item | Proposta | Implementado | Motivo |
| --- | --- | --- | --- |
| `cancela` / `cancelar` / `cancel` sozinhos | lista (revoga) | ambiguo | Numa agência, "cancela" sozinho costuma ser a reserva. Revogar e ainda tirar a mensagem do consultor seria pior do que perguntar. |
| `لا ترسل` sozinho | lista | ambiguo | Sem objeto, pode ser "não mande [a cotação]". Com objeto (`لا ترسل لي رسائل`) é claro. |
| `ألغ ١` (termo + número) | lista | ambiguo | Número muda o sentido em outras línguas (`sair 9`). Na dúvida, suspende e pergunta. |
| Negação `não para` / `never stop` | negativo | fora da lista de negação | "não para de chegar mensagem" e "you never stop sending" são reclamações, não negação do pedido. |

## Lista ampliada e revisão

A lista por idioma (pt, en, ar, hi em devanágari e hinglish, ru, de) fica em `config/descadastro.yaml`, separada do código, com
termos de lista, ambíguos, frases, pedidos + objetos, negações e marcadores de pedido educado. Os seis termos originais ficam no
código e continuam revogando mesmo que alguém os apague do YAML. Mudança no YAML exige reiniciar o cérebro (`make restart`).

**Antes de produção**, os termos e textos em árabe, hindi e russo precisam de revisão por falante nativo
(`revisao_nativa_pendente` no YAML). Os textos ao cliente não dizem que quem atende é IA.

## Testes

```
pip install -e '.[dev]'
pytest tests/test_descadastro.py tests/test_consent.py          # sem banco
HTC_TEST_DATABASE_URL=postgresql://postgres:test@localhost:55432/postgres pytest tests/test_consent_db.py   # Postgres descartável
ruff check brain tests && python -m scripts.check
```
