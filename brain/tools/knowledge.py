"""Base de conhecimento (RAG em pgvector) + leitura da web para o Market Intel."""
from __future__ import annotations

from typing import Any

import httpx

from brain.core import db
from brain.settings import get_settings
from brain.tools import create_sdk_mcp_server, err, ok, tool

SERVER = "knowledge"
EMBED_MODEL = "voyage-3"   # 1024 dims; troque e ajuste vector(1024) na migração se usar outro


async def embed(text: str) -> list[float]:
    """Embedding via Voyage AI (parceira Anthropic). Requer VOYAGE_API_KEY no ambiente; sem chave, usa busca textual."""
    import os
    key = os.getenv("VOYAGE_API_KEY")
    if not key:
        raise RuntimeError("VOYAGE_API_KEY ausente")
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post("https://api.voyageai.com/v1/embeddings", headers={"Authorization": f"Bearer {key}"},
                         json={"input": [text[:8000]], "model": EMBED_MODEL})
        r.raise_for_status()
        return r.json()["data"][0]["embedding"]


@tool("search_knowledge", "Busca na base de conhecimento (segurança 2026, vistos, regras para visitantes, hotéis, respostas a objeções). Filtre por market_code e/ou topic. Sempre cite source_url ao responder ao cliente.", {"query": str, "market_code": str, "topic": str, "limit": int})
async def search_knowledge(args: dict[str, Any]) -> dict[str, Any]:
    limit = int(args.get("limit") or 6)
    params: list[Any] = []
    conds = ["(valid_until IS NULL OR valid_until >= current_date)"]
    if args.get("market_code"):
        params.append(args["market_code"]); conds.append(f"(market_code IS NULL OR market_code = ${len(params)})")
    if args.get("topic"):
        params.append(args["topic"]); conds.append(f"topic = ${len(params)}")
    try:
        vec = await embed(args["query"])
        params.append(str(vec)); order = f"embedding <=> ${len(params)}::vector"
    except Exception:  # noqa: BLE001 — sem embeddings, busca textual por palavras-chave (qualquer uma; ordena por quantas batem)
        import re as _re
        stop = {"para", "com", "que", "uma", "das", "dos", "the", "and", "for", "what", "quais", "qual", "como", "onde", "fazer", "podemos", "tem", "sobre", "there", "about"}
        words = [w for w in _re.findall(r"[\wÀ-ÿ]{4,}", args["query"].lower()) if w not in stop][:8] or [args["query"][:40]]
        score_terms = []
        for w in words:
            params.append(f"%{w}%"); score_terms.append(f"(content ILIKE ${len(params)})::int")
        conds.append("(" + " OR ".join(t[:-6] for t in score_terms) + ")")
        order = "(" + " + ".join(score_terms) + ") DESC, source_date DESC NULLS LAST"
    params.append(limit)
    rows = await db.fetch(
        f"SELECT id, market_code, topic, source_url, source_date, language, content FROM knowledge_chunks WHERE {' AND '.join(conds)} ORDER BY {order} LIMIT ${len(params)}",
        *params,
    )
    return ok(rows)


@tool("upsert_knowledge", "Grava ou atualiza um trecho de conhecimento (usado pelo Market Intel). topic estável (ex.: safety_2026), market_code opcional, source_url obrigatório para fatos externos.", {"topic": str, "content": str, "market_code": str, "source_url": str, "source_date": str, "language": str, "valid_days": int})
async def upsert_knowledge(args: dict[str, Any]) -> dict[str, Any]:
    if len(args.get("content", "")) < 40:
        return err("conteúdo curto demais")
    vec = None
    try:
        vec = str(await embed(args["content"]))
    except Exception:  # noqa: BLE001
        pass
    await db.execute("DELETE FROM knowledge_chunks WHERE topic = $1 AND coalesce(market_code,'') = coalesce($2,'') AND coalesce(source_url,'') = coalesce($3,'')",
                     args["topic"], args.get("market_code"), args.get("source_url"))
    await db.execute(
        """INSERT INTO knowledge_chunks (market_code, topic, source_url, source_date, language, content, embedding, valid_until)
           VALUES ($1,$2,$3,$4::date,$5,$6,$7::vector, CASE WHEN $8::int IS NULL THEN NULL ELSE current_date + $8::int END)""",
        args.get("market_code"), args["topic"], args.get("source_url"), args.get("source_date"), args.get("language"),
        args["content"], vec, args.get("valid_days"),
    )
    return ok({"stored": True})


@tool("fetch_url", "Baixa o texto de uma página pública (DET, WAM, advisories, companhias aéreas). Máx. 20k caracteres.", {"url": str})
async def fetch_url(args: dict[str, Any]) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers={"User-Agent": "brain/0.1 (+agency)"}) as c:
            r = await c.get(args["url"])
            r.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        return err(f"falha ao buscar: {exc}")
    import re
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", r.text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return ok({"url": str(r.url), "status": r.status_code, "text": text[:20000]})


def server():
    return create_sdk_mcp_server(SERVER, "1.0.0", [search_knowledge, upsert_knowledge, fetch_url])
