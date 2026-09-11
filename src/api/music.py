from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from src.settings import settings


router = APIRouter()

TRACK_ID = "try-everything"
TRACK_TITLE = "Try Everything"
TRACK_ARTIST = "Shakira"
TRACK_FILENAME = "try-everything.fopus"
STREAM_CHUNK_BYTES = 16 * 1024


def _track_path() -> Path:
    return settings.music_asset_path / TRACK_FILENAME


def _iter_track(path: Path) -> Iterator[bytes]:
    with path.open("rb") as handle:
        while chunk := handle.read(STREAM_CHUNK_BYTES):
            yield chunk


@router.get("/api/v1/music/tracks")
def list_music_tracks() -> dict:
    track_path = _track_path()
    return {
        "tracks": [
            {
                "id": TRACK_ID,
                "title": TRACK_TITLE,
                "artist": TRACK_ARTIST,
                "available": track_path.is_file(),
                "stream_url": f"{settings.public_base_url}/api/v1/music/{TRACK_ID}/audio",
            }
        ]
    }


@router.get(f"/api/v1/music/{TRACK_ID}/audio")
def stream_music_track() -> StreamingResponse:
    track_path = _track_path()
    if not track_path.is_file():
        raise HTTPException(status_code=404, detail="music_track_not_ready")
    return StreamingResponse(
        _iter_track(track_path),
        media_type="application/octet-stream",
        headers={
            "Content-Length": str(track_path.stat().st_size),
            "Cache-Control": "public, max-age=86400",
            "X-Audio-Format": "opus",
            "X-Audio-Packetization": "framed-v1",
            "X-Opus-Sample-Rate": "16000",
            "X-Opus-Channels": "1",
            "X-Opus-Frame-Duration-Ms": "60",
        },
    )
