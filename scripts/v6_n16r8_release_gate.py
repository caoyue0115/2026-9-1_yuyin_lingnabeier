#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path


OTA_SLOT_BYTES = 3 * 1024 * 1024
DEFAULT_ALLOWED_DEVICE = "miaoban-v1p2-002"
DEFAULT_BLOCKED_DEVICES = ("miaoban-v1p2-003", "miaoban-v1p2-004")


class GateFailure(Exception):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise GateFailure(message)


def _read_json_url(url: str, timeout_sec: float) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=timeout_sec) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.URLError as exc:
        raise GateFailure(f"manifest request failed: {url}: {exc}") from exc
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise GateFailure(f"manifest response is not JSON: {url}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise GateFailure(f"manifest response is not an object: {url}")
    return parsed


def check_artifact(path: Path, expected_sha256: str | None, max_bytes: int) -> list[str]:
    _require(path.is_file(), f"artifact is not a file: {path}")
    size = path.stat().st_size
    _require(size > 0, f"artifact is empty: {path}")
    _require(size < max_bytes, f"artifact size {size} exceeds OTA slot {max_bytes}")
    actual_sha = _sha256_file(path)
    if expected_sha256:
        _require(
            actual_sha == expected_sha256,
            f"artifact sha256 mismatch: expected {expected_sha256} got {actual_sha}",
        )
    return [f"artifact_bytes={size}", f"artifact_sha256={actual_sha}"]


def check_log(
    log_path: Path,
    *,
    expected_version: str,
    require_ota_success: bool,
) -> list[str]:
    text = log_path.read_text(encoding="utf-8", errors="replace")
    required_patterns = {
        "app_version": rf"App version:\s+{re.escape(expected_version)}",
        "board_v1_0": r"Board: ESP-VoCat v1\.0",
        "target_profile": r"target_profile=vocat_lowcost_16m8m",
        "audio_pcb": r"audio_pcb_rev=v1\.0",
        "audio_i2s_din": r"audio_i2s_din_gpio=15",
        "audio_pa": r"audio_pa_gpio=4",
        "audio_gpio48": r"audio_gpio48_enable=0",
        "wifi_ssid": r"wifi_ssid=GMT-G60",
        "server_base_url": r"server_base_url=http://106\.54\.240\.51",
        "ota_boot_switch": r"ota_boot_switch_enabled=1",
        "ota_rollback_validation": r"ota_rollback_validation_enabled=1",
    }
    if require_ota_success:
        required_patterns["ota_post_reboot_success"] = (
            r"stage=ota_post_reboot_confirm event=(success|done|validated)"
        )
    for name, pattern in required_patterns.items():
        _require(re.search(pattern, text), f"log missing required marker: {name}")
    forbidden_patterns = {
        "empty_wifi_ssid": r"DEMO_WIFI_SSID is empty|wifi_ssid=\s*$",
        "empty_server_base_url": r"server_base_url=\s*$",
        "v1_2_audio_binding": (
            r"audio_pcb_rev=v1\.2|audio_i2s_din_gpio=3|audio_pa_gpio=15|audio_gpio48_enable=1"
        ),
        "ota_recovered": r"stage=ota_rollback event=recovered",
        "ota_confirm_failed": r"stage=ota_post_reboot_confirm event=failed",
    }
    for name, pattern in forbidden_patterns.items():
        _require(not re.search(pattern, text, re.MULTILINE), f"log contains forbidden marker: {name}")
    return [f"log_checked={log_path}"]


def _manifest_url(
    base_url: str,
    *,
    device_id: str,
    app_version: str,
    board: str,
    hw_rev: str,
) -> str:
    from urllib.parse import urlencode

    query = urlencode(
        {
            "device_id": device_id,
            "app_version": app_version,
            "board": board,
            "hw_rev": hw_rev,
        }
    )
    return f"{base_url.rstrip('/')}/api/v5/ota/manifest?{query}"


def check_manifest(
    base_url: str,
    *,
    allowed_device: str,
    allowed_device_mode: str,
    blocked_devices: list[str],
    baseline_version: str,
    board: str,
    hw_rev: str,
    expected_release_id: str,
    expected_version: str,
    expected_artifact: str,
    expected_sha256: str,
    expected_size: int,
    timeout_sec: float,
) -> list[str]:
    allowed_url = _manifest_url(
        base_url,
        device_id=allowed_device,
        app_version=baseline_version,
        board=board,
        hw_rev=hw_rev,
    )
    allowed_payload = _read_json_url(allowed_url, timeout_sec)
    updates = allowed_payload.get("updates")
    _require(isinstance(updates, list), "allowed-device manifest updates is not a list")
    if allowed_device_mode == "no-update":
        _require(updates == [], f"allowed device {allowed_device} unexpectedly still has updates")
        checked = [f"manifest_allowed_no_update={allowed_device}"]
    else:
        _require(len(updates) == 1, f"allowed-device manifest expected 1 update, got {len(updates)}")
        update = updates[0]
        _require(update.get("release_id") == expected_release_id, "manifest release_id mismatch")
        _require(update.get("version") == expected_version, "manifest version mismatch")
        _require(update.get("artifact") == expected_artifact, "manifest artifact mismatch")
        _require(update.get("sha256") == expected_sha256, "manifest sha256 mismatch")
        _require(update.get("size") == expected_size, "manifest size mismatch")
        _require(update.get("min_version") == baseline_version, "manifest min_version mismatch")
        checked = [f"manifest_allowed_update={allowed_device}"]

    for device_id in blocked_devices:
        blocked_url = _manifest_url(
            base_url,
            device_id=device_id,
            app_version=baseline_version,
            board=board,
            hw_rev=hw_rev,
        )
        blocked_payload = _read_json_url(blocked_url, timeout_sec)
        blocked_updates = blocked_payload.get("updates")
        _require(blocked_updates == [], f"blocked device {device_id} unexpectedly has updates")
        checked.append(f"manifest_blocked={device_id}")
    return checked


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gate v6 N16R8 OTA release artifacts and manifests.")
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--expected-release-id")
    parser.add_argument("--expected-artifact-name")
    parser.add_argument("--baseline-version", default="v6-n16r8-002-ota-baseline")
    parser.add_argument("--allowed-device", default=DEFAULT_ALLOWED_DEVICE)
    parser.add_argument("--blocked-device", action="append", default=list(DEFAULT_BLOCKED_DEVICES))
    parser.add_argument("--board", default="ESP-VoCat")
    parser.add_argument("--hw-rev", default="v1.0")
    parser.add_argument("--manifest-base-url")
    parser.add_argument(
        "--allowed-device-mode",
        choices=("update", "no-update"),
        default="update",
        help="Use no-update after the allowed device has already consumed the release.",
    )
    parser.add_argument("--manifest-timeout-sec", type=float, default=8.0)
    parser.add_argument("--log", type=Path)
    parser.add_argument("--require-ota-success", action="store_true")
    parser.add_argument("--max-bytes", type=int, default=OTA_SLOT_BYTES)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    checks: list[str] = []

    try:
        artifact_size: int | None = None
        artifact_sha: str | None = None
        artifact_name: str | None = None
        if args.artifact:
            checks.extend(check_artifact(args.artifact, args.expected_sha256, args.max_bytes))
            artifact_size = args.artifact.stat().st_size
            artifact_sha = _sha256_file(args.artifact)
            artifact_name = args.artifact.name
        elif args.manifest_base_url:
            missing = [
                name
                for name, value in [
                    ("--expected-sha256", args.expected_sha256),
                    ("--expected-artifact-name", args.expected_artifact_name),
                ]
                if not value
            ]
            _require(not missing, f"manifest-only gate requires {', '.join(missing)}")

        if args.log:
            checks.extend(
                check_log(
                    args.log,
                    expected_version=args.expected_version,
                    require_ota_success=args.require_ota_success,
                )
            )

        if args.manifest_base_url:
            _require(args.expected_release_id is not None, "manifest gate requires --expected-release-id")
            expected_sha = artifact_sha or args.expected_sha256
            expected_name = artifact_name or args.expected_artifact_name
            _require(expected_sha is not None, "manifest gate requires an expected sha256")
            _require(expected_name is not None, "manifest gate requires an expected artifact name")
            _require(artifact_size is not None, "manifest gate currently requires --artifact for expected size")
            checks.extend(
                check_manifest(
                    args.manifest_base_url,
                    allowed_device=args.allowed_device,
                    allowed_device_mode=args.allowed_device_mode,
                    blocked_devices=args.blocked_device,
                    baseline_version=args.baseline_version,
                    board=args.board,
                    hw_rev=args.hw_rev,
                    expected_release_id=args.expected_release_id,
                    expected_version=args.expected_version,
                    expected_artifact=expected_name,
                    expected_sha256=expected_sha,
                    expected_size=artifact_size,
                    timeout_sec=args.manifest_timeout_sec,
                )
            )
    except GateFailure as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2

    print("PASS: v6 N16R8 release gate")
    for check in checks:
        print(check)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
