"""DLQ da fila: listar e reprocessar. `python -m scripts.dlq list` · `python -m scripts.dlq replay <id> [<id> …]` · `replay --all`.

Cada entrada guarda fila de origem, motivo, tentativas, horários e o payload. O replay republica o payload na fila de
origem com o contador zerado e o histórico preservado em `_delivery.replays`, apaga a entrada da DLQ e registra
auditoria em `dlq:replayed` — tudo atômico: a mesma entrada nunca é reprocessada duas vezes.
A listagem mostra só metadados (o payload tem dados de cliente).
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import time
from datetime import datetime, timezone

from brain.core import bus, retry


def _ts(v) -> str:
    try:
        return datetime.fromtimestamp(float(v), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    except (TypeError, ValueError):
        return "-"


async def list_entries(count: int) -> None:
    rows = await bus.dlq_entries(count)
    if not rows:
        print("DLQ vazia.")
        return
    for dlq_id, r in rows:
        payload = r.get("payload") or {}
        print(f"{dlq_id}  fila={r.get('source_stream')}  tentativas={r.get('attempts')}  morto={_ts(r.get('dead_at'))}  "
              f"canal={payload.get('channel', '-')}  motivo={str(r.get('reason', ''))[:160]}")
    print(f"\n{len(rows)} entrada(s). Reprocessar: python -m scripts.dlq replay <id>")


async def replay(ids: list[str], replay_all: bool) -> int:
    rows = dict(await bus.dlq_entries(10_000))
    targets = list(rows) if replay_all else ids
    done = 0
    for dlq_id in targets:
        rec = rows.get(dlq_id)
        if not rec:
            print(f"{dlq_id}: não está na DLQ (já reprocessada?)")
            continue
        audit = {"dlq_id": dlq_id, "stream": rec["source_stream"], "by": getpass.getuser(), "at": time.time(),
                 "attempts": rec.get("attempts"), "reason": rec.get("reason")}
        ok = await bus.dlq_replay(dlq_id, retry.for_replay(rec, dlq_id), rec["source_stream"], audit)
        print(f"{dlq_id}: {'republicada em ' + rec['source_stream'] if ok else 'ignorada (já reprocessada)'}")
        done += int(ok)
    return done


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m scripts.dlq")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list")
    ls.add_argument("-n", type=int, default=50)
    rp = sub.add_parser("replay")
    rp.add_argument("ids", nargs="*")
    rp.add_argument("--all", action="store_true")
    a = ap.parse_args()
    if a.cmd == "list":
        asyncio.run(list_entries(a.n))
    else:
        if not a.ids and not a.all:
            ap.error("informe ids ou --all")
        n = asyncio.run(replay(a.ids, a.all))
        print(f"{n} reprocessada(s).")


if __name__ == "__main__":
    main()
