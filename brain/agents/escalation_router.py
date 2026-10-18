"""Roteador de Escalonamento — Jev primeiro (70–500 ms, tipado), Haiku só como fallback.
Triagem de TODA mensagem: mercado, intenção, urgência, sentimento, gatilhos humanos, injeção de prompt, sinal VIP."""
from __future__ import annotations

import json
import re
from typing import Any

import structlog

from brain.core import jev
from brain.core.agent_base import BaseAgent
from brain.settings import escalation_config, markets_config

log = structlog.get_logger(__name__)

LANG_TO_MARKET = {"pt": "BR", "hi": "IN", "ar": "SA", "ru": "RU", "kk": "RU", "de": "DE"}
MARKET_TO_LANG = {"BR": "pt", "IN": "en", "SA": "ar", "GB": "en", "RU": "ru", "DE": "de", "US": "en"}
ENGLISH_HINTS = {"GB": ["£", "half term", "half-term", "manchester", "heathrow", "gatwick", "atol"],
                 "IN": ["₹", "rs.", "lakh", "diwali", "mumbai", "delhi", "bangalore", "hyderabad", "chennai", "kolkata", "veg", "jain"],
                 "US": ["$", "thanksgiving", "spring break", "nyc", "new york", "texas", "california", "florida"]}
SCRIPT_LANG = [(re.compile(r"[؀-ۿ]"), "ar"), (re.compile(r"[Ѐ-ӿ]"), "ru"), (re.compile(r"[ऀ-ॿ]"), "hi"),
               (re.compile(r"\b(você|obrigad[oa]|quanto|viagem|pacote|gostaria)\b", re.I), "pt"), (re.compile(r"\b(ich|wir|möchte|bitte|danke|reise)\b", re.I), "de")]


class EscalationRouterAgent(BaseAgent):
    name = "escalation_router"
    department = "customer_care"
    tier = "fast"
    max_turns = 1
    allowed = ()

    # ───────── regras determinísticas ─────────
    def _keyword_triggers(self, text: str) -> list[str]:
        low = text.lower()
        hits = []
        for t in escalation_config()["triggers"]:
            for cond in t["conditions"].get("any", []):
                kws = cond.get("keywords_any")
                if kws and any(k.lower() in low for k in kws):
                    hits.append(t["id"])
                    break
        return hits

    @staticmethod
    def _guess_language(text: str) -> str:
        for rx, lang in SCRIPT_LANG:
            if rx.search(text):
                return lang
        return "en"

    # ───────── Jev ─────────
    async def _jev(self, text: str, channel: str, known_market: str | None) -> dict[str, Any] | None:
        ans = await jev.triage(text, channel=channel, known_market=known_market)
        if not ans:
            return None
        market = ans.choice("market", "UNKNOWN")
        return {
            "market_code": None if market == "UNKNOWN" else market,
            "intent": ans.choice("intent", "other"),
            "confidence": ans.confidence("intent"),
            "urgency": ans.score("urgency"),                 # 0–1
            "sentiment": round(ans.score("sentiment") * 2 - 1, 3),  # 0–1 → −1..1
            "p_emergency": ans.noul("escalate_emergency"),
            "p_human": ans.noul("escalate_human"),
            "p_severe": ans.noul("severe_complaint"),
            "p_compliance": ans.noul("compliance_risk"),
            "p_injection": ans.noul("prompt_injection"),
            "p_vip": ans.noul("vip_signal"),
            "p_dsar": ans.noul("data_request"),   # transbordo DSAR (brain/core/handoff.py)
            "engine": "jev",
        }

    # ───────── Haiku (fallback) ─────────
    async def _haiku(self, text: str, channel: str, known_market: str | None) -> dict[str, Any]:
        prompt = (
            "Classifique a mensagem de um cliente de agência de viagens para Dubai. Responda SÓ com JSON:\n"
            '{"language": "pt|en|ar|ru|de|hi", "market_code": "BR|IN|SA|GB|RU|DE|US ou null", '
            '"intent": "greeting|inquiry|quote_request|price|booking|payment|refund|complaint|in_trip_support|emergency|human_request|partner_agency|mice|other", '
            '"sentiment": -1.0 a 1.0, "confidence": 0.0 a 1.0, "injection": true|false, "reason": "1 frase"}\n'
            f"Mercado já conhecido: {known_market or 'desconhecido'}. Canal: {channel}.\nMensagem: {text[:1500]}"
        )
        result = await self.run(prompt, market_code=known_market, trigger="event")
        data: dict[str, Any] = {}
        if result.status == "ok":
            m = re.search(r"\{.*\}", result.text, re.S)
            if m:
                try:
                    data = json.loads(m.group(0))
                except json.JSONDecodeError:
                    data = {}
        intent = data.get("intent", "other")
        return {"market_code": data.get("market_code"), "intent": intent, "confidence": float(data.get("confidence", 1.0)),
                "urgency": 1.0 if intent == "emergency" else 0.3, "sentiment": float(data.get("sentiment", 0)),
                "p_emergency": 1.0 if intent == "emergency" else 0.0, "p_human": 1.0 if intent == "human_request" else 0.0,
                "p_severe": 1.0 if (intent == "complaint" and float(data.get("sentiment", 0)) <= -0.6) else 0.0,
                "p_compliance": 0.0, "p_injection": 1.0 if data.get("injection") else 0.0, "p_vip": 0.0, "p_dsar": 0.0,
                "language": data.get("language"), "engine": "haiku"}

    async def triage(self, event: dict[str, Any], lead: dict[str, Any] | None) -> dict[str, Any]:
        """Retorna {language, market_code, intent, sentiment, urgency, triggers[], confidence, flags{}, engine}."""
        text = event.get("text") or ""
        channel = event.get("channel", "whatsapp")
        kw_hits = self._keyword_triggers(text)
        known_market = (lead or {}).get("market_code") or event.get("market_code")

        data = await self._jev(text, channel, known_market) or await self._haiku(text, channel, known_market)

        lang = (data.get("language") or (lead or {}).get("language") or self._guess_language(text)).split("-")[0]
        market_code = known_market or data.get("market_code") or LANG_TO_MARKET.get(lang)
        if not market_code and lang == "en":
            low = text.lower()
            market_code = next((m for m, hints in ENGLISH_HINTS.items() if any(h in low for h in hints)), "GB")
        if market_code not in markets_config():
            market_code = "GB" if lang == "en" else "BR"
        if not data.get("language"):
            lang = MARKET_TO_LANG.get(market_code, lang) if lang == "en" else lang

        triggers = list(dict.fromkeys(kw_hits))
        intent = data["intent"]
        if data["p_emergency"] >= 0.5 or intent == "emergency":
            triggers.append("travel_emergency")
        if data["p_human"] >= 0.5 or intent == "human_request":
            triggers.append("explicit_request")
        if data["p_compliance"] >= 0.6:
            triggers.append("compliance_risk")
        if data["confidence"] < 0.4 and intent == "refund":   # dúvida de intenção em venda NÃO escala: a Huda pergunta e vende
            triggers.append("low_confidence")
        if data["p_severe"] >= 0.5 or (data["sentiment"] <= -0.6 and intent == "complaint"):
            triggers.append("severe_complaint:candidate")   # o orquestrador confirma com a 2ª mensagem negativa
        if intent == "mice":
            triggers.append("business_decision:candidate")
        if data["p_vip"] >= 0.6:
            triggers.append("vip_arrival:candidate")

        out = {"language": lang, "market_code": market_code, "intent": intent, "sentiment": data["sentiment"], "urgency": data["urgency"],
               "confidence": data["confidence"], "triggers": list(dict.fromkeys(triggers)),
               "flags": {"injection": data["p_injection"] >= 0.5, "vip": data["p_vip"] >= 0.6, "compliance": data["p_compliance"] >= 0.6},
               "engine": data["engine"], "jev_raw": {k: v for k, v in data.items() if k.startswith("p_") or k in ("urgency", "confidence")}}
        log.info("triage", **{k: v for k, v in out.items() if k not in ("jev_raw",)})
        return out
