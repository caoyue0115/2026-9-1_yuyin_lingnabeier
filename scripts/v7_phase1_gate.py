from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


DEFAULT_APP_SIZE_LIMIT = 3 * 1024 * 1024


class GateError(RuntimeError):
    pass


def validate_artifacts(
    build_dir: Path,
    *,
    app_size_limit: int = DEFAULT_APP_SIZE_LIMIT,
) -> dict[str, Any]:
    build_dir = Path(build_dir)
    app_path = build_dir / "esp_idf_demo.bin"
    if not app_path.is_file():
        raise GateError("app_artifact_missing")
    compiled_config_path = build_dir / "config" / "sdkconfig.h"
    if not compiled_config_path.is_file():
        raise GateError("compiled_sdkconfig_missing")
    compiled_config = compiled_config_path.read_text(encoding="utf-8")
    required_profile_defines = (
        "#define CONFIG_DEMO_TARGET_PROFILE_VOCAT_LOWCOST_16M8M 1",
        "#define CONFIG_DEMO_AUDIO_PCB_ESP_VOCAT_V1_0 1",
    )
    if not all(item in compiled_config for item in required_profile_defines):
        raise GateError("compiled_n16r8_profile_missing")
    payload = app_path.read_bytes()
    app_bytes = len(payload)
    if app_bytes >= app_size_limit:
        raise GateError("app_size_limit_exceeded")
    return {
        "app_bytes": app_bytes,
        "app_remaining_bytes": app_size_limit - app_bytes,
        "app_sha256": hashlib.sha256(payload).hexdigest(),
        "compiled_profile": "vocat_lowcost_16m8m_audio_v1_0",
    }


def _read_required(path: Path) -> str:
    if not path.is_file():
        raise GateError(f"required_source_missing:{path.as_posix()}")
    return path.read_text(encoding="utf-8")


def validate_source_contract(root: Path) -> None:
    root = Path(root)
    main = _read_required(root / "esp_idf_demo" / "main" / "main.c")
    config = _read_required(root / "esp_idf_demo" / "main" / "config.h")
    credential_header = root / "esp_idf_demo" / "main" / "wifi_credential_store.h"
    credential_source = _read_required(credential_header) if credential_header.is_file() else config
    realtime = _read_required(root / "src" / "api" / "realtime_v6.py")

    required = {
        "v6_firmware_disabled": "DEMO_V6_CONVERSATION_ENABLED 1" in config,
        "wifi_credential_limit_invalid": "MAX_WIFI_CREDENTIALS = 5" in credential_source
        or "MAX_WIFI_CREDENTIALS 5" in credential_source,
        "conversation_controller_missing": "conversation_controller_handle" in main,
        "v6_websocket_route_missing": "/api/v6/realtime/conversation/opus-stream" in realtime,
    }
    for error, ok in required.items():
        if not ok:
            raise GateError(error)

    prepare = main.find("app_ota_rollback_prepare_before_network();")
    network = main.find("app_network_start()", prepare + 1)
    if prepare < 0 or network < 0 or prepare >= network:
        raise GateError("ota_watchdog_order_invalid")


def run_gate(root: Path, build_dir: Path) -> dict[str, Any]:
    validate_source_contract(root)
    report = validate_artifacts(build_dir)
    report.update({"gate": "v7_phase1", "status": "pass"})
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the sanitized v7 phase-1 release gate")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--build-dir", type=Path)
    args = parser.parse_args()
    build_dir = args.build_dir or args.root / "esp_idf_demo" / "build"
    try:
        report = run_gate(args.root, build_dir)
    except GateError as exc:
        print(json.dumps({"gate": "v7_phase1", "status": "fail", "error": str(exc)}))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
