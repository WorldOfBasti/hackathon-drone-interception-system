#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

PYTHON_BIN="${PYTHON:-python3}"
PORT="${PORT:-8501}"

if [ ! -x ".venv/bin/python" ]; then
  echo "[*] Creating virtual environment..."
  "$PYTHON_BIN" -m venv .venv
fi

echo "[*] Installing dependencies..."
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r requirements.txt

echo "[*] Starting Streamlit dashboard..."
echo "    Open http://127.0.0.1:${PORT} in your browser"
exec .venv/bin/python -m streamlit run mti_detector/streamlit_demo.py \
  --server.port "$PORT" \
  --server.address 127.0.0.1 \
  --server.headless true
