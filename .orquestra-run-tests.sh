#!/bin/sh
# Roda pytest e scripts.check numa cópia descartável do repositório (dentro do container). Não versionar.
set -e
cp -r /src /app
cd /app
rm -f /app/.orquestra-run-tests.sh
pip install -q --root-user-action=ignore '.[dev]' 2>&1 | tail -3
echo "=== pytest ==="
python -m pytest -v 2>&1 | tail -60
echo "=== scripts.check ==="
python -m scripts.check; echo "check exit=$?"
echo "=== ruff ==="
ruff check brain/channels/webchat.py brain/core/payment_webhook.py brain/core/bus.py brain/main.py brain/settings.py tests/test_webchat_security.py; echo "ruff exit=$?"
