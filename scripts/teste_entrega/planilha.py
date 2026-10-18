"""Planilha de resultados em CSV e xlsx. O xlsx é escrito só com a biblioteca padrão (sem openpyxl no projeto)."""
from __future__ import annotations

import csv
import re
import zipfile
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from scripts.teste_entrega.nucleo import COLUNAS, RESULTADOS

_NUMERICAS = {"latencia_ms", "codigo_erro"}
_INVALIDOS_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def caminho_novo(prefixo: str, quando: str) -> Path:
    """resultados/<prefixo>_<AAAAMMDD-HHMMSS>.csv — cada rodada num arquivo, nada é sobrescrito."""
    carimbo = re.sub(r"\D", "", quando)[:14]
    return RESULTADOS / f"{prefixo}_{carimbo[:8]}-{carimbo[8:14]}.csv"


def mais_recente(pasta: Path = RESULTADOS) -> Path | None:
    arquivos = sorted(pasta.glob("resultados_*.csv"))
    return arquivos[-1] if arquivos else None


def gravar(linhas: list[dict[str, Any]], csv_path: Path) -> tuple[Path, Path]:
    """Grava o CSV e o xlsx (mesmo nome) e devolve os dois caminhos."""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:   # BOM: o Excel abre com acentos certos
        w = csv.DictWriter(f, fieldnames=COLUNAS, extrasaction="ignore")
        w.writeheader()
        w.writerows(linhas)
    xlsx_path = csv_path.with_suffix(".xlsx")
    escrever_xlsx(linhas, xlsx_path)
    return csv_path, xlsx_path


def ler(csv_path: Path) -> list[dict[str, Any]]:
    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        return [{c: r.get(c, "") or "" for c in COLUNAS} for r in csv.DictReader(f)]


# ───────────────────────── xlsx mínimo ─────────────────────────

def _coluna(i: int) -> str:
    letras = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        letras = chr(65 + r) + letras
    return letras


def _celula(ref: str, chave: str, valor: Any) -> str:
    texto = "" if valor is None else str(valor)
    if chave in _NUMERICAS and re.fullmatch(r"-?\d+", texto):
        return f'<c r="{ref}"><v>{texto}</v></c>'
    texto = escape(_INVALIDOS_XML.sub("", texto))
    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{texto}</t></is></c>'


def escrever_xlsx(linhas: list[dict[str, Any]], caminho: Path) -> None:
    cabecalho = {c: c for c in COLUNAS}
    linhas_xml = []
    for n, linha in enumerate([cabecalho, *linhas], 1):
        celulas = "".join(_celula(f"{_coluna(i)}{n}", c if n > 1 else "", linha.get(c, ""))
                          for i, c in enumerate(COLUNAS))
        linhas_xml.append(f'<row r="{n}">{celulas}</row>')
    folha = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" '
             'state="frozen"/></sheetView></sheetViews>'
             f'<cols><col min="1" max="{len(COLUNAS)}" width="22" customWidth="1"/></cols>'
             f'<sheetData>{"".join(linhas_xml)}</sheetData></worksheet>')
    arquivos = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>'),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="xl/workbook.xml" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"/>'
            '</Relationships>'),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="resultados" sheetId="1" r:id="rId1"/></sheets></workbook>'),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/>'
            '</Relationships>'),
        "xl/worksheets/sheet1.xml": folha,
    }
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(caminho, "w", zipfile.ZIP_DEFLATED) as z:
        for nome, conteudo in arquivos.items():
            z.writestr(nome, conteudo)
