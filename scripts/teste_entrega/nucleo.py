"""Regras do teste de entrega, sem rede: números de teste, mercado, máscara, payloads, latência, status e erros da Meta.

Os números vêm de numeros.json (fora do versionamento) e nunca aparecem inteiros na planilha nem no terminal:
só o mercado, o código do país e os 4 últimos dígitos.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from brain.channels.delivery_failures import extract_error_codes, market_from_phone
from brain.core.logsafe import redact

PASTA = Path(__file__).resolve().parent
NUMEROS = PASTA / "numeros.json"
RESULTADOS = PASTA / "resultados"
CAPTURAS = PASTA / "capturas"

TOTAL_NUMEROS = 4
NUMERO_WABA = "971585153946"   # +971 58 515 3946: é o remetente, nunca destino

TIPO_TEMPLATE, TIPO_LIVRE = "template_utility", "livre"
COLUNAS = ["mercado", "numero_mascarado", "tipo", "template", "wamid", "status", "enviado_em", "entregue_em",
           "latencia_ms", "codigo_erro", "mensagem_erro", "captura", "observacoes"]

# Huda não se apresenta como IA: o texto de teste é neutro e assinado só com o nome.
TEXTO_LIVRE_PADRAO = ("Hello, this is Huda from Dubai Explore. We are checking that our WhatsApp messages reach you. "
                      "No reply needed. Thank you!")
_MENCIONA_IA = re.compile(r"\b(?:AI|IA)\b|\bA\.I\.|(?i:\b(?:chat\s?bot|bot|artificial intelligence|intelig[eê]ncia "
                          r"artificial|virtual assistant|assistente virtual)\b)")

# status da Meta, do menos ao mais avançado; "failed" é terminal
_ORDEM_STATUS = {"dry_run": 0, "accepted": 1, "held_for_quality_assessment": 1, "paused": 1, "sent": 2,
                 "delivered": 3, "read": 4, "failed": 5}

URL_CODIGOS = "https://developers.facebook.com/docs/whatsapp/cloud-api/support/error-codes"
ERROS_META: dict[int, str] = {
    130497: "Mercado restrito: a conta não pode enviar para este país (falha permanente, não retentar)",
    131047: "Janela de 24h fechada: mensagem livre só vale se o número escreveu para o +971 58 515 3946 nas últimas 24h",
    131026: "Não entregue: o número não tem WhatsApp, usa versão antiga ou não aceitou os termos",
    131049: "A Meta não entregou para preservar o engajamento (limite por usuário); não retentar em seguida",
    131000: "Erro genérico da Meta",
    131005: "Acesso negado: o token não tem a permissão necessária",
    131008: "Parâmetro obrigatório ausente",
    131009: "Valor de parâmetro inválido",
    131016: "Serviço da Meta indisponível no momento",
    131021: "Destino igual ao remetente",
    131030: "Destino fora da lista de números permitidos (app em modo de desenvolvimento)",
    131031: "Conta bloqueada pela Meta",
    131042: "Problema no método de pagamento da conta WhatsApp",
    131048: "Limite de spam: muitas mensagens bloqueadas ou denunciadas",
    131051: "Tipo de mensagem não suportado",
    131056: "Muitas mensagens para o mesmo destino em pouco tempo (par remetente/destino)",
    132000: "Template: número de parâmetros diferente do aprovado",
    132001: "Template não existe no idioma informado ou não está aprovado",
    132005: "Template: texto traduzido longo demais",
    132007: "Template: conteúdo viola a política da Meta",
    132012: "Template: formato de parâmetro diferente do aprovado",
    132015: "Template pausado por baixa qualidade",
    132016: "Template desativado",
    133010: "Número remetente não registrado na Cloud API",
    130429: "Limite de taxa da Cloud API",
    80007: "Limite de taxa da conta WhatsApp",
    368: "Remetente bloqueado temporariamente por violação de política",
    190: "Token expirado ou inválido",
    100: "Parâmetro inválido na requisição",
    10: "Permissão negada ao token",
    4: "Limite de chamadas do app",
}


class ErroConfig(ValueError):
    """Configuração recusada: o script não roda (nem em dry-run) até corrigir."""


@dataclass(frozen=True)
class Destino:
    numero: str        # só dígitos, E.164 sem '+', como a Meta usa em "to"
    mercado: str       # declarado no numeros.json (IN, GB, SA, DE…) e conferido com o prefixo
    janela_24h: bool   # o número escreveu para o +971 58 515 3946 nas últimas 24h?

    @property
    def mascarado(self) -> str:
        return mascarar(self.numero)


# ───────────────────────── números ─────────────────────────

def normalizar(numero: str | None) -> str:
    return re.sub(r"\D", "", numero or "")


def mascarar(numero: str | None) -> str:
    """+<código do país>*****<4 últimos>, no formato do logsafe, com o código do país pelo prefixo conhecido."""
    d = normalizar(numero)
    if len(d) < 5:
        return "*****"
    _, prefixo = market_from_phone(d)
    return f"{prefixo or '+'}{'*' * 5}{d[-4:]}"


def mercado(numero: str | None) -> str:
    return market_from_phone(normalizar(numero))[0]


def ler_numeros(caminho: Path = NUMEROS) -> list[Destino]:
    if not caminho.exists():
        raise ErroConfig(f"{caminho.name} não existe: copie numeros.exemplo.json para numeros.json e preencha os 4 números")
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ErroConfig(f"{caminho.name} não é JSON válido (linha {e.lineno})") from None
    itens = dados.get("numeros") if isinstance(dados, dict) else None
    if not isinstance(itens, list):
        raise ErroConfig(f'{caminho.name} precisa de uma lista "numeros"')
    destinos, vistos = [], set()
    for i, item in enumerate(itens, 1):
        if not isinstance(item, dict):
            raise ErroConfig(f"item {i} do {caminho.name} não é um objeto")
        d = normalizar(str(item.get("numero", "")))
        declarado = str(item.get("mercado", "")).strip().upper()
        if not 8 <= len(d) <= 15 or d.startswith("0"):
            raise ErroConfig(f"item {i}: número ausente ou inválido (use E.164, ex.: +44 7700 900123)")
        if d == NUMERO_WABA:
            raise ErroConfig(f"item {i}: é o próprio número de testes (+971 58 515 3946), que é o remetente")
        if d in vistos:
            raise ErroConfig(f"item {i}: número repetido ({mascarar(d)})")
        detectado = mercado(d)
        if not declarado:
            raise ErroConfig(f"item {i} ({mascarar(d)}): informe o mercado")
        if detectado == "unknown":
            raise ErroConfig(f"item {i} ({mascarar(d)}): prefixo fora dos mercados conhecidos")
        if detectado != "ambiguous" and detectado != declarado:
            raise ErroConfig(f"item {i} ({mascarar(d)}): mercado declarado {declarado}, mas o prefixo é de {detectado}")
        vistos.add(d)
        destinos.append(Destino(d, declarado, bool(item.get("janela_24h", False))))
    return destinos


def selecionar(destinos: list[Destino], so: list[str] | None = None, parcial: bool = False) -> list[Destino]:
    """Aplica as travas de volume: no máximo 4, exatamente 4 sem --parcial, e --so só com números do arquivo."""
    if len(destinos) > TOTAL_NUMEROS:
        raise ErroConfig(f"o arquivo tem {len(destinos)} números; o teste é só com {TOTAL_NUMEROS}")
    escolhidos = destinos
    if so:
        por_numero = {d.numero: d for d in destinos}
        fora = [mascarar(n) for n in so if normalizar(n) not in por_numero]
        if fora:
            raise ErroConfig(f"número(s) fora do numeros.json: {', '.join(fora)}. Só os números de teste do arquivo")
        escolhidos = [por_numero[n] for n in dict.fromkeys(normalizar(n) for n in so)]
    if len(escolhidos) < TOTAL_NUMEROS and not parcial:
        raise ErroConfig(f"{len(escolhidos)} número(s) selecionado(s); o teste completo usa {TOTAL_NUMEROS}. "
                         "Para rodar com menos, use --parcial")
    if not escolhidos:
        raise ErroConfig("nenhum número selecionado")
    return escolhidos


# ───────────────────────── payloads ─────────────────────────

def payload_template(to: str, nome: str, idioma: str, parametros: list[str] | None = None) -> dict[str, Any]:
    template: dict[str, Any] = {"name": nome, "language": {"code": idioma}}
    if parametros:
        template["components"] = [{"type": "body", "parameters": [{"type": "text", "text": p} for p in parametros]}]
    return {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to, "type": "template",
            "template": template}


def payload_livre(to: str, texto: str) -> dict[str, Any]:
    return {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to, "type": "text",
            "text": {"preview_url": False, "body": texto}}


def menciona_ia(texto: str) -> bool:
    return bool(_MENCIONA_IA.search(texto or ""))


def validar_payload(p: dict[str, Any]) -> list[str]:
    """Problemas que a Meta recusaria (ou que quebram regra do projeto). Lista vazia = ok."""
    erros = []
    if not 8 <= len(normalizar(p.get("to"))) <= 15 or p.get("to") != normalizar(p.get("to")):
        erros.append("destino inválido (E.164 só com dígitos)")
    if p.get("type") == "template":
        t = p.get("template") or {}
        if not re.fullmatch(r"[a-z0-9_]{1,512}", t.get("name") or ""):
            erros.append("nome do template inválido (minúsculas, dígitos e _)")
        if not re.fullmatch(r"[a-z]{2,3}(?:_[A-Z]{2})?", (t.get("language") or {}).get("code") or ""):
            erros.append("idioma do template inválido (ex.: en, en_US, ar)")
        for c in t.get("components") or []:
            for prm in c.get("parameters") or []:
                txt = prm.get("text") or ""
                if not txt.strip() or re.search(r"[\n\t]| {5,}", txt):
                    erros.append("parâmetro do template vazio ou com quebra de linha, tab ou 5+ espaços")
                if menciona_ia(txt):
                    erros.append("parâmetro do template diz que é IA (a Huda não se apresenta como IA)")
    elif p.get("type") == "text":
        body = (p.get("text") or {}).get("body") or ""
        if not 1 <= len(body) <= 4096:
            erros.append("texto livre vazio ou com mais de 4096 caracteres")
        if menciona_ia(body):
            erros.append("texto livre diz que é IA (a Huda não se apresenta como IA)")
    else:
        erros.append(f"tipo de mensagem não previsto no teste: {p.get('type')}")
    return erros


def payload_para_exibir(p: dict[str, Any]) -> dict[str, Any]:
    return {**p, "to": mascarar(p.get("to"))}


# ───────────────────────── tempo e latência ─────────────────────────

def agora() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def de_iso(texto: str | None) -> datetime | None:
    if not texto:
        return None
    try:
        dt = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def de_unix(ts: Any) -> str | None:
    """Timestamp dos webhooks da Meta (segundos, em texto) → ISO UTC."""
    try:
        return iso(datetime.fromtimestamp(int(ts), tz=timezone.utc))
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def latencia_ms(inicio: float, fim: float) -> int:
    """ms entre requisição e resposta da API, a partir de time.perf_counter()."""
    if fim < inicio:
        raise ValueError("fim antes do início")
    return round((fim - inicio) * 1000)


def ms_entre(inicio_iso: str | None, fim_iso: str | None) -> int | None:
    """ms entre o envio e um webhook de status. O webhook da Meta tem precisão de 1 s; diferença negativa vira 0."""
    a, b = de_iso(inicio_iso), de_iso(fim_iso)
    if a is None or b is None:
        return None
    return max(0, round((b - a).total_seconds() * 1000))


# ───────────────────────── status e erros ─────────────────────────

def avanca_status(atual: str | None, novo: str | None) -> bool:
    """Webhooks chegam fora de ordem: só troca o status por um mais avançado (failed sempre ganha)."""
    if not novo or novo not in _ORDEM_STATUS:
        return False
    return _ORDEM_STATUS[novo] > _ORDEM_STATUS.get(atual or "", -1)


def descrever_erro(codigo: int | str | None) -> str:
    if codigo in (None, ""):
        return ""
    try:
        return ERROS_META.get(int(codigo), f"Código não mapeado: ver {URL_CODIGOS}")
    except (TypeError, ValueError):
        return f"Código não numérico: ver {URL_CODIGOS}"


def erro_da_resposta(corpo: Any) -> tuple[int | None, str]:
    """(código, mensagem) de uma resposta síncrona de erro da Graph ({"error": {...}}). Sem número nem token."""
    codigos = extract_error_codes(corpo)
    if not codigos:
        return None, ""
    e = corpo.get("error") or {}
    detalhe = (e.get("error_data") or {}).get("details") or ""
    meta = " — ".join(x for x in (str(e.get("message") or ""), str(detalhe)) if x)
    return codigos[0], _mensagem(codigos[0], meta)


def erro_de_status(errors: Any) -> tuple[int | None, str]:
    """(código, mensagem) do primeiro erro de statuses[].errors[] de um webhook."""
    for e in errors or []:
        if not isinstance(e, dict):
            continue
        try:
            codigo = int(e.get("code"))
        except (TypeError, ValueError):
            continue
        detalhe = (e.get("error_data") or {}).get("details") or e.get("detail") or ""
        meta = " — ".join(x for x in (str(e.get("title") or e.get("message") or ""), str(detalhe)) if x)
        return codigo, _mensagem(codigo, meta)
    return None, ""


_DIGITOS = re.compile(r"(?<![\d*])\d{8,15}(?!\d)")   # número sem '+' (o redact só mascara E.164 com '+')


def _mensagem(codigo: int, meta: str) -> str:
    texto = descrever_erro(codigo)
    if not meta:
        return texto
    return f"{texto} | Meta: {_DIGITOS.sub(lambda m: mascarar(m[0]), redact(meta))}"


# ───────────────────────── planilha ─────────────────────────

def nova_linha(dest: Destino, tipo: str, template: str = "", **campos: Any) -> dict[str, Any]:
    linha: dict[str, Any] = dict.fromkeys(COLUNAS, "")
    linha.update(mercado=dest.mercado, numero_mascarado=dest.mascarado, tipo=tipo, template=template)
    linha.update(campos)
    return linha


def nome_captura(linha: dict[str, Any]) -> str:
    """Nome-base esperado da captura: <MERCADO>_<4 últimos>_<tipo>, ex.: IN_3210_template_utility."""
    finais = re.sub(r"\D", "", str(linha.get("numero_mascarado") or ""))[-4:]
    return f"{linha.get('mercado')}_{finais}_{linha.get('tipo')}"


def achar_captura(linha: dict[str, Any], pasta: Path = CAPTURAS) -> str:
    """Caminho relativo (capturas/…) da captura, se o arquivo existir; senão vazio."""
    base = nome_captura(linha)
    for ext in (".png", ".jpg", ".jpeg", ".webp", ".heic", ".pdf"):
        for nome in (base + ext, base + ext.upper()):
            if (pasta / nome).is_file():
                return f"{pasta.name}/{nome}"
    return ""


def anotar(linha: dict[str, Any], texto: str) -> None:
    obs = str(linha.get("observacoes") or "")
    if texto and texto not in obs:
        linha["observacoes"] = f"{obs}; {texto}" if obs else texto
