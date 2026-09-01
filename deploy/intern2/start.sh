#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${DISNEY_PROJECT_DIR:-$HOME/projects/disney-voice-assistant}"
PORT="${DISNEY_PORT:-18120}"
RUN_DIR="${PROJECT_DIR}/data/run"
PID_FILE="${RUN_DIR}/disney_voice.pid"

if [[ ! -f "${PROJECT_DIR}/.env" ]]; then
  echo "missing ${PROJECT_DIR}/.env; copy .env.example and configure it first" >&2
  exit 1
fi
if [[ -f "${PID_FILE}" ]]; then
  EXISTING_PID="$(cat "${PID_FILE}")"
  if kill -0 "${EXISTING_PID}" 2>/dev/null; then
    echo "Disney voice service is already running as PID ${EXISTING_PID}" >&2
    exit 1
  fi
  rm -f "${PID_FILE}"
fi

mkdir -p "${PROJECT_DIR}/data/logs" "${RUN_DIR}"
cd "${PROJECT_DIR}"
nohup .venv/bin/uvicorn src.app:app --host 0.0.0.0 --port "${PORT}" \
  >> data/logs/server.log 2>&1 < /dev/null &
SERVICE_PID=$!
echo "${SERVICE_PID}" > "${PID_FILE}"

echo "started Disney voice service as PID ${SERVICE_PID} on port ${PORT}"
