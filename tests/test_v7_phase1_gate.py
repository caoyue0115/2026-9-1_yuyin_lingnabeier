from __future__ import annotations

from pathlib import Path

import pytest

from scripts.v7_phase1_gate import GateError, validate_artifacts, validate_source_contract


def _write_compiled_profile(build: Path, *, enabled: bool = True) -> None:
    config = build / "config"
    config.mkdir(parents=True, exist_ok=True)
    value = "1" if enabled else "0"
    (config / "sdkconfig.h").write_text(
        f"#define CONFIG_DEMO_TARGET_PROFILE_VOCAT_LOWCOST_16M8M {value}\n"
        f"#define CONFIG_DEMO_AUDIO_PCB_ESP_VOCAT_V1_0 {value}\n",
        encoding="utf-8",
    )


def test_gate_rejects_oversized_firmware(tmp_path: Path) -> None:
    build = tmp_path / "build"
    build.mkdir()
    (build / "esp_idf_demo.bin").write_bytes(b"x" * 17)
    _write_compiled_profile(build)

    with pytest.raises(GateError, match="app_size_limit_exceeded"):
        validate_artifacts(build, app_size_limit=16)


def test_gate_reports_public_artifact_hash(tmp_path: Path) -> None:
    build = tmp_path / "build"
    build.mkdir()
    (build / "esp_idf_demo.bin").write_bytes(b"firmware")
    _write_compiled_profile(build)

    report = validate_artifacts(build, app_size_limit=1024)

    assert report["app_bytes"] == 8
    assert len(report["app_sha256"]) == 64
    assert report["app_remaining_bytes"] == 1016


def test_gate_rejects_non_n16r8_compiled_profile(tmp_path: Path) -> None:
    build = tmp_path / "build"
    build.mkdir()
    (build / "esp_idf_demo.bin").write_bytes(b"firmware")
    _write_compiled_profile(build, enabled=False)

    with pytest.raises(GateError, match="compiled_n16r8_profile_missing"):
        validate_artifacts(build, app_size_limit=1024)


def test_source_contract_requires_v6_controller_wifi_and_ota_order(tmp_path: Path) -> None:
    main = tmp_path / "esp_idf_demo" / "main"
    server = tmp_path / "src" / "api"
    main.mkdir(parents=True)
    server.mkdir(parents=True)
    (main / "config.h").write_text(
        "MAX_WIFI_CREDENTIALS 5\nDEMO_V6_CONVERSATION_ENABLED 1\n",
        encoding="utf-8",
    )
    (main / "main.c").write_text(
        "app_ota_rollback_prepare_before_network();\n"
        "app_network_start();\n"
        "conversation_controller_handle();\n",
        encoding="utf-8",
    )
    (server / "realtime_v6.py").write_text(
        "@router.websocket('/api/v6/realtime/conversation/opus-stream')\n",
        encoding="utf-8",
    )

    validate_source_contract(tmp_path)

    (main / "main.c").write_text(
        "app_network_start();\n"
        "app_ota_rollback_prepare_before_network();\n"
        "conversation_controller_handle();\n",
        encoding="utf-8",
    )
    with pytest.raises(GateError, match="ota_watchdog_order_invalid"):
        validate_source_contract(tmp_path)
