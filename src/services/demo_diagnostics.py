from __future__ import annotations

from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
import threading
from typing import Any


MAX_RECENT_EVENTS = 100


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class DemoDiagnostics:
    """Small in-memory event store for the single-device demonstration console."""

    def __init__(self, *, max_events: int = MAX_RECENT_EVENTS) -> None:
        self._events: deque[dict[str, Any]] = deque(maxlen=max_events)
        self._devices: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def record(
        self,
        event: str,
        *,
        device_id: str = "",
        conversation_id: str = "",
        turn_id: str = "",
        turn_index: int | None = None,
        **details: Any,
    ) -> None:
        timestamp = _utc_now()
        item: dict[str, Any] = {
            "timestamp": timestamp,
            "event": str(event),
            "device_id": str(device_id or ""),
            "conversation_id": str(conversation_id or ""),
            "turn_id": str(turn_id or ""),
            "turn_index": turn_index,
        }
        item.update(details)
        with self._lock:
            self._events.append(item)
            if device_id:
                device = self._devices.setdefault(
                    device_id,
                    {
                        "device_id": device_id,
                        "online": False,
                        "last_seen": timestamp,
                        "conversation_id": "",
                        "state": "unknown",
                        "turn_index": None,
                        "asr_text": "",
                        "answer": "",
                        "memory": [],
                        "direction_degrees": None,
                        "direction_label": "unknown",
                        "wifi_rssi": None,
                        "free_internal_ram": None,
                        "largest_internal_block": None,
                        "restart_reason": "",
                    },
                )
                device["last_seen"] = timestamp
                if conversation_id:
                    device["conversation_id"] = conversation_id
                if turn_index is not None:
                    device["turn_index"] = turn_index
                for key, value in details.items():
                    if key in device:
                        device[key] = deepcopy(value)

    def set_connected(self, device_id: str, conversation_id: str) -> None:
        self.record(
            "device_connected",
            device_id=device_id,
            conversation_id=conversation_id,
            online=True,
            state="connected",
            asr_text="",
            answer="",
            memory=[],
        )
        with self._lock:
            self._devices[device_id]["turn_index"] = None

    def set_disconnected(self, device_id: str, conversation_id: str) -> None:
        self.record(
            "device_disconnected",
            device_id=device_id,
            conversation_id=conversation_id,
            online=False,
            state="offline",
        )

    def update_telemetry(self, device_id: str, values: dict[str, Any]) -> None:
        allowed = {
            "wifi_rssi",
            "free_internal_ram",
            "largest_internal_block",
            "restart_reason",
            "direction_degrees",
            "direction_label",
            "state",
        }
        sanitized = {key: values[key] for key in allowed if key in values}
        self.record("device_telemetry", device_id=device_id, **sanitized)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "generated_at": _utc_now(),
                "devices": deepcopy(list(self._devices.values())),
                "recent_events": deepcopy(list(reversed(self._events))),
            }

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
            self._devices.clear()


demo_diagnostics = DemoDiagnostics()
