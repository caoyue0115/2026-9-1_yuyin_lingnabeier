from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import threading
import time
from typing import Any

import requests

from src.settings import settings


@dataclass(frozen=True, slots=True)
class ParkPoi:
    key: str
    name: str
    latitude: float
    longitude: float
    aliases: tuple[str, ...]


# WGS-84 positions from OpenStreetMap. Convert only for AMap requests; browser
# location and the offline direction fallback remain in WGS-84.
PARK_POIS: tuple[ParkPoi, ...] = (
    ParkPoi("zootopia_hot_pursuit", "疯狂动物城：热力追踪", 31.14886, 121.65526,
            ("热力追踪", "疯狂动物城", "动物城", "朱迪", "尼克")),
    ParkPoi("storybook_castle", "奇幻童话城堡", 31.14574, 121.65533,
            ("城堡", "童话城堡")),
    ParkPoi("tron", "创极速光轮", 31.14424, 121.65179,
            ("创极速", "极速光轮", "光轮", "TRON", "tron")),
    ParkPoi("pirates", "加勒比海盗——沉落宝藏之战", 31.14823, 121.65818,
            ("加勒比海盗", "沉落宝藏", "宝藏之战")),
    ParkPoi("seven_dwarfs", "七个小矮人矿山车", 31.14764, 121.65549,
            ("七个小矮人", "小矮人矿山车", "矿山车")),
    ParkPoi("roaring_rapids", "雷鸣山漂流", 31.14494, 121.65926,
            ("雷鸣山", "漂流")),
)


@dataclass(frozen=True, slots=True)
class LocationFix:
    device_id: str
    latitude: float
    longitude: float
    accuracy: float | None
    received_at: float

    def public_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["age_seconds"] = max(0, round(time.time() - self.received_at, 1))
        return data


class PhoneLocationRegistry:
    def __init__(self) -> None:
        self._locations: dict[str, LocationFix] = {}
        self._lock = threading.RLock()

    def update(
        self,
        device_id: str,
        latitude: float,
        longitude: float,
        accuracy: float | None = None,
    ) -> LocationFix:
        normalized_id = str(device_id or "").strip()
        if not normalized_id:
            raise ValueError("missing_device_id")
        latitude = float(latitude)
        longitude = float(longitude)
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError("invalid_coordinates")
        normalized_accuracy = None if accuracy is None else max(0.0, float(accuracy))
        fix = LocationFix(
            device_id=normalized_id,
            latitude=latitude,
            longitude=longitude,
            accuracy=normalized_accuracy,
            received_at=time.time(),
        )
        with self._lock:
            self._locations[normalized_id] = fix
        return fix

    def get(self, device_id: str, *, include_stale: bool = False) -> LocationFix | None:
        with self._lock:
            fix = self._locations.get(str(device_id or "").strip())
        if fix is None:
            return None
        ttl = max(5, int(settings.phone_location_ttl_seconds))
        if not include_stale and time.time() - fix.received_at > ttl:
            return None
        return fix

    def reset(self) -> None:
        with self._lock:
            self._locations.clear()


phone_locations = PhoneLocationRegistry()

_NAVIGATION_MARKERS = (
    "怎么走", "怎么去", "带我去", "导航", "路线", "往哪", "在哪个方向", "离我多远"
)


def list_park_pois() -> list[dict[str, Any]]:
    return [
        {"key": poi.key, "name": poi.name, "latitude": poi.latitude, "longitude": poi.longitude}
        for poi in PARK_POIS
    ]


def match_destination(value: str) -> ParkPoi | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    for poi in PARK_POIS:
        if normalized == poi.key or poi.name in normalized:
            return poi
        if any(alias in normalized for alias in poi.aliases):
            return poi
    return None


def is_navigation_question(question: str) -> bool:
    normalized = str(question or "").strip()
    return any(marker in normalized for marker in _NAVIGATION_MARKERS)


def answer_navigation_question(question: str, device_id: str) -> str | None:
    if not is_navigation_question(question):
        return None
    destination = match_destination(question)
    if destination is None:
        return "没问题！请再告诉我想去哪个项目，比如热力追踪、城堡或创极速光轮。"
    fix = phone_locations.get(device_id)
    if fix is None:
        return "我还没收到手机位置。请先打开手机定位页、选中这台设备并允许定位，然后再问我怎么走。"
    return build_navigation_answer(fix, destination)


def build_navigation_answer(fix: LocationFix, destination: ParkPoi) -> str:
    if settings.amap_web_service_key.strip():
        amap = _amap_walking_route(fix, destination)
        if amap:
            return amap
    distance = round(_haversine_meters(
        fix.latitude, fix.longitude, destination.latitude, destination.longitude
    ))
    direction = _bearing_label(_initial_bearing(
        fix.latitude, fix.longitude, destination.latitude, destination.longitude
    ))
    accuracy_note = " 手机定位目前有点飘，" if fix.accuracy is not None and fix.accuracy > 40 else ""
    return (
        f"收到！{destination.name}直线大约{distance}米，在你现在的{direction}方向。"
        f"{accuracy_note}这版是方向提示，不是逐路口导航，路口请同时看园区地图。"
    )


def _amap_walking_route(fix: LocationFix, destination: ParkPoi) -> str | None:
    origin_lon, origin_lat = _wgs84_to_gcj02(fix.longitude, fix.latitude)
    destination_lon, destination_lat = _wgs84_to_gcj02(destination.longitude, destination.latitude)
    try:
        response = requests.get(
            "https://restapi.amap.com/v3/direction/walking",
            params={
                "key": settings.amap_web_service_key.strip(),
                "origin": f"{origin_lon:.6f},{origin_lat:.6f}",
                "destination": f"{destination_lon:.6f},{destination_lat:.6f}",
            },
            timeout=4,
        )
        response.raise_for_status()
        payload = response.json()
        paths = payload.get("route", {}).get("paths", []) if payload.get("status") == "1" else []
        if not paths:
            return None
        path = paths[0]
        distance = int(float(path.get("distance") or 0))
        minutes = max(1, round(float(path.get("duration") or 0) / 60))
        instructions = [
            str(step.get("instruction") or "").strip()
            for step in path.get("steps", [])
            if str(step.get("instruction") or "").strip()
        ]
        first_step = instructions[0] if instructions else "按园区步道前进"
        return (
            f"收到！去{destination.name}步行约{distance}米，大约{minutes}分钟。"
            f"先{first_step}，之后到路口再问我，我会用手机的新位置继续带路。"
        )
    except (requests.RequestException, ValueError, TypeError, KeyError):
        return None


def _haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    value = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def _initial_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def _bearing_label(bearing: float) -> str:
    labels = ("正北", "东北", "正东", "东南", "正南", "西南", "正西", "西北")
    return labels[int((bearing + 22.5) // 45) % 8]


def _wgs84_to_gcj02(longitude: float, latitude: float) -> tuple[float, float]:
    if not (72.004 <= longitude <= 137.8347 and 0.8293 <= latitude <= 55.8271):
        return longitude, latitude
    semimajor = 6378245.0
    eccentricity = 0.006693421622965943
    delta_lat = _transform_lat(longitude - 105.0, latitude - 35.0)
    delta_lon = _transform_lon(longitude - 105.0, latitude - 35.0)
    rad_lat = math.radians(latitude)
    magic = 1 - eccentricity * math.sin(rad_lat) ** 2
    sqrt_magic = math.sqrt(magic)
    delta_lat = delta_lat * 180 / (((semimajor * (1 - eccentricity)) / (magic * sqrt_magic)) * math.pi)
    delta_lon = delta_lon * 180 / ((semimajor / sqrt_magic) * math.cos(rad_lat) * math.pi)
    return longitude + delta_lon, latitude + delta_lat


def _transform_lat(x: float, y: float) -> float:
    value = -100 + 2*x + 3*y + 0.2*y*y + 0.1*x*y + 0.2*math.sqrt(abs(x))
    value += (20*math.sin(6*x*math.pi) + 20*math.sin(2*x*math.pi)) * 2/3
    value += (20*math.sin(y*math.pi) + 40*math.sin(y/3*math.pi)) * 2/3
    value += (160*math.sin(y/12*math.pi) + 320*math.sin(y*math.pi/30)) * 2/3
    return value


def _transform_lon(x: float, y: float) -> float:
    value = 300 + x + 2*y + 0.1*x*x + 0.1*x*y + 0.1*math.sqrt(abs(x))
    value += (20*math.sin(6*x*math.pi) + 20*math.sin(2*x*math.pi)) * 2/3
    value += (20*math.sin(x*math.pi) + 40*math.sin(x/3*math.pi)) * 2/3
    value += (150*math.sin(x/12*math.pi) + 300*math.sin(x/30*math.pi)) * 2/3
    return value
