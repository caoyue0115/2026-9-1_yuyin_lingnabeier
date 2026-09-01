#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${DISNEY_PROJECT_DIR:-$HOME/projects/disney-voice-assistant}"
PORT="${DISNEY_PORT:-18124}"
PID_FILE="${PROJECT_DIR}/data/run/disney_voice.pid"

if [[ -f "${PID_FILE}" ]]; then
  SERVICE_PID="$(cat "${PID_FILE}")"
  if kill -0 "${SERVICE_PID}" 2>/dev/null; then
    echo "running pid=${SERVICE_PID}"
  else
    echo "stale pid file: ${SERVICE_PID}"
  fi
else
  echo "not running"
fi
curl --fail --silent --show-error "http://127.0.0.1:${PORT}/healthz" || true
echo
