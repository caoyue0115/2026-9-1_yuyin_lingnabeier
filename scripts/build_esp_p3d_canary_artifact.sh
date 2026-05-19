#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_DIR="${SRC_DIR:-/tmp/v36_p3d_artifact_src}"
BUILD_DIR="${BUILD_DIR:-/tmp/v36_p3d_artifact_build}"
OUT_BIN="${OUT_BIN:-${ROOT_DIR}/tmp/esp_idf_demo_v36_p3d_002_20260519.bin}"

IDF_PATH="${IDF_PATH:-/data/esp/esp-idf-v5.5.4-full}"
IDF_TOOLS_PATH="${IDF_TOOLS_PATH:-/data/esp/tools}"
PROJECT_VER=${PROJECT_VER:-v36-p3d-canary}

CANARY_WIFI_SSID="${CANARY_WIFI_SSID:-GMT-G60}"
CANARY_SERVER_BASE_URL="${CANARY_SERVER_BASE_URL:-http://106.54.240.51}"
CANARY_DEVICE_ID=${CANARY_DEVICE_ID:-miaoban-v1p2-002}

rm -rf "${SRC_DIR}" "${BUILD_DIR}"
mkdir -p "${SRC_DIR}" "$(dirname "${OUT_BIN}")"

tar \
  --exclude='esp_idf_demo/build' \
  --exclude='esp_idf_demo/managed_components' \
  --exclude='esp_idf_demo/**/__pycache__' \
  --exclude='esp_idf_demo/**/*.pyc' \
  -cf - -C "${ROOT_DIR}" esp_idf_demo | tar -xf - -C "${SRC_DIR}"

ln -s "${ROOT_DIR}/esp_idf_demo/managed_components" "${SRC_DIR}/esp_idf_demo/managed_components"

CONFIG_H="${SRC_DIR}/esp_idf_demo/main/config.h"
perl -0pi -e 's/#define DEMO_OTA_BOOT_SWITCH_ENABLED 0/#define DEMO_OTA_BOOT_SWITCH_ENABLED 1/' "${CONFIG_H}"
perl -0pi -e 's/#define DEMO_OTA_ROLLBACK_VALIDATION_ENABLED 0/#define DEMO_OTA_ROLLBACK_VALIDATION_ENABLED 1/' "${CONFIG_H}"
perl -0pi -e "s/#define DEMO_WIFI_SSID\s+\"\"/#define DEMO_WIFI_SSID           \"${CANARY_WIFI_SSID}\"/" "${CONFIG_H}"
perl -0pi -e "s|#define DEMO_SERVER_BASE_URL\s+\"\"|#define DEMO_SERVER_BASE_URL     \"${CANARY_SERVER_BASE_URL}\"|" "${CONFIG_H}"
perl -0pi -e "s/#define DEMO_DEVICE_ID\s+\"\"/#define DEMO_DEVICE_ID           \"${CANARY_DEVICE_ID}\"/" "${CONFIG_H}"
cat >> "${SRC_DIR}/esp_idf_demo/sdkconfig.defaults" <<'EOF'
CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y
CONFIG_APP_ROLLBACK_ENABLE=y
EOF

export PATH=/usr/bin:/bin:/usr/sbin:/sbin
export IDF_TOOLS_PATH
export IDF_PATH
export IDF_PATH_FORCE=1

# shellcheck disable=SC1091
. "${IDF_PATH}/export.sh"

idf.py -C "${SRC_DIR}/esp_idf_demo" -B "${BUILD_DIR}" -D "PROJECT_VER=${PROJECT_VER}" build
cp "${BUILD_DIR}/esp_idf_demo.bin" "${OUT_BIN}"

stat -c 'path=%n bytes=%s' "${OUT_BIN}"
sha256sum "${OUT_BIN}"
