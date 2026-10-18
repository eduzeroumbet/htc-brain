"""Carrega config/renewals_hcte.yaml na tabela renewals. Uso: python -m scripts.sync_renewals"""
from __future__ import annotations

import asyncio
import json

from brain.core import db
from brain.tools.admin import sync_renewals_from_config, upcoming_renewals


async def main() -> None:
    await db.pool()
    print(json.loads((await sync_renewals_from_config({}))["content"][0]["text"]))
    for r in json.loads((await upcoming_renewals({"days": 120}))["content"][0]["text"]):
        print(f"{str(r['due']):>10}  {r['days_left']:>4}d  {r['name']}")
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
