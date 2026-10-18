"""Envio do teste de entrega: 1 template utility + 1 mensagem livre para cada número do numeros.json.

    python -m scripts.teste_entrega.enviar --template NOME --idioma en            # dry-run (padrão): nada sai
    python -m scripts.teste_entrega.enviar --template NOME --idioma en --verificar-meta   # + leituras GET na Meta
    python -m scripts.teste_entrega.enviar --template NOME --idioma en --enviar   # envio real

Credenciais só por ambiente: WA_ACCESS_TOKEN, WA_PHONE_NUMBER_ID, WA_BUSINESS_ACCOUNT_ID (opcional WA_GRAPH_URL).
Antes do envio real o script lê na Meta (GET) se o template existe, está APPROVED e é UTILITY; se não, recusa.
Resultados em resultados/resultados_<data-hora>.csv e .xlsx (dry-run: resultados/dry_run_<data-hora>.*).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx

from brain.channels.whatsapp import GRAPH
from scripts.teste_entrega import nucleo as n
from scripts.teste_entrega import planilha

ENV_OBRIGATORIAS = ("WA_ACCESS_TOKEN", "WA_PHONE_NUMBER_ID", "WA_BUSINESS_ACCOUNT_ID")


def config_env(env: Mapping[str, str]) -> tuple[dict[str, str], list[str]]:
    faltando = [k for k in ENV_OBRIGATORIAS if not (env.get(k) or "").strip()]
    cfg = {"token": (env.get("WA_ACCESS_TOKEN") or "").strip(),
           "phone_number_id": (env.get("WA_PHONE_NUMBER_ID") or "").strip(),
           "waba": (env.get("WA_BUSINESS_ACCOUNT_ID") or "").strip(),
           "graph": (env.get("WA_GRAPH_URL") or GRAPH).rstrip("/")}
    return cfg, faltando


def montar_envios(destinos: list[n.Destino], a: argparse.Namespace) -> list[tuple[n.Destino, str, dict[str, Any]]]:
    envios = []
    for d in destinos:
        if n.TIPO_TEMPLATE in a.tipos:
            envios.append((d, n.TIPO_TEMPLATE, n.payload_template(d.numero, a.template, a.idioma, a.parametro)))
        if n.TIPO_LIVRE in a.tipos:
            envios.append((d, n.TIPO_LIVRE, n.payload_livre(d.numero, a.texto)))
    return envios


# ───────────────────────── leituras na Meta (GET) ─────────────────────────

async def verificar_meta(c: httpx.AsyncClient, cfg: dict[str, str], template: str,
                         idioma: str) -> tuple[list[str], list[str]]:
    """(erros, avisos). Só GET: confere template aprovado/utility, número remetente e saúde da conta."""
    erros, avisos = [], []
    r = await c.get(f"{cfg['graph']}/{cfg['waba']}/message_templates",
                    params={"name": template, "fields": "name,language,status,category", "limit": 100})
    if r.status_code >= 400:
        codigo, msg = n.erro_da_resposta(_json(r))
        erros.append(f"não consegui listar os templates do WABA (HTTP {r.status_code}, código {codigo}): {msg}")
    else:
        achados = [t for t in _json(r).get("data", []) if t.get("name") == template]
        no_idioma = [t for t in achados if t.get("language") == idioma]
        if not achados:
            erros.append(f"template '{template}' não existe no WABA {cfg['waba']} (criar exige aprovação do Edu)")
        elif not no_idioma:
            idiomas = ", ".join(sorted({str(t.get("language")) for t in achados}))
            erros.append(f"template '{template}' não existe no idioma {idioma} (existe em: {idiomas})")
        else:
            t = no_idioma[0]
            if t.get("status") != "APPROVED":
                erros.append(f"template '{template}' ({idioma}) está {t.get('status')}, não APPROVED")
            if t.get("category") != "UTILITY":
                erros.append(f"template '{template}' é {t.get('category')}, não UTILITY")
    r = await c.get(f"{cfg['graph']}/{cfg['phone_number_id']}",
                    params={"fields": "display_phone_number,quality_rating,health_status"})
    if r.status_code >= 400:
        codigo, msg = n.erro_da_resposta(_json(r))
        erros.append(f"não consegui ler o phone_number_id (HTTP {r.status_code}, código {codigo}): {msg}")
    else:
        info = _json(r)
        if n.normalizar(info.get("display_phone_number")) != n.NUMERO_WABA:
            avisos.append(f"WA_PHONE_NUMBER_ID aponta para {info.get('display_phone_number')}, não para +971 58 515 3946")
        saude = info.get("health_status") or {}
        if saude.get("can_send_message") == "BLOCKED":
            motivos = "; ".join(f"{e.get('error_code')}: {e.get('error_description')}"
                                for ent in saude.get("entities") or [] for e in ent.get("errors") or [])
            avisos.append(f"health_status = BLOCKED, templates tendem a falhar ({motivos or 'sem detalhe'})")
        avisos.append(f"qualidade do número: {info.get('quality_rating', '?')}")
    return erros, avisos


def _json(r: httpx.Response) -> dict[str, Any]:
    try:
        corpo = r.json()
    except ValueError:
        return {}
    return corpo if isinstance(corpo, dict) else {}


# ───────────────────────── envio ─────────────────────────

async def enviar_um(c: httpx.AsyncClient, cfg: dict[str, str], dest: n.Destino, tipo: str, payload: dict[str, Any],
                    template: str) -> dict[str, Any]:
    linha = n.nova_linha(dest, tipo, template if tipo == n.TIPO_TEMPLATE else "")
    linha["enviado_em"] = n.iso(n.agora())
    inicio = time.perf_counter()
    try:
        r = await c.post(f"{cfg['graph']}/{cfg['phone_number_id']}/messages", json=payload)
    except httpx.HTTPError as e:
        linha.update(latencia_ms=n.latencia_ms(inicio, time.perf_counter()), status="failed",
                     mensagem_erro=f"falha de rede: {type(e).__name__}")
        return linha
    linha["latencia_ms"] = n.latencia_ms(inicio, time.perf_counter())
    corpo = _json(r)
    if r.status_code >= 400:
        codigo, msg = n.erro_da_resposta(corpo)
        linha.update(status="failed", codigo_erro=codigo if codigo is not None else "",
                     mensagem_erro=msg or f"HTTP {r.status_code}")
        if codigo == 131047:
            n.anotar(linha, "janela fechada: o número precisa escrever para o +971 58 515 3946 e repetir só a livre")
        return linha
    msg = (corpo.get("messages") or [{}])[0]
    linha.update(wamid=msg.get("id", ""), status=msg.get("message_status") or "accepted")
    n.anotar(linha, "aguardando webhook de status: rode o comando atualizar")
    return linha


async def executar(a: argparse.Namespace, env: Mapping[str, str],
                   transport: httpx.AsyncBaseTransport | None = None) -> int:
    try:
        destinos = n.selecionar(n.ler_numeros(Path(a.numeros)), a.so, a.parcial)
    except n.ErroConfig as e:
        print(f"RECUSADO: {e}", file=sys.stderr)
        return 2
    envios = montar_envios(destinos, a)
    problemas = [f"{d.mascarado} {tipo}: {p}" for d, tipo, payload in envios for p in n.validar_payload(payload)]
    cfg, faltando = config_env(env)
    if a.enviar and faltando:
        problemas.append(f"variáveis de ambiente ausentes: {', '.join(faltando)}")
    if problemas:
        print("RECUSADO:\n  " + "\n  ".join(problemas), file=sys.stderr)
        return 2

    modo = "ENVIO REAL" if a.enviar else "DRY-RUN (nada é enviado)"
    print(f"== {modo}: {len(destinos)} número(s), {len(envios)} mensagem(ns)")
    for d in destinos:
        print(f"  {d.mercado:<4} {d.mascarado:<16} janela 24h: {'aberta' if d.janela_24h else 'NÃO confirmada'}")
        if n.TIPO_LIVRE in a.tipos and not d.janela_24h:
            print(f"    AVISO: a mensagem livre para {d.mascarado} deve voltar 131047 (janela de 24h fechada). Peça ao "
                  "número que mande uma mensagem para +971 58 515 3946 antes e marque janela_24h: true.")
        if d.mercado == "BR":
            print("    AVISO: Brasil está pausado no atendimento (130497); este envio é só o teste de entrega.")
    if faltando:
        print(f"  AVISO: faltam {', '.join(faltando)} no ambiente; o envio real será recusado.")

    headers = {"Authorization": f"Bearer {cfg['token']}"} if cfg["token"] else {}
    async with httpx.AsyncClient(timeout=a.timeout, headers=headers, transport=transport) as c:
        if (a.enviar or (a.verificar_meta and not faltando)) and n.TIPO_TEMPLATE in a.tipos:
            erros, avisos = await verificar_meta(c, cfg, a.template, a.idioma)
            for av in avisos:
                print(f"  Meta: {av}")
            if erros:
                print("RECUSADO:\n  " + "\n  ".join(erros), file=sys.stderr)
                return 2
        elif a.verificar_meta and faltando:
            print("  --verificar-meta ignorado: faltam variáveis de ambiente.")

        quando = n.iso(n.agora())
        if not a.enviar:
            linhas = []
            for d, tipo, payload in envios:
                print(f"\n  {d.mercado} {tipo}:\n    " + json.dumps(n.payload_para_exibir(payload), ensure_ascii=False))
                linhas.append(n.nova_linha(d, tipo, a.template if tipo == n.TIPO_TEMPLATE else "", status="dry_run",
                                           observacoes="dry-run: payload validado, nada enviado"))
            csv_path, xlsx_path = planilha.gravar(linhas, planilha.caminho_novo("dry_run", quando))
            print(f"\nDry-run ok. Planilha de conferência: {csv_path} e {xlsx_path.name}")
            print("Envio real: o mesmo comando com --enviar.")
            return 0

        linhas = []
        csv_path = planilha.caminho_novo("resultados", quando)
        try:
            for i, (d, tipo, payload) in enumerate(envios):
                if i and envios[i - 1][0] == d:
                    await asyncio.sleep(a.intervalo)   # evita o 131056 (mesmo destino em sequência)
                linha = await enviar_um(c, cfg, d, tipo, payload, a.template)
                linhas.append(linha)
                erro = f" erro {linha['codigo_erro']}" if linha["codigo_erro"] != "" else ""
                print(f"  {d.mercado} {d.mascarado} {tipo}: {linha['status']}{erro} em {linha['latencia_ms']} ms")
        finally:
            if linhas:
                csv_path, xlsx_path = planilha.gravar(linhas, csv_path)
                print(f"\nPlanilha: {csv_path} e {xlsx_path.name}")
    print("Próximo passo: python -m scripts.teste_entrega.atualizar --webhooks <arquivo com os webhooks de status>")
    return 0   # falha de entrega é resultado do teste, não erro do script


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m scripts.teste_entrega.enviar", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--template", default="", help="nome do template utility aprovado")
    ap.add_argument("--idioma", default="en", help="código de idioma do template (ex.: en, en_US, ar). Padrão: en")
    ap.add_argument("--parametro", action="append", default=[],
                    help="parâmetro do corpo do template, na ordem (repetível)")
    ap.add_argument("--texto", default=n.TEXTO_LIVRE_PADRAO, help="texto da mensagem livre")
    ap.add_argument("--tipos", default=f"{n.TIPO_TEMPLATE},{n.TIPO_LIVRE}",
                    type=lambda s: [t.strip() for t in s.split(",") if t.strip()],
                    help=f"o que enviar: {n.TIPO_TEMPLATE}, {n.TIPO_LIVRE} ou os dois (padrão)")
    ap.add_argument("--numeros", default=str(n.NUMEROS), help="arquivo com os números de teste (padrão: numeros.json)")
    ap.add_argument("--so", action="append", help="restringe a este número do arquivo (repetível; exige --parcial se < 4)")
    ap.add_argument("--parcial", action="store_true", help="permite rodar com menos de 4 números")
    modo = ap.add_mutually_exclusive_group()
    modo.add_argument("--dry-run", dest="enviar", action="store_false", help="valida sem enviar (padrão)")
    modo.add_argument("--enviar", dest="enviar", action="store_true", help="envio real")
    ap.add_argument("--verificar-meta", action="store_true", help="no dry-run, faz também as leituras GET na Meta")
    ap.add_argument("--intervalo", type=float, default=7.0, help="segundos entre as 2 mensagens do mesmo número")
    ap.add_argument("--timeout", type=float, default=20.0, help="timeout da Graph API em segundos")
    ap.set_defaults(enviar=False)
    return ap


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    ap = parser()
    a = ap.parse_args(argv)
    invalidos = [t for t in a.tipos if t not in (n.TIPO_TEMPLATE, n.TIPO_LIVRE)] or ([] if a.tipos else ["(vazio)"])
    if invalidos:
        ap.error(f"--tipos inválido: {', '.join(invalidos)}")
    if n.TIPO_TEMPLATE in a.tipos and not a.template:
        ap.error("informe --template (nome de um template utility aprovado no WABA)")
    return asyncio.run(executar(a, os.environ if env is None else env))


if __name__ == "__main__":
    raise SystemExit(main())
