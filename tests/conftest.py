"""Testes do cérebro: `pip install -e '.[dev]' && pytest tests`.

Os testes de banco (test_consent_db.py) só rodam com HTC_TEST_DATABASE_URL apontando para um Postgres 16 descartável
(com pgvector); eles aplicam db/migrations ali. Nunca aponte para produção.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("ANTHROPIC_API_KEY", "x")
os.environ.setdefault("DATABASE_URL", os.environ.get("HTC_TEST_DATABASE_URL", "postgresql://x:x@localhost/x"))
os.environ.setdefault("REDIS_URL", "redis://localhost")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
