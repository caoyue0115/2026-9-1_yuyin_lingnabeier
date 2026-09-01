#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${DISNEY_PROJECT_DIR:-$HOME/projects/disney-voice-assistant}"
SESSION_NAME="${DISNEY_SCREEN_SESSION:-disney_voice}"
PORT="${DISNEY_PORT:-18120}"

if [[ ! -f "${PROJECT_DIR}/.env" ]]; then
  echo "missing ${PROJECT_DIR}/.env; copy .env.example and configure it first" >&2
  exit 1
fi
if screen -ls 2>/dev/null | grep -q "\.${SESSION_NAME}[[:space:]]"; then
  echo "screen session ${SESSION_NAME} is already running" >&2
  exit 1
fi

mkdir -p "${PROJECT_DIR}/data/logs"
screen -dmS "${SESSION_NAME}" bash -lc \
  "cd '${PROJECT_DIR}' && . .venv/bin/activate && exec uvicorn src.app:app --host 0.0.0.0 --port '${PORT}' >> data/logs/server.log 2>&1"

echo "started ${SESSION_NAME} on port ${PORT}"
