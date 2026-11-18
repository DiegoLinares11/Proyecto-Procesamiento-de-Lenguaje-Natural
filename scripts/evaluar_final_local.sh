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
# La afirmación de energía termina con la evaluación; no cambia preferencias del sistema.
if command -v caffeinate >/dev/null 2>&1; then
  exec caffeinate -is .venv/bin/python scripts/evaluar_banco.py "$@"
fi
exec .venv/bin/python scripts/evaluar_banco.py "$@"
