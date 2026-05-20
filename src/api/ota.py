from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.settings import settings
from src.storage.db import has_successful_ota_report_stage, list_ota_release_candidates, record_ota_report

OTA_POLL_INTERVAL_SEC = 3600
OTA_TARGET_ESP32S3 = "esp32s3"
# A successful P3c boot switch means this device has already consumed that
# exact release. Suppress only the same device_id + release_id pair so later
# releases, other devices, and P3a/P3b reports continue to work normally.
OTA_RELEASE_SUPPRESS_STAGES = ["boot_switch_scheduled", "post_reboot_confirm"]

router = APIRouter()


class OtaReportRequest(BaseModel):
    device_id: str
    target: str
    from_version: str | None = None
    to_version: str | None = None
    release_id: str | None = None
    stage: str
    ok: bool
    error_code: str | None = None
    error_message: str | None = None
    free_heap: int | None = None
    rssi: int | None = None
    http_status: int | None = None
    bytes_read: int | None = None
    expected_size: int | None = None
    sha256: str | None = None
    expected_sha256: str | None = None
    partition_label: str | None = None
    partition_subtype: int | None = None
    partition_address: int | None = None
    bytes_written: int | None = None
    boot_partition_before: str | None = None
    boot_partition_after_set: str | None = None
    running_partition_after_reboot: str | None = None
    reboot_reason: str | None = None
    previous_partition: str | None = None
    last_stage: str | None = None


def _version_key(version: str | None) -> tuple[int, ...]:
    if not version:
        return ()
    parts = re.findall(r"\d+", version)
    return tuple(int(part) for part in parts)


def _version_at_least(current: str | None, minimum: str | None) -> bool:
    if not minimum:
        return True
    current_key = _version_key(current)
    minimum_key = _version_key(minimum)
    if not current_key or not minimum_key:
        return current == minimum
    max_len = max(len(current_key), len(minimum_key))
    return current_key + (0,) * (max_len - len(current_key)) >= minimum_key + (0,) * (max_len - len(minimum_key))


def _release_matches(
    release: dict[str, Any],
    *,
    device_id: str,
    board: str | None,
    hw_rev: str | None,
    app_version: str | None,
) -> bool:
    if release["target"] != OTA_TARGET_ESP32S3:
        return False
    if not release["enabled"]:
        return False
    if device_id not in release.get("device_ids", []):
        return False
    if release.get("board") and release["board"] != board:
        return False
    if release.get("hw_rev") and release["hw_rev"] != hw_rev:
        return False
    if not release["force"] and not _version_at_least(app_version, release.get("min_version")):
        return False
    if has_successful_ota_report_stage(device_id, release["release_id"], OTA_RELEASE_SUPPRESS_STAGES):
        return False
    return bool(release.get("artifact_name") and release.get("sha256") and release.get("size"))


def _release_to_update(release: dict[str, Any]) -> dict[str, Any]:
    artifact_name = release["artifact_name"]
    return {
        "target": release["target"],
        "version": release["version"],
        "artifact": artifact_name,
        "url": f"{settings.public_base_url}/api/v5/ota/firmware/{artifact_name}",
        "size": release["size"],
        "sha256": release["sha256"],
        "force": bool(release["force"]),
        "min_version": release["min_version"],
        "release_id": release["release_id"],
        "notes": release["notes"],
    }


@router.get("/api/v5/ota/manifest")
def get_ota_manifest(
    device_id: str,
    board: str | None = None,
    hw_rev: str | None = None,
    app_version: str | None = None,
    idf_version: str | None = None,
    ota_slot: str | None = None,
    display_fw_version: str | None = None,
) -> dict[str, Any]:
    del idf_version, ota_slot, display_fw_version
    updates: list[dict[str, Any]] = []
    for release in list_ota_release_candidates():
        if _release_matches(release, device_id=device_id, board=board, hw_rev=hw_rev, app_version=app_version):
            updates.append(_release_to_update(release))
            break
    return {"device_id": device_id, "poll_interval_sec": OTA_POLL_INTERVAL_SEC, "updates": updates}


def _safe_ota_artifact_path(artifact_name: str) -> Path:
    if Path(artifact_name).name != artifact_name:
        raise HTTPException(status_code=404, detail="firmware not found")
    root = settings.ota_artifact_path.resolve()
    candidate = (root / artifact_name).resolve()
    if candidate.parent != root:
        raise HTTPException(status_code=404, detail="firmware not found")
    return candidate


@router.get("/api/v5/ota/firmware/{artifact_name:path}")
def get_ota_firmware(artifact_name: str) -> FileResponse:
    artifact_path = _safe_ota_artifact_path(artifact_name)
    if not artifact_path.is_file():
        raise HTTPException(status_code=404, detail="firmware not found")
    return FileResponse(artifact_path, media_type="application/octet-stream", filename=artifact_path.name)


def _report_to_dict(report: OtaReportRequest) -> dict[str, Any]:
    if hasattr(report, "model_dump"):
        return report.model_dump()
    return report.dict()


@router.post("/api/v5/ota/report", status_code=202)
def submit_ota_report(report: OtaReportRequest) -> dict[str, Any]:
    received_at = record_ota_report(_report_to_dict(report))
    return {"status": "accepted", "received_at": received_at}
