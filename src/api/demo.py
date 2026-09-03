from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from src.services.demo_diagnostics import demo_diagnostics
from src.services.park_navigation import (
    build_navigation_answer,
    list_park_pois,
    match_destination,
    phone_locations,
)
from src.settings import settings


router = APIRouter()
_WEB_DIR = Path(__file__).resolve().parents[1] / "web"


class PhoneLocationUpdate(BaseModel):
    device_id: str = Field(min_length=1, max_length=80)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy: float | None = Field(default=None, ge=0, le=100_000)


class DeviceTelemetryUpdate(BaseModel):
    device_id: str = Field(min_length=1, max_length=80)
    wifi_rssi: int | None = Field(default=None, ge=-127, le=0)
    free_internal_ram: int | None = Field(default=None, ge=0)
    largest_internal_block: int | None = Field(default=None, ge=0)
    restart_reason: str | None = Field(default=None, max_length=80)
    direction_degrees: int | None = Field(default=None, ge=0, le=180)
    direction_label: str | None = Field(default=None, max_length=32)
    state: str | None = Field(default=None, max_length=32)


def _html_page(name: str) -> HTMLResponse:
    response = HTMLResponse((_WEB_DIR / name).read_text(encoding="utf-8"))
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/demo", response_class=HTMLResponse, include_in_schema=False)
def demo_console() -> HTMLResponse:
    return _html_page("demo_console.html")


@router.get("/park", response_class=HTMLResponse, include_in_schema=False)
def park_guide() -> HTMLResponse:
    return _html_page("park_guide.html")


@router.get("/api/demo/status", tags=["demo"])
def demo_status() -> dict[str, Any]:
    snapshot = demo_diagnostics.snapshot()
    for device in snapshot["devices"]:
        fix = phone_locations.get(device["device_id"], include_stale=True)
        device["phone_location"] = fix.public_dict() if fix else None
    snapshot.update(
        {
            "service": settings.project_name,
            "models": {
                "asr": settings.asr_model,
                "llm": settings.llm_model,
                "tts": settings.realtime_tts_model or settings.dashscope_tts_model,
            },
            "memory_turns": min(max(settings.conversation_v6_memory_turns, 0), 5),
        }
    )
    return snapshot


@router.get("/api/demo/devices", tags=["demo"])
def demo_devices() -> dict[str, Any]:
    devices = [item["device_id"] for item in demo_diagnostics.snapshot()["devices"]]
    if "disney-vocat-demo-001" not in devices:
        devices.append("disney-vocat-demo-001")
    return {"devices": devices, "pois": list_park_pois()}


@router.post("/api/demo/location", tags=["demo"])
def update_phone_location(update: PhoneLocationUpdate) -> dict[str, Any]:
    try:
        fix = phone_locations.update(
            update.device_id,
            update.latitude,
            update.longitude,
            update.accuracy,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    demo_diagnostics.record(
        "phone_location",
        device_id=update.device_id,
        latitude=fix.latitude,
        longitude=fix.longitude,
        accuracy=fix.accuracy,
    )
    return {"status": "ok", "location": fix.public_dict()}


@router.get("/api/demo/navigation", tags=["demo"])
def demo_navigation(device_id: str, destination: str) -> dict[str, Any]:
    poi = match_destination(destination)
    if poi is None:
        raise HTTPException(status_code=404, detail="destination_not_found")
    fix = phone_locations.get(device_id)
    if fix is None:
        raise HTTPException(status_code=409, detail="phone_location_missing_or_stale")
    return {
        "status": "ok",
        "destination": poi.name,
        "answer": build_navigation_answer(fix, poi),
    }


@router.post("/api/demo/telemetry", tags=["demo"])
def update_device_telemetry(update: DeviceTelemetryUpdate) -> dict[str, str]:
    values = update.model_dump(exclude={"device_id"}, exclude_none=True)
    demo_diagnostics.update_telemetry(update.device_id, values)
    return {"status": "ok"}
