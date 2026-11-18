#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -x .venv/bin/python ]]; then
  echo "Falta el entorno local. Preparalo con uv sync --locked."
  exit 1
fi
export PYTHONPATH=src
export TOKENIZERS_PARALLELISM=false
export RAGAS_DO_NOT_TRACK=true
export PYTORCH_ENABLE_MPS_FALLBACK=0
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"
exec .venv/bin/python -m uvicorn tickets_rag.api:app --host 127.0.0.1 --port 8000 "$@"
