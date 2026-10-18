"""Classificador de descadastro no WhatsApp: os seis termos originais e o que fica fora deles (config/descadastro.yaml).

classificar(texto) → Classificacao(classe, idioma, motivo) ou None:
  lista    termo da lista (+ cortesia), sem "?"                          → revoga (comportamento dos seis termos)
  ambiguo  termo da lista com "?", termo ambíguo ("chega", "بس", "хватит"), → suspende, pergunta uma vez, só revoga com "sim"
           termo seguido de número, ou pedido claro em forma de pergunta sem marcador de pedido educado
  claro    frase de descadastro ou pedido + objeto a até 6 palavras         → suspende e abre tarefa humana, sem revogar sozinho
Antes de tudo, negação numa oração ("não pare de me mandar as fotos", "don't stop") → None.
interpretar_resposta(texto) → "sim" | "nao" | None, para a resposta à pergunta do caso ambíguo.
Decisão e motivos: docs/decisoes/descadastro-fora-da-lista.md.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from brain.core.consent import _CORTESIA, GATILHOS_DESCADASTRO, normalizar
from brain.settings import descadastro_config

LISTA, AMBIGUO, CLARO = "lista", "ambiguo", "claro"
JANELA_OBJETO = 6           # palavras entre o pedido ("pare de", "मत भेजो") e o objeto ("mensagens", "संदेश"), nos dois sentidos
MAX_PALAVRAS_TERMO = 6      # termo da lista/ambíguo só vale se a mensagem for curta (termo + cortesia)
MAX_PALAVRAS_RESPOSTA = 6
_INTERROGACAO = ("?", "؟", "¿", "⸮")
_ORACOES = re.compile(r"[,.;:!?¿؟،؛\n]+")

Frase = tuple[str, ...]


@dataclass(frozen=True)
class Classificacao:
    classe: str     # lista | ambiguo | claro
    idioma: str     # pt, en, ar, hi, ru, de
    motivo: str     # o que bateu (vai para o log e para o resumo da tarefa humana)


@dataclass(frozen=True)
class _Regras:
    lista: dict[Frase, str]
    ambiguo: dict[Frase, str]
    frases: dict[Frase, str]
    pedidos: dict[Frase, str]
    objetos: dict[str, frozenset[Frase]]
    negacao: tuple[Frase, ...]
    educado: tuple[Frase, ...]
    cortesia: frozenset[str]
    sim: tuple[Frase, ...]
    nao: tuple[Frase, ...]


def _frases(itens: list[Any] | None) -> list[Frase]:
    return [f for f in (tuple(normalizar(str(i)).split()) for i in (itens or [])) if f]


@lru_cache
def regras() -> _Regras:
    cfg = descadastro_config()
    lista: dict[Frase, str] = {(k,): v for k, v in GATILHOS_DESCADASTRO.items()}  # os seis originais nunca saem da lista
    ambiguo: dict[Frase, str] = {}
    frases: dict[Frase, str] = {}
    pedidos: dict[Frase, str] = {}
    objetos: dict[str, frozenset[Frase]] = {}
    negacao: list[Frase] = []
    educado: list[Frase] = []
    for lang, r in (cfg.get("idiomas") or {}).items():
        for destino, chave in ((lista, "lista"), (ambiguo, "ambiguo"), (frases, "frases"), (pedidos, "pedidos")):
            for f in _frases(r.get(chave)):
                destino.setdefault(f, lang)  # termo em dois idiomas ("stop"): fica o primeiro do arquivo
        objetos[lang] = frozenset(_frases(r.get("objetos")))
        negacao += _frases(r.get("negacao"))
        educado += _frases(r.get("pedido_educado"))
    cortesia = set(_CORTESIA) | {t for f in _frases(cfg.get("cortesia")) for t in f}
    resp = cfg.get("respostas") or {}
    return _Regras(lista, ambiguo, frases, pedidos, objetos, tuple(negacao), tuple(educado), frozenset(cortesia),
                   tuple(_frases(resp.get("sim"))), tuple(_frases(resp.get("nao"))))


def tem_interrogacao(texto: str | None) -> bool:
    t = unicodedata.normalize("NFKC", texto or "")
    return any(q in t for q in _INTERROGACAO)


def _acha(tokens: list[str], frase: Frase) -> int:
    """Posição da frase como sequência inteira de palavras, ou -1."""
    n = len(frase)
    return next((i for i in range(len(tokens) - n + 1) if tuple(tokens[i:i + n]) == frase), -1)


def _contem(tokens: list[str], frases: tuple[Frase, ...] | list[Frase]) -> Frase | None:
    return next((f for f in frases if _acha(tokens, f) >= 0), None)


def _so_termos(tokens: list[str], termos: dict[Frase, str], cortesia: frozenset[str]) -> tuple[list[Frase], bool] | None:
    """A mensagem inteira é termo(s) + cortesia (+ números)? Devolve (termos achados, tem_numero) ou None."""
    if not tokens or len(tokens) > MAX_PALAVRAS_TERMO:
        return None
    por_tamanho = sorted(termos, key=len, reverse=True)
    achados: list[Frase] = []
    numero = False
    i = 0
    while i < len(tokens):
        f = next((f for f in por_tamanho if tuple(tokens[i:i + len(f)]) == f), None)
        if f:
            achados.append(f)
            i += len(f)
        elif tokens[i] in cortesia:
            i += 1
        elif tokens[i].isdigit():
            numero, i = True, i + 1
        else:
            return None
    return (achados, numero) if achados else None


def _negacao(texto: str, r: _Regras) -> Frase | None:
    """Negação dentro de uma mesma oração: "não pare de me mandar as fotos" sim; "não, pare de me mandar mensagens" não."""
    for oracao in _ORACOES.split(unicodedata.normalize("NFKC", texto)):
        f = _contem(normalizar(oracao).split(), r.negacao)
        if f:
            return f
    return None


def _pedido_claro(tokens: list[str], r: _Regras) -> tuple[str, str] | None:
    """(idioma, motivo) se houver frase de descadastro, ou pedido de parar com objeto (mensagens, ofertas...) por perto."""
    for f, lang in r.frases.items():
        if _acha(tokens, f) >= 0:
            return lang, " ".join(f)
    for p, lang in r.pedidos.items():
        i = _acha(tokens, p)
        if i < 0:
            continue
        antes, depois = tokens[max(0, i - JANELA_OBJETO): i], tokens[i + len(p): i + len(p) + JANELA_OBJETO]
        for o in r.objetos.get(lang, ()):
            if _acha(antes, o) >= 0 or _acha(depois, o) >= 0:
                return lang, f"{' '.join(p)} … {' '.join(o)}"
    return None


def classificar(texto: str | None) -> Classificacao | None:
    r = regras()
    tokens = normalizar(texto).split()
    if not tokens:
        return None
    if _negacao(texto or "", r):
        return None
    pergunta = tem_interrogacao(texto)

    # 1. ambíguo antes da lista: "STOP please?" não pode revogar
    so_lista = _so_termos(tokens, r.lista, r.cortesia)
    if so_lista and (pergunta or so_lista[1]):
        f = so_lista[0][0]
        return Classificacao(AMBIGUO, r.lista[f], f"{' '.join(f)} + {'?' if pergunta else 'número'}")
    termos_curtos = {**r.lista, **r.ambiguo}
    so_ambiguo = _so_termos(tokens, termos_curtos, r.cortesia)
    if so_ambiguo and any(f in r.ambiguo for f in so_ambiguo[0]):
        f = next(f for f in so_ambiguo[0] if f in r.ambiguo)
        return Classificacao(AMBIGUO, r.ambiguo[f], " ".join(f))

    # 2. termo da lista + cortesia, sem "?": revoga
    if so_lista:
        f = so_lista[0][0]
        return Classificacao(LISTA, r.lista[f], " ".join(f))

    # 3. pedido claro fora da lista; em forma de pergunta só vale como claro com marcador de pedido ("could you", "poderia")
    claro = _pedido_claro(tokens, r)
    if claro:
        lang, motivo = claro
        if pergunta and not _contem(tokens, r.educado):
            return Classificacao(AMBIGUO, lang, f"{motivo} + ?")
        return Classificacao(CLARO, lang, motivo)
    return None


def interpretar_resposta(texto: str | None) -> str | None:
    """Resposta à pergunta de confirmação: "sim" | "nao" | None. Vale a expressão que abre a mensagem (até 6 palavras),
    em qualquer dos seis idiomas: "sim", "Sim, pode parar", "نعم", "nein danke". Quem chama já descartou descadastro novo."""
    r = regras()
    tokens = normalizar(texto).split()
    if not tokens or len(tokens) > MAX_PALAVRAS_RESPOSTA:
        return None
    for resposta, frases in (("nao", r.nao), ("sim", r.sim)):
        if any(tuple(tokens[:len(f)]) == f for f in frases):
            return resposta
    return None
