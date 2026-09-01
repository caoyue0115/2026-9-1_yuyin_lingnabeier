#!/usr/bin/env bash
set -euo pipefail

SESSION_NAME="${DISNEY_SCREEN_SESSION:-disney_voice}"
PORT="${DISNEY_PORT:-18120}"

screen -ls 2>/dev/null | grep "\.${SESSION_NAME}[[:space:]]" || true
curl --fail --silent --show-error "http://127.0.0.1:${PORT}/healthz" || true
echo
