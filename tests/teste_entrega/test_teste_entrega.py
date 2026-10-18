"""Teste de entrega por mercado (scripts/teste_entrega): latência, erros da Meta, máscara, travas e planilha.

Tudo simulado: a Graph é um httpx.MockTransport. Nenhuma mensagem real sai daqui. Os números são fictícios.
"""
from __future__ import annotations

import csv
import json
import zipfile
from pathlib import Path
from typing import Any

import httpx
import pytest

from scripts.teste_entrega import atualizar, enviar, planilha
from scripts.teste_entrega import nucleo as n

IN, GB, SA, DE = "+91 98765 43210", "+44 7700 900123", "+966 50 123 4567", "+49 151 12345678"
ENV = {"WA_ACCESS_TOKEN": "token-de-teste", "WA_PHONE_NUMBER_ID": "111", "WA_BUSINESS_ACCOUNT_ID": "222"}


def numeros(tmp_path: Path, itens: list[tuple[str, str]] | None = None, janela: bool = True) -> Path:
    itens = itens if itens is not None else [(IN, "IN"), (GB, "GB"), (SA, "SA"), (DE, "DE")]
    p = tmp_path / "numeros.json"
    p.write_text(json.dumps({"numeros": [{"numero": num, "mercado": m, "janela_24h": janela} for num, m in itens]}))
    return p


class Graph:
    """Graph simulada: registra as chamadas e responde por rota."""

    def __init__(self, template_status: str = "APPROVED", livre_erro: int | None = None) -> None:
        self.calls: list[httpx.Request] = []
        self.template_status, self.livre_erro = template_status, livre_erro

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.calls.append(req)
        if req.method == "GET" and req.url.path.endswith("/message_templates"):
            return httpx.Response(200, json={"data": [{"name": "htc_teste", "language": "en",
                                                       "status": self.template_status, "category": "UTILITY"}]})
        if req.method == "GET":
            return httpx.Response(200, json={"display_phone_number": "+971 58 515 3946", "quality_rating": "GREEN",
                                             "health_status": {"can_send_message": "AVAILABLE"}})
        body = json.loads(req.content)
        if body["type"] == "text" and self.livre_erro:
            return httpx.Response(400, json={"error": {"code": self.livre_erro, "message": "Re-engagement message",
                                                       "error_data": {"details": f"to {body['to']}"}}})
        return httpx.Response(200, json={"messages": [{"id": f"wamid.{body['type']}.{body['to'][-4:]}",
                                                       "message_status": "accepted"}]})

    @property
    def posts(self) -> list[httpx.Request]:
        return [c for c in self.calls if c.method == "POST"]


@pytest.fixture
def resultados(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    pasta = tmp_path / "resultados"
    monkeypatch.setattr(planilha, "RESULTADOS", pasta)
    return pasta


async def rodar(argv: list[str], graph: Graph, env: dict[str, str] | None = None) -> int:
    a = enviar.parser().parse_args(argv)
    return await enviar.executar(a, env or {}, transport=httpx.MockTransport(graph))


def ler_csv(p: Path) -> list[dict[str, str]]:
    with p.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


# ───────────────────────── latência ─────────────────────────

def test_latencia_api_em_ms():
    assert n.latencia_ms(10.0, 10.25) == 250
    assert n.latencia_ms(5.0, 5.0) == 0
    with pytest.raises(ValueError):
        n.latencia_ms(2.0, 1.0)


def test_latencia_ate_webhook():
    assert n.ms_entre("2026-10-18T10:00:00.000Z", "2026-10-18T10:00:02.500Z") == 2500
    assert n.ms_entre("2026-10-18T10:00:00.400Z", n.de_unix("1792317600")) is not None
    # webhook tem precisão de 1 s: chegar "antes" do envio vira 0, nunca negativo
    assert n.ms_entre("2026-10-18T10:00:00.700Z", "2026-10-18T10:00:00.000Z") == 0
    assert n.ms_entre("", "2026-10-18T10:00:00.000Z") is None and n.ms_entre("x", None) is None


def test_de_unix_converte_timestamp_da_meta():
    assert n.de_unix("0") == "1970-01-01T00:00:00.000Z"
    assert n.de_unix(None) is None and n.de_unix("abc") is None


# ───────────────────────── mapeamento de erros ─────────────────────────

@pytest.mark.parametrize("codigo,trecho", [
    (130497, "Mercado restrito"), (131047, "Janela de 24h"), (131026, "não tem WhatsApp"),
    (131049, "engajamento"), (132000, "parâmetros"), (132001, "não existe"), ("131056", "mesmo destino"),
])
def test_codigos_conhecidos(codigo, trecho):
    assert trecho in n.descrever_erro(codigo)


def test_codigo_desconhecido_e_vazio():
    assert n.descrever_erro(999999).startswith("Código não mapeado")
    assert n.descrever_erro(None) == "" and n.descrever_erro("") == ""


def test_erro_da_resposta_sincrona_mascara_numero():
    corpo = {"error": {"code": 131047, "message": "Re-engagement message",
                       "error_data": {"details": "Message failed to send to +919876543210"}}}
    codigo, msg = n.erro_da_resposta(corpo)
    assert codigo == 131047
    assert msg.startswith("Janela de 24h fechada") and "Meta: Re-engagement message" in msg
    assert "9876543210" not in msg


def test_erro_de_status_do_webhook():
    assert n.erro_de_status([{"code": "131026", "title": "Message undeliverable"}])[0] == 131026
    assert n.erro_de_status([{"code": "x"}, {"code": 130497}])[0] == 130497
    assert n.erro_de_status(None) == (None, "")
    assert n.erro_da_resposta({"ok": True}) == (None, "")


# ───────────────────────── máscara e mercado ─────────────────────────

@pytest.mark.parametrize("numero,mascara,mercado", [
    (IN, "+91*****3210", "IN"), (GB, "+44*****0123", "GB"), (SA, "+966*****4567", "SA"),
    (DE, "+49*****5678", "DE"), ("971501234567", "+971*****4567", "AE"),
])
def test_mascara_e_mercado(numero, mascara, mercado):
    assert n.mascarar(numero) == mascara
    assert n.mercado(numero) == mercado


def test_mascara_nunca_mostra_numero_inteiro():
    assert n.mascarar("123") == "*****"
    assert "98765" not in n.mascarar(IN)


# ───────────────────────── travas (valem também no dry-run) ─────────────────────────

def test_arquivo_ausente_e_exemplo_sao_recusados(tmp_path):
    with pytest.raises(n.ErroConfig, match="numeros.exemplo.json"):
        n.ler_numeros(tmp_path / "numeros.json")
    with pytest.raises(n.ErroConfig, match="inválido"):
        n.ler_numeros(n.PASTA / "numeros.exemplo.json")


@pytest.mark.parametrize("itens,trecho", [
    ([(IN, "GB")], "prefixo é de IN"),
    ([("+971 58 515 3946", "AE")], "próprio número"),
    ([(IN, "IN"), ("+919876543210", "IN")], "repetido"),
    ([("+999 1234 5678", "XX")], "fora dos mercados"),
    ([(IN, "")], "informe o mercado"),
])
def test_numeros_invalidos_recusados(tmp_path, itens, trecho):
    with pytest.raises(n.ErroConfig, match=trecho):
        n.ler_numeros(numeros(tmp_path, itens))


def test_menos_de_quatro_so_com_parcial_e_nunca_mais_de_quatro(tmp_path):
    tres = n.ler_numeros(numeros(tmp_path, [(IN, "IN"), (GB, "GB"), (SA, "SA")]))
    with pytest.raises(n.ErroConfig, match="--parcial"):
        n.selecionar(tres)
    assert len(n.selecionar(tres, parcial=True)) == 3
    cinco = [*tres, n.Destino("4915112345678", "DE", True), n.Destino("447700900999", "GB", True)]
    with pytest.raises(n.ErroConfig, match="só com 4"):
        n.selecionar(cinco, parcial=True)


def test_so_aceita_apenas_numero_do_arquivo(tmp_path):
    quatro = n.ler_numeros(numeros(tmp_path))
    with pytest.raises(n.ErroConfig, match=r"fora do numeros.json: \+44\*\*\*\*\*9999"):
        n.selecionar(quatro, so=["+44 7700 909999"], parcial=True)
    with pytest.raises(n.ErroConfig, match="--parcial"):
        n.selecionar(quatro, so=[GB])
    assert [d.mercado for d in n.selecionar(quatro, so=[GB], parcial=True)] == ["GB"]


def test_texto_que_diz_ser_ia_e_recusado():
    assert n.validar_payload(n.payload_livre("447700900123", "Hi, I am Huda, an AI assistant"))
    assert n.validar_payload(n.payload_livre("447700900123", "Olá, sou um chatbot"))
    assert n.validar_payload(n.payload_livre("447700900123", n.TEXTO_LIVRE_PADRAO)) == []
    assert n.validar_payload(n.payload_template("447700900123", "Htc-Teste", "english"))
    assert n.validar_payload(n.payload_template("447700900123", "htc_teste", "en", ["linha\nquebrada"]))


async def test_dry_run_e_o_padrao_e_nao_chama_a_graph(tmp_path, resultados):
    g = Graph()
    rc = await rodar(["--template", "htc_teste", "--numeros", str(numeros(tmp_path))], g, ENV)
    assert rc == 0 and g.calls == []
    [arquivo] = resultados.glob("dry_run_*.csv")
    linhas = ler_csv(arquivo)
    assert len(linhas) == 8 and {r["status"] for r in linhas} == {"dry_run"}
    assert {r["tipo"] for r in linhas} == {n.TIPO_TEMPLATE, n.TIPO_LIVRE}
    texto = arquivo.read_text(encoding="utf-8-sig") + json.dumps(linhas)
    assert "98765" not in texto and "7700900" not in texto
    assert arquivo.with_suffix(".xlsx").exists()


async def test_dry_run_recusa_menos_de_quatro_sem_parcial(tmp_path, resultados, capsys):
    g = Graph()
    rc = await rodar(["--template", "htc_teste", "--numeros", str(numeros(tmp_path, [(IN, "IN")]))], g)
    assert rc == 2 and g.calls == [] and not resultados.exists()
    assert "--parcial" in capsys.readouterr().err


async def test_dry_run_recusa_numero_fora_do_arquivo(tmp_path, resultados):
    g = Graph()
    rc = await rodar(["--template", "htc_teste", "--numeros", str(numeros(tmp_path)),
                      "--so", "+44 7700 909999", "--parcial"], g)
    assert rc == 2 and g.calls == [] and not resultados.exists()


async def test_dry_run_recusa_texto_de_ia(tmp_path, resultados):
    g = Graph()
    rc = await rodar(["--template", "htc_teste", "--numeros", str(numeros(tmp_path)),
                      "--texto", "Hello, this is an AI assistant"], g)
    assert rc == 2 and g.calls == []


async def test_verificar_meta_no_dry_run_so_le(tmp_path, resultados):
    g = Graph()
    rc = await rodar(["--template", "htc_teste", "--numeros", str(numeros(tmp_path)), "--verificar-meta"], g, ENV)
    assert rc == 0 and g.calls and all(c.method == "GET" for c in g.calls)


async def test_enviar_sem_credenciais_recusa(tmp_path, resultados):
    g = Graph()
    rc = await rodar(["--template", "htc_teste", "--numeros", str(numeros(tmp_path)), "--enviar"], g, {})
    assert rc == 2 and g.calls == []


async def test_enviar_recusa_template_nao_aprovado(tmp_path, resultados):
    g = Graph(template_status="PENDING")
    rc = await rodar(["--template", "htc_teste", "--numeros", str(numeros(tmp_path)), "--enviar"], g, ENV)
    assert rc == 2 and g.posts == []


async def test_envio_simulado_registra_wamid_latencia_e_erro(tmp_path, resultados):
    g = Graph(livre_erro=131047)
    rc = await rodar(["--template", "htc_teste", "--numeros", str(numeros(tmp_path)), "--enviar",
                      "--intervalo", "0"], g, ENV)
    assert rc == 0 and len(g.posts) == 8
    assert all(c.headers["Authorization"] == "Bearer token-de-teste" for c in g.posts)
    [arquivo] = resultados.glob("resultados_*.csv")
    linhas = ler_csv(arquivo)
    tpl = [r for r in linhas if r["tipo"] == n.TIPO_TEMPLATE]
    livre = [r for r in linhas if r["tipo"] == n.TIPO_LIVRE]
    assert all(r["status"] == "accepted" and r["wamid"].startswith("wamid.template") for r in tpl)
    assert all(r["status"] == "failed" and r["codigo_erro"] == "131047" for r in livre)
    assert all(r["latencia_ms"].isdigit() and r["enviado_em"].endswith("Z") for r in linhas)
    assert {r["mercado"] for r in linhas} == {"IN", "GB", "SA", "DE"}
    assert "token-de-teste" not in arquivo.read_text(encoding="utf-8-sig")
    assert "98765" not in arquivo.read_text(encoding="utf-8-sig")


def test_main_exige_template_e_tipos_validos():
    with pytest.raises(SystemExit):
        enviar.main(["--tipos", "foto"], env={})
    with pytest.raises(SystemExit):
        enviar.main([], env={})


# ───────────────────────── atualização pelos webhooks ─────────────────────────

def webhook(wamid: str, status: str, ts: str, errors: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    st: dict[str, Any] = {"id": wamid, "status": status, "timestamp": ts, "recipient_id": "919876543210"}
    if errors:
        st["errors"] = errors
    return {"object": "whatsapp_business_account",
            "entry": [{"id": "waba", "changes": [{"field": "messages", "value": {"statuses": [st]}}]}]}


def linhas_enviadas() -> list[dict[str, Any]]:
    d = n.Destino("919876543210", "IN", True)
    return [n.nova_linha(d, n.TIPO_TEMPLATE, "htc_teste", wamid="wamid.A", status="accepted",
                         enviado_em="2026-10-18T10:00:00.000Z",
                         observacoes="aguardando webhook de status: rode o comando atualizar"),
            n.nova_linha(d, n.TIPO_LIVRE, "", wamid="wamid.B", status="accepted", enviado_em="2026-10-18T10:00:07.000Z")]


def test_atualizar_aplica_status_fora_de_ordem_e_erro():
    base = 1792317600   # 2026-10-18T10:00:00Z
    eventos = atualizar.ler_eventos([
        "\n".join(json.dumps(w) for w in [
            webhook("wamid.A", "read", str(base + 5)),
            webhook("wamid.A", "delivered", str(base + 2)),
            webhook("wamid.A", "sent", str(base + 1)),
            webhook("wamid.B", "failed", str(base + 8), [{"code": 131026, "title": "Message undeliverable"}]),
            webhook("wamid.OUTRO", "delivered", str(base + 9)),
        ])])
    linhas = linhas_enviadas()
    assert atualizar.aplicar(linhas, eventos) == 4
    a, b = linhas
    assert a["status"] == "read" and a["entregue_em"] == "2026-10-18T10:00:02.000Z"
    assert "entrega 2000 ms" in a["observacoes"] and "aguardando" not in a["observacoes"]
    assert b["status"] == "failed" and b["codigo_erro"] == 131026 and "não tem WhatsApp" in b["mensagem_erro"]
    assert not b["entregue_em"]


def test_atualizar_le_linhas_de_log_do_cerebro():
    log = ("brain-1  | 2026-10-18 10:00:03 [debug    ] wa_status                      id=wamid.A status=delivered\n"
           "2026-10-18 10:00:09 [error    ] wa_delivery_failed             "
           "errors=[{'code': 130497, 'title': 'Restricted', 'detail': None}] id=wamid.B to=919876543210\n"
           "linha qualquer\n")
    eventos = atualizar.ler_eventos([log])
    assert [(e["wamid"], e["status"], e["codigo"]) for e in eventos] == [
        ("wamid.A", "delivered", None), ("wamid.B", "failed", 130497)]
    linhas = linhas_enviadas()
    atualizar.aplicar(linhas, eventos)
    assert linhas[0]["entregue_em"] == "2026-10-18T10:00:03.000Z"
    assert linhas[1]["codigo_erro"] == 130497 and "Mercado restrito" in linhas[1]["mensagem_erro"]


def test_atualizar_preenche_captura(tmp_path):
    linhas = linhas_enviadas()
    (tmp_path / "IN_3210_template_utility.png").write_bytes(b"png")
    assert atualizar.completar_capturas(linhas, tmp_path) == 1
    assert linhas[0]["captura"] == f"{tmp_path.name}/IN_3210_template_utility.png"
    assert linhas[1]["captura"] == ""


def test_atualizar_regrava_csv_e_xlsx(tmp_path):
    csv_path = tmp_path / "resultados_20261018-100000.csv"
    planilha.gravar(linhas_enviadas(), csv_path)
    wh = tmp_path / "status.jsonl"
    wh.write_text(json.dumps(webhook("wamid.A", "delivered", "1792317602")))
    assert atualizar.main(["--planilha", str(csv_path), "--webhooks", str(wh), "--capturas", str(tmp_path)]) == 0
    assert planilha.ler(csv_path)[0]["status"] == "delivered"


# ───────────────────────── planilha ─────────────────────────

def test_xlsx_tem_cabecalho_e_latencia_numerica(tmp_path):
    linha = n.nova_linha(n.Destino("447700900123", "GB", True), n.TIPO_LIVRE, latencia_ms=321,
                         mensagem_erro="a < b & \x07c")
    csv_path, xlsx_path = planilha.gravar([linha], tmp_path / "x.csv")
    with zipfile.ZipFile(xlsx_path) as z:
        assert {"[Content_Types].xml", "xl/workbook.xml", "xl/worksheets/sheet1.xml"} <= set(z.namelist())
        folha = z.read("xl/worksheets/sheet1.xml").decode()
    assert "numero_mascarado" in folha and '<c r="I2"><v>321</v></c>' in folha
    assert "a &lt; b &amp; c" in folha
    assert list(ler_csv(csv_path)[0]) == n.COLUNAS
