"""Grava os arquivos knowledge/**/*.md em knowledge_chunks (um chunk por seção H2, com embedding se houver chave).

Uso: python -m scripts.ingest_knowledge [--dir knowledge]
Recusa arquivos que contenham padrões de credencial (password, senha, login:, token) — segurança primeiro.
"""
from __future__ import annotations

import argparse
import asyncio
import re
from pathlib import Path

import yaml

from brain.core import db
from brain.tools.knowledge import embed

SECRET_PATTERNS = re.compile(r"(password|senha|passwd|login\s*:|token|api[_ ]?key|secret)", re.I)


def parse(path: Path) -> tuple[dict, list[tuple[str, str]]]:
    text = path.read_text(encoding="utf-8")
    meta: dict = {}
    if text.startswith("---"):
        _, fm, text = text.split("---", 2)
        meta = yaml.safe_load(fm) or {}
    sections: list[tuple[str, str]] = []
    current_title, buf, h2 = path.stem, [], ""
    for line in text.splitlines():
        if line.startswith("## ") or line.startswith("### "):   # um chunk por H2 e por H3 (atrações, hotéis...) — recuperação precisa
            if buf:
                sections.append((current_title, "\n".join(buf).strip()))
            if line.startswith("## "):
                h2 = line[3:].strip(); current_title = h2
            else:
                current_title = f"{h2} › {line[4:].strip()}" if h2 else line[4:].strip()
            buf = []
        else:
            buf.append(line)
    if buf:
        sections.append((current_title, "\n".join(buf).strip()))
    return meta, [(t, b) for t, b in sections if len(b) > 40]


async def main(directory: str, close_pool: bool = True) -> None:
    await db.pool()
    files = sorted(Path(directory).rglob("*.md"))
    total = 0
    for path in files:
        if path.name.lower() == "readme.md":
            continue
        meta, sections = parse(path)
        raw = path.read_text(encoding="utf-8")
        if SECRET_PATTERNS.search(raw) and "credencial" not in raw.lower():
            print(f"RECUSADO (possível credencial): {path}")
            continue
        topic = meta.get("topic") or path.stem
        source = meta.get("source") or str(path)
        await db.execute("DELETE FROM knowledge_chunks WHERE topic = $1 AND source_url = $2", topic, source)
        for title, body in sections:
            content = f"# {title}\n\n{body}"
            vec = None
            try:
                vec = str(await embed(content))
            except Exception:  # noqa: BLE001 — sem embeddings, busca textual
                pass
            await db.execute(
                """INSERT INTO knowledge_chunks (market_code, topic, source_url, source_date, language, content, embedding, valid_until)
                   VALUES ($1,$2,$3,current_date,$4,$5,$6::vector, CASE WHEN $7::int IS NULL THEN NULL ELSE current_date + $7::int END)""",
                meta.get("market_code"), topic, source, meta.get("language", "pt"), content, vec, meta.get("valid_days"),
            )
            total += 1
        print(f"ok {path} → {len(sections)} chunks (topic={topic})")
    print(f"total: {total} chunks")
    if close_pool:
        await db.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="knowledge")
    asyncio.run(main(ap.parse_args().dir))
