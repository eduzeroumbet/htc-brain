# Capturas de tela do teste de entrega

Coloque aqui a captura de cada mensagem recebida, tirada no celular de teste. O nome do arquivo é
`<MERCADO>_<4 últimos dígitos>_<tipo>.<png|jpg|jpeg|webp|heic|pdf>`. Exemplos:

- `IN_3210_template_utility.png`: template recebido no número indiano terminado em 3210
- `IN_3210_livre.png`: mensagem livre no mesmo número
- `GB_0123_livre.jpg`

O `atualizar` mostra o nome esperado de cada linha que ainda está sem captura. Depois de copiar os arquivos, rode:

    python -m scripts.teste_entrega.atualizar

A coluna `captura` da planilha passa a mostrar o caminho (`capturas/IN_3210_template_utility.png`).

Os arquivos desta pasta não vão para o git, porque as capturas mostram o número inteiro. Para entregar, anexe a
planilha junto com esta pasta, compactada.
