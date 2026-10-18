"""Classificador de descadastro fora dos seis termos (brain/core/descadastro.py + config/descadastro.yaml), sem banco.

Tabela de casos da decisão em docs/decisoes/descadastro-fora-da-lista.md (IDs T-0xx onde houver).
"""
from __future__ import annotations

import pytest

from brain.core import consent, descadastro
from brain.core.descadastro import AMBIGUO, CLARO, LISTA

# ───────────────────────── normalização ─────────────────────────


@pytest.mark.parametrize("entrada, esperado", [
    ("stooop", "stop"),                 # T-028: 3+ letras repetidas → 1
    ("pararrr", "parar"),
    ("stoop", "stoop"),                 # 2 repetidas ficam
    ("ＳＴＯＰ", "stop"),                # largura total (NFKC)
    ("STOP 🙏🏽", "stop"),               # emoji com tom de pele
    ("stop‍👍", "stop"),           # ZWJ
    ("‏ألغ", "الغ"),               # marca RTL
    ("ألغ ١", "الغ 1"),                 # T-031: dígito árabe
    ("۳ ३ 3", "3 3 3"),                 # árabe estendido, devanágari
    ("Hör nicht auf", "hor nicht auf"),
    ("  STOP !  ", "stop"),             # T-029
])
def test_normalizar_ampliado(entrada: str, esperado: str) -> None:
    assert consent.normalizar(entrada) == esperado


# ───────────────────────── tabela por idioma ─────────────────────────

CASOS: list[tuple[str, str, str]] = [
    # (mensagem, classe, idioma)
    # pt
    ("PARAR", LISTA, "pt"),                                       # T-001
    ("PARAR por favor", LISTA, "pt"),
    ("SAIR", LISTA, "pt"),
    ("Descadastrar", LISTA, "pt"),
    ("pare", LISTA, "pt"),
    ("me descadastre, obrigado", LISTA, "pt"),
    ("parar?", AMBIGUO, "pt"),                                    # T-003
    ("Sair?", AMBIGUO, "pt"),
    ("Chega", AMBIGUO, "pt"),
    ("basta!", AMBIGUO, "pt"),
    ("Cancela", AMBIGUO, "pt"),                                   # desvio da etapa 3: "cancela" pode ser da reserva
    ("pode parar?", AMBIGUO, "pt"),
    ("Sair de tudo?", AMBIGUO, "pt"),
    ("parar de mandar mensagem?", AMBIGUO, "pt"),                 # pedido em forma de pergunta, sem "poderia"
    ("quer parar de receber mensagens?", AMBIGUO, "pt"),
    ("pare de me mandar mensagens", CLARO, "pt"),                 # T-002
    ("parar de mandar mensagem", CLARO, "pt"),                    # T-025 (critério de pronto)
    ("não quero mais receber mensagens", CLARO, "pt"),
    ("Não me envie mais mensagens!!", CLARO, "pt"),
    ("quero parar de receber marketing", CLARO, "pt"),
    ("remova meu número da lista", CLARO, "pt"),
    ("não quero mais ofertas", CLARO, "pt"),
    ("poderia parar de me enviar ofertas?", CLARO, "pt"),         # pergunta educada com objeto: claro
    ("não, pare de me mandar mensagens", CLARO, "pt"),            # "não" em outra oração não é negação do pedido
    ("Não para de chegar mensagem de vocês, parem de mandar mensagem", CLARO, "pt"),
    ("PAREEE DE MANDAR MENSAGEM 😡😡", CLARO, "pt"),
    # en
    ("STOP", LISTA, "en"),                                        # T-005
    ("STOP please", LISTA, "en"),                                 # T-006
    ("STOP por favor", LISTA, "en"),                              # T-027
    ("UNSUBSCRIBE obrigado", LISTA, "en"),
    ("stooop", LISTA, "en"),                                      # T-028
    ("  STOP !  ", LISTA, "en"),                                  # T-029
    ("STOP 🙏", LISTA, "en"),                                     # T-030
    ("ＳＴＯＰ", LISTA, "en"),
    ("opt-out", LISTA, "en"),
    ("Stop promotions", LISTA, "en"),
    ("STOP please?", AMBIGUO, "en"),                              # T-007 / T-026 (critério de pronto)
    ("stop?", AMBIGUO, "en"),
    ("STOP? 🙏", AMBIGUO, "en"),
    ("enough", AMBIGUO, "en"),
    ("cancel", AMBIGUO, "en"),
    ("please stop sending me offers", CLARO, "en"),               # T-009
    ("don't message me again", CLARO, "en"),
    ("no more messages", CLARO, "en"),
    ("I want to stop receiving marketing messages", CLARO, "en"),
    ("could you stop sending me offers?", CLARO, "en"),
    ("leave me alone", CLARO, "en"),
    # ar
    ("ألغ", LISTA, "ar"),                                         # T-010
    ("ألغِ", LISTA, "ar"),
    ("إلغاء الاشتراك", LISTA, "ar"),
    ("أوقف", LISTA, "ar"),
    ("بس", AMBIGUO, "ar"),                                        # T-011
    ("خلاص", AMBIGUO, "ar"),
    ("لا ترسل", AMBIGUO, "ar"),                                   # desvio: sem objeto pode ser "não mande [a cotação]"
    ("ألغ ١", AMBIGUO, "ar"),                                     # T-031: termo + número → pergunta (desvio, ver decisão)
    ("لا ترسل لي رسائل", CLARO, "ar"),                            # T-012
    ("لا أريد المزيد من الرسائل", CLARO, "ar"),
    ("أخرجني من قائمة الإرسال", CLARO, "ar"),
    # hi — devanágari
    ("रोकें", LISTA, "hi"),                                       # T-013
    ("बंद करो", LISTA, "hi"),
    ("बस", AMBIGUO, "hi"),                                        # T-014
    ("मुझे और संदेश मत भेजो", CLARO, "hi"),                       # T-015
    ("मुझे मार्केटिंग संदेश नहीं चाहिए", CLARO, "hi"),
    # hi — hinglish
    ("stop karo", LISTA, "hi"),                                   # T-016
    ("band karo", LISTA, "hi"),
    ("message mat bhejo", LISTA, "hi"),
    ("bas?", AMBIGUO, "hi"),
    ("Mujhe aur messages mat bhejo", CLARO, "hi"),
    ("mujhe marketing messages nahi chahiye", CLARO, "hi"),
    # ru
    ("стоп", LISTA, "ru"),                                        # T-018
    ("Отписаться", LISTA, "ru"),
    ("хватит", AMBIGUO, "ru"),                                    # T-019
    ("стоп?", AMBIGUO, "ru"),
    ("Не пишите мне больше", CLARO, "ru"),                        # T-020
    ("больше не пишите", CLARO, "ru"),
    ("не присылайте мне сообщения", CLARO, "ru"),
    # de
    ("abbestellen", LISTA, "de"),                                 # T-021
    ("Abmelden bitte", LISTA, "de"),
    ("Stopp", LISTA, "de"),
    ("genug?", AMBIGUO, "de"),                                    # T-022
    ("stopp?", AMBIGUO, "de"),
    ("bitte nicht mehr kontaktieren", CLARO, "de"),               # T-023
    ("keine Werbenachrichten mehr von euch", CLARO, "de"),
    ("Ich möchte keine Werbung mehr bekommen", CLARO, "de"),
]


@pytest.mark.parametrize("msg, classe, idioma", CASOS)
def test_tabela_de_casos(msg: str, classe: str, idioma: str) -> None:
    c = descadastro.classificar(msg)
    assert c is not None, msg
    assert (c.classe, c.idioma) == (classe, idioma), (msg, c)


NEGATIVOS = [
    # negação do pedido
    "não pare de me mandar as fotos",                             # T-004
    "não pare de enviar fotos",
    "Don't stop sending the photos",                              # T-008
    "don't cancel my trip",
    "لا تتوقف عن إرسال الصور",
    "तस्वीरें भेजना बंद मत करो",
    "Photos bhejna stop mat karo",                                # T-017
    "не переставайте отправлять фотографии",
    "Hör nicht auf, mir die Fotos zu schicken",                   # T-024
    "não quero parar de viajar",
    # palavra do descadastro em outro sentido
    "cancelar minha viagem",
    "quero cancelar o passeio de amanhã",
    "stop at the hotel?",
    "Stopp am Hotel?",
    "Bus stop near the hotel?",
    "stopover in Dubai",
    "posso sair amanhã?",
    "vamos sair às 9h",
    "parar de viajar",
    "unsubscribed",
    "stoop",
    # conversa normal
    "olá, quero um pacote para Dubai",
    "a mensagem não chegou",
    "Can you send me the offers?",
    "أرسل لي العروض",
    "पूरा पैकेज भेजो",
    "Отправьте мне предложение",
    "Schicken Sie mir bitte Angebote",
    "sim",
    "",
]


@pytest.mark.parametrize("msg", NEGATIVOS)
def test_negativos_nao_acionam(msg: str) -> None:
    assert descadastro.classificar(msg) is None


def test_os_seis_termos_originais_continuam_revogando() -> None:
    for termo in ("PARAR", "STOP", "SAIR", "UNSUBSCRIBE", "ألغِ", "रोकें"):
        c = descadastro.classificar(termo)
        assert c is not None and c.classe == LISTA, termo
        assert c.idioma == consent.detectar_descadastro(termo)


def test_cortesia_nao_anula_o_descadastro() -> None:
    for msg in ("STOP please", "PARAR por favor", "UNSUBSCRIBE obrigado", "stop thanks", "abbestellen danke", "стоп пожалуйста",
                "ألغ من فضلك", "रोकें कृपया"):
        c = descadastro.classificar(msg)
        assert c is not None and c.classe == LISTA, msg


def test_interrogacao_em_qualquer_script_vira_ambiguo() -> None:
    for msg in ("stop?", "stop？", "ألغ؟", "¿stop?"):
        c = descadastro.classificar(msg)
        assert c is not None and c.classe == AMBIGUO, msg


# ───────────────────────── resposta à pergunta ─────────────────────────


@pytest.mark.parametrize("msg, esperado", [
    ("sim", "sim"), ("SIM!", "sim"), ("Sim, pode parar", "sim"), ("yes please", "sim"), ("Yes", "sim"), ("نعم", "sim"),
    ("हाँ", "sim"), ("हां", "sim"), ("haan", "sim"), ("да", "sim"), ("Ja", "sim"), ("ok", "sim"),
    ("não", "nao"), ("Não, obrigado", "nao"), ("nao", "nao"), ("no", "nao"), ("No thanks", "nao"), ("لا", "nao"), ("नहीं", "nao"),
    ("nahi", "nao"), ("нет", "nao"), ("nein danke", "nao"),
    ("quanto custa o safari?", None), ("haha", None), ("", None), (None, None),
    ("sim mas antes me diga quanto custa o safari no deserto", None),  # longa demais para ser só a resposta
])
def test_interpretar_resposta(msg: str | None, esperado: str | None) -> None:
    assert descadastro.interpretar_resposta(msg) == esperado


# ───────────────────────── arquivo de dados ─────────────────────────


def test_arquivo_de_dados_cobre_os_seis_idiomas_e_marca_revisao_nativa() -> None:
    from brain.settings import descadastro_config

    cfg = descadastro_config()
    assert set(cfg["idiomas"]) == {"pt", "en", "ar", "hi", "ru", "de"}
    for lang, r in cfg["idiomas"].items():
        for chave in ("lista", "ambiguo", "pedidos", "objetos", "negacao", "pedido_educado"):
            assert r.get(chave), (lang, chave)
    assert set(cfg["revisao_nativa_pendente"]) >= {"ar", "hi", "ru"}
    assert cfg["prazo_confirmacao_dias"] == consent.prazo_confirmacao_dias() == 7


def test_nenhum_termo_de_lista_e_negacao_ao_mesmo_tempo() -> None:
    r = descadastro.regras()
    for f in r.negacao:
        assert f not in r.lista and f not in r.ambiguo and f not in r.frases, f
