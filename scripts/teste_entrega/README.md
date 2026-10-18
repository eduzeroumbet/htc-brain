# Teste de entrega por mercado (WhatsApp Cloud API)

Envia, do +971 58 515 3946, **1 template utility e 1 mensagem livre** para cada um dos **4 números de teste**
(IN, GB, SA e DE). Mede a latência da API, guarda o wamid, o status e o código de erro e gera a planilha de
resultados em CSV e xlsx. O padrão é **dry-run**: nada sai sem `--enviar`.

| Arquivo | Para quê |
|---|---|
| `enviar.py` | dry-run (padrão) ou envio real com `--enviar` |
| `atualizar.py` | completa a planilha com os webhooks de status e as capturas |
| `nucleo.py` | regras: números, mercado, máscara, payloads, latência, erros da Meta |
| `planilha.py` | grava CSV e xlsx |
| `numeros.exemplo.json` | modelo do `numeros.json` (o real fica fora do git) |
| `capturas/` | capturas de tela (fora do git), ver `capturas/LEIA-ME.md` |
| `resultados/` | planilhas geradas (fora do git) |

## Travas

- Os números vêm só do `numeros.json`. Não há como passar um número pela linha de comando que não esteja no arquivo
  (`--so` aceita apenas números do arquivo).
- O arquivo aceita no máximo 4 números. Com menos de 4 (no arquivo ou via `--so`), o script recusa, a não ser com
  `--parcial`.
- Cada número precisa estar em E.164, sem repetição, e o mercado declarado tem que bater com o prefixo. O próprio
  +971 58 515 3946 é recusado como destino.
- O envio real exige `WA_ACCESS_TOKEN`, `WA_PHONE_NUMBER_ID` e `WA_BUSINESS_ACCOUNT_ID` no ambiente. O token nunca
  é impresso.
- Antes de enviar, o script lê na Meta (só GET) se o template existe no idioma pedido, está `APPROVED` e é `UTILITY`.
  Se não estiver, recusa. Também mostra a qualidade do número e avisa se o `health_status` estiver `BLOCKED`.
- Os textos não podem dizer que quem escreve é IA ou bot. A Huda não se apresenta como IA, e o script recusa um
  texto ou parâmetro que diga isso.
- Na planilha e no terminal o número aparece mascarado (`+91*****3210`).

## Colunas da planilha

`mercado, numero_mascarado, tipo, template, wamid, status, enviado_em, entregue_em, latencia_ms, codigo_erro,
mensagem_erro, captura, observacoes`

- `latencia_ms`: ms entre a requisição e a resposta da Graph API.
- A latência até a entrega (de `enviado_em` a `entregue_em`) vai em `observacoes` depois do `atualizar`. O webhook
  da Meta tem precisão de 1 s.
- `status`: `dry_run`, `accepted` (aceito pela API), depois `sent`, `delivered`, `read` ou `failed`.
- `mensagem_erro`: o significado do código em português e a mensagem da Meta. Códigos mapeados: 130497, 131047,
  131026, 131049, 131056, 131042, 132000, 132001, 132012, 132015, 132016, 190, entre outros (`nucleo.ERROS_META`).

## Passo a passo

### 0. Ambiente (na sua máquina, fora do container)

```bash
python3.12 -m venv /tmp/htc-teste && . /tmp/htc-teste/bin/activate
pip install -e '.[dev]'
cp scripts/teste_entrega/numeros.exemplo.json scripts/teste_entrega/numeros.json   # e preencha
```

Rode na raiz do repositório. Não rode dentro da imagem: o Dockerfile copia `scripts/` inteiro, e o `numeros.json`
iria junto para a imagem.

### 1. Dry-run (padrão, nada é enviado)

```bash
python -m scripts.teste_entrega.enviar --template NOME_DO_TEMPLATE --idioma en
```

Valida os números, monta e confere os 8 payloads, mostra cada um com o número mascarado e grava
`resultados/dry_run_<data-hora>.csv/.xlsx`. Para conferir também o template e o número na Meta, só com leituras:

```bash
export $(grep -E '^WA_(ACCESS_TOKEN|PHONE_NUMBER_ID|BUSINESS_ACCOUNT_ID)=' .env | cut -d' ' -f1 | xargs)
python -m scripts.teste_entrega.enviar --template NOME_DO_TEMPLATE --idioma en --verificar-meta
```

Se o template tiver variáveis no corpo, passe uma `--parametro "texto"` para cada, na ordem.

### 2. Abrir a janela de 24h (para a mensagem livre)

A mensagem livre só é entregue se o número de teste escreveu para o +971 58 515 3946 nas últimas 24h. Peça a
cada pessoa que mande um "oi" e marque `"janela_24h": true` no `numeros.json`. Sem isso o script avisa antes, e a
Meta devolve **131047**, que fica registrado na planilha (o que também é um resultado).

### 3. Envio real

```bash
python -m scripts.teste_entrega.enviar --template NOME_DO_TEMPLATE --idioma en --enviar
```

Para cada número vão o template e, 7 s depois, a mensagem livre (`--intervalo` muda a espera; serve para evitar o
131056). Resultado em `resultados/resultados_<data-hora>.csv/.xlsx`.

Para repetir só a mensagem livre de um número depois de abrir a janela:

```bash
python -m scripts.teste_entrega.enviar --tipos livre --so "+44 7700 900123" --parcial --enviar
```

### 4. Status dos webhooks

A Meta manda `sent`, `delivered`, `read` e `failed` para `POST /webhooks/whatsapp` do cérebro, que registra no log
(`wa_status`, e `wa_delivery_failed` com o código de erro). Junte os status num arquivo e rode o `atualizar`:

```bash
docker compose logs brain --no-log-prefix --since 2h | grep -E 'wa_status|wa_delivery_failed' > /tmp/status.log
python -m scripts.teste_entrega.atualizar --webhooks /tmp/status.log
```

Também aceita o JSON bruto do webhook da Meta (um por linha ou lista), por exemplo copiado do painel de webhooks do
app. O cruzamento é pelo wamid. Sem `--planilha`, usa a `resultados_*.csv` mais recente. Pode rodar quantas vezes
quiser, porque o status só avança (um `delivered` atrasado não desfaz um `read`).

### 5. Capturas

Tire uma captura de cada mensagem no celular de teste e salve em `capturas/` com o nome
`<MERCADO>_<4 últimos>_<tipo>.png` (ex.: `IN_3210_template_utility.png`). Rode `atualizar` de novo: a coluna
`captura` é preenchida e a saída lista o que ainda falta. Detalhes em `capturas/LEIA-ME.md`.

## Testes

```bash
ruff check scripts/teste_entrega tests/teste_entrega
pytest tests/teste_entrega -q
```

Os testes não usam rede: a Graph é simulada com `httpx.MockTransport` e um teste confirma que o dry-run não faz
nenhuma chamada.
