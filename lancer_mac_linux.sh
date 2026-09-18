#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  echo "Installation initiale…"
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/pip install -r requirements.txt
fi

echo "VozLocal est disponible sur http://127.0.0.1:8000"
if command -v open >/dev/null 2>&1; then open http://127.0.0.1:8000; fi
if command -v xdg-open >/dev/null 2>&1; then xdg-open http://127.0.0.1:8000 >/dev/null 2>&1 || true; fi
exec .venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8000

