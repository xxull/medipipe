#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
else
  PY="${PYTHON:-python3}"
fi

exec "$PY" -m streamlit run app.py --server.port=8501
