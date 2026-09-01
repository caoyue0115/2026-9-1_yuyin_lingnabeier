#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${DISNEY_PROJECT_DIR:-$HOME/projects/disney-voice-assistant}"

if [[ ! -f "${PROJECT_DIR}/requirements.txt" ]]; then
  echo "project not found at ${PROJECT_DIR}" >&2
  exit 1
fi

cd "${PROJECT_DIR}"
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
mkdir -p data/logs data/incoming data/output indices
python -m src.rag.ingest

echo "bootstrap complete: ${PROJECT_DIR}"
