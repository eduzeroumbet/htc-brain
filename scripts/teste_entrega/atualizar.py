"""Completa a planilha do teste com os webhooks de status (sent, delivered, read, failed) e as capturas de tela.

    python -m scripts.teste_entrega.atualizar --webhooks status.jsonl [--webhooks outro.json] [--planilha X.csv]

Aceita, em qualquer combinação (um por arquivo ou misturados, JSON único, lista JSON ou um JSON por linha):
  - o corpo bruto do webhook da Meta ({"object": "whatsapp_business_account", "entry": [...]});
  - só o "value" de um change ({"statuses": [...]});
  - as linhas de log do cérebro `wa_status` e `wa_delivery_failed` (docker compose logs brain).
O cruzamento é pelo wamid; o número do destinatário que vem no webhook é ignorado.
Sem --planilha, usa o resultados_*.csv mais recente. Grava o CSV e o xlsx no mesmo lugar.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections.abc import Iterable, Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.teste_entrega import nucleo as n
from scripts.teste_entrega import planilha

# 2026-10-18 12:00:00 [debug    ] wa_status    id=wamid.X status=delivered   (aceita o prefixo "brain-1  | ")
_LOG = re.compile(r"(?P<ts>\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\s+\[\s*\w+\s*\]\s+"
                  r"(?P<ev>wa_status|wa_delivery_failed)\b(?P<resto>.*)$")


def _status(wamid: Any, status: Any, quando: str | None, errors: Any = None) -> dict[str, Any] | None:
    if not wamid or not status:
        return None
    codigo, msg = n.erro_de_status(errors)
    return {"wamid": str(wamid), "status": str(status), "quando": quando, "codigo": codigo, "mensagem": msg}


def de_payload(obj: Any) -> Iterator[dict[str, Any]]:
    """Status de um webhook bruto, de um value ou de uma lista deles."""
    if isinstance(obj, list):
        for item in obj:
            yield from de_payload(item)
        return
    if not isinstance(obj, dict):
        return
    values = [c.get("value") or {} for e in obj.get("entry") or [] for c in e.get("changes") or []] or [obj]
    for v in values:
        for s in v.get("statuses") or []:
            st = _status(s.get("id"), s.get("status"), n.de_unix(s.get("timestamp")), s.get("errors"))
            if st:
                yield st


def de_log(linha: str, tz_log: timezone = timezone.utc) -> dict[str, Any] | None:
    """Linha de log do cérebro (structlog, ConsoleRenderer). O horário é o de chegada do webhook no cérebro."""
    m = _LOG.search(linha.strip())
    if not m:
        return None
    resto = m["resto"]
    wamid = re.search(r"\bid=(\S+)", resto)
    quando = n.iso(datetime.strptime(m["ts"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz_log))
    if m["ev"] == "wa_status":
        status = re.search(r"\bstatus=(\w+)", resto)
        return _status(wamid and wamid[1], status and status[1], quando)
    errors: Any = []
    lista = re.search(r"\berrors=(\[.*\])", resto)
    if lista:
        try:
            errors = ast.literal_eval(lista[1])
        except (ValueError, SyntaxError):
            errors = [{"code": c} for c in re.findall(r"'code':\s*(\d+)", lista[1])]
    return _status(wamid and wamid[1], "failed", quando, errors)


def ler_eventos(textos: Iterable[str]) -> list[dict[str, Any]]:
    eventos: list[dict[str, Any]] = []
    for texto in textos:
        try:
            eventos += list(de_payload(json.loads(texto)))
            continue
        except json.JSONDecodeError:
            pass
        for linha in texto.splitlines():
            linha = linha.strip()
            if not linha:
                continue
            try:
                eventos += list(de_payload(json.loads(linha)))
            except json.JSONDecodeError:
                ev = de_log(linha)
                if ev:
                    eventos.append(ev)
    return eventos


def aplicar(linhas: list[dict[str, Any]], eventos: list[dict[str, Any]]) -> int:
    """Aplica os status às linhas pelo wamid. Devolve quantos eventos casaram com alguma linha."""
    por_wamid = {str(lin["wamid"]): lin for lin in linhas if lin.get("wamid")}
    casados = 0
    for ev in sorted(eventos, key=lambda e: e.get("quando") or ""):
        lin = por_wamid.get(ev["wamid"])
        if lin is None:
            continue
        casados += 1
        if ev["status"] == "delivered" and not lin.get("entregue_em"):
            lin["entregue_em"] = ev["quando"] or ""
        if ev["status"] == "read" and not lin.get("entregue_em") and ev["quando"]:
            lin["entregue_em"] = ev["quando"]
            n.anotar(lin, "entregue_em pelo 'read' (webhook 'delivered' não recebido)")
        if ev["status"] == "failed":
            lin["codigo_erro"] = ev["codigo"] if ev["codigo"] is not None else lin.get("codigo_erro", "")
            lin["mensagem_erro"] = ev["mensagem"] or lin.get("mensagem_erro", "")
        if n.avanca_status(lin.get("status"), ev["status"]):
            lin["status"] = ev["status"]
    for lin in linhas:
        if lin.get("status") in ("sent", "delivered", "read", "failed"):
            lin["observacoes"] = str(lin.get("observacoes") or "").replace(
                "aguardando webhook de status: rode o comando atualizar", "").strip("; ")
        ms = n.ms_entre(lin.get("enviado_em"), lin.get("entregue_em"))
        if ms is not None:
            n.anotar(lin, f"entrega {ms} ms após o envio (webhook, precisão de 1 s)")
    return casados


def completar_capturas(linhas: list[dict[str, Any]], pasta: Path = n.CAPTURAS) -> int:
    achadas = 0
    for lin in linhas:
        caminho = n.achar_captura(lin, pasta)
        if caminho:
            lin["captura"] = caminho
            achadas += 1
    return achadas


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m scripts.teste_entrega.atualizar", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--planilha", help="CSV de resultados (padrão: o resultados_*.csv mais recente)")
    ap.add_argument("--webhooks", action="append", default=[], help="arquivo com webhooks ou logs ('-' = stdin)")
    ap.add_argument("--capturas", default=str(n.CAPTURAS), help="pasta das capturas de tela")
    a = ap.parse_args(argv)

    csv_path = Path(a.planilha) if a.planilha else planilha.mais_recente()
    if not csv_path or not csv_path.exists():
        print("Nenhuma planilha de resultados encontrada. Rode antes o envio com --enviar.", file=sys.stderr)
        return 2
    linhas = planilha.ler(csv_path)
    textos = [sys.stdin.read() if w == "-" else Path(w).read_text(encoding="utf-8") for w in a.webhooks]
    eventos = ler_eventos(textos)
    casados = aplicar(linhas, eventos)
    capturas = completar_capturas(linhas, Path(a.capturas))
    csv_path, xlsx_path = planilha.gravar(linhas, csv_path)

    print(f"{len(eventos)} status lido(s), {casados} casado(s) com a planilha; {capturas} captura(s) anexada(s).")
    for lin in linhas:
        erro = f" erro {lin['codigo_erro']}" if lin.get("codigo_erro") not in ("", None) else ""
        cap = "com captura" if lin.get("captura") else f"sem captura ({n.nome_captura(lin)}.png)"
        print(f"  {lin['mercado']} {lin['numero_mascarado']} {lin['tipo']}: {lin['status']}{erro}, {cap}")
    print(f"Planilha: {csv_path} e {xlsx_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
