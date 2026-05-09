from __future__ import annotations

import logging
import time
import uuid

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

from src.models.realtime import RealtimeSessionAcceptedResponse, RealtimeSessionStatusResponse
from src.providers.opus import (
    OpusError,
    decode_framed_opus_to_pcm,
    encode_pcm_stream_to_framed_opus,
    opus_available,
)
from src.services.realtime_session import start_realtime_session
from src.settings import settings
from src.storage.files import save_pcm_as_wav
from src.storage.realtime_store import InMemoryRealtimeSessionStore

logger = logging.getLogger(__name__)

router = APIRouter()
store = InMemoryRealtimeSessionStore(
    base_url=settings.public_base_url,
    ttl_seconds=settings.realtime_session_ttl_seconds,
)


def _frame_audio_packets(chunks):
    sequence = 0
    for chunk in chunks:
        if not chunk:
            continue
        yield sequence.to_bytes(4, "big") + len(chunk).to_bytes(4, "big") + chunk
        sequence += 1


@router.post("/api/v3/realtime/sessions", response_model=RealtimeSessionAcceptedResponse, status_code=202)
async def create_realtime_session(
    request: Request,
    x_device_id: str = Header(...),
    x_sample_rate: int = Header(default=settings.realtime_audio_sample_rate),
    x_sample_width: int = Header(default=settings.realtime_audio_sample_width_bits),
    x_channels: int = Header(default=settings.realtime_audio_channels),
) -> RealtimeSessionAcceptedResponse:
    if request.headers.get("content-type") != "application/octet-stream":
        raise HTTPException(status_code=400, detail="invalid_request")
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="empty_audio_body")
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(body) > max_bytes:
        raise HTTPException(status_code=413, detail="audio_too_large")

    wav_path = save_pcm_as_wav(body, x_sample_rate, x_sample_width, x_channels)
    session = store.create_session(device_id=x_device_id, input_wav_path=str(wav_path))
    start_realtime_session(store, session["session_id"])
    return RealtimeSessionAcceptedResponse(
        status="accepted",
        session_id=session["session_id"],
        received_at=session["created_at"],
        audio_stream_url=session["audio_stream_url"],
    )


@router.post("/api/v5/realtime/opus-sessions", response_model=RealtimeSessionAcceptedResponse, status_code=202)
async def create_opus_realtime_session(
    request: Request,
    x_device_id: str = Header(...),
    x_audio_packetization: str = Header(default="framed-v1"),
    x_audio_format: str = Header(default="opus"),
    x_opus_sample_rate: int = Header(default=settings.realtime_audio_opus_sample_rate),
    x_opus_channels: int = Header(default=settings.realtime_audio_opus_channels),
    x_opus_frame_duration_ms: int = Header(default=settings.realtime_audio_opus_frame_duration_ms),
    x_original_pcm_bytes: int | None = Header(default=None),
) -> RealtimeSessionAcceptedResponse:
    if request.headers.get("content-type") != "application/octet-stream":
        raise HTTPException(status_code=400, detail="invalid_request")
    if x_audio_packetization != "framed-v1":
        raise HTTPException(status_code=400, detail="invalid_packetization")
    if x_audio_format != "opus":
        raise HTTPException(status_code=400, detail="invalid_audio_format")
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="empty_opus_body")
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(body) > max_bytes:
        raise HTTPException(status_code=413, detail="audio_too_large")

    decode_started = time.perf_counter()
    try:
        pcm, uplink_trace = decode_framed_opus_to_pcm(
            [body],
            sample_rate=x_opus_sample_rate,
            channels=x_opus_channels,
            frame_duration_ms=x_opus_frame_duration_ms,
        )
    except OpusError as exc:
        detail = str(exc).split(":", 1)[0] or "opus_decode_failed"
        status_code = 400 if detail.startswith(("framed_", "opus_packet_", "invalid_")) else 500
        raise HTTPException(status_code=status_code, detail=detail) from exc

    if not pcm:
        raise HTTPException(status_code=400, detail="empty_decoded_audio")
    if x_original_pcm_bytes is not None:
        if x_original_pcm_bytes <= 0 or x_original_pcm_bytes > len(pcm):
            raise HTTPException(status_code=400, detail="invalid_original_pcm_bytes")
        pcm = pcm[:x_original_pcm_bytes]
        uplink_trace["uplink_pcm_bytes"] = len(pcm)
        opus_bytes = uplink_trace.get("uplink_opus_bytes") or 0
        uplink_trace["uplink_compression_ratio"] = round(len(pcm) / opus_bytes, 3) if opus_bytes else None
        byte_rate = x_opus_sample_rate * x_opus_channels * 2
        uplink_trace["reconstructed_audio_ms"] = int(round((len(pcm) / byte_rate) * 1000)) if byte_rate else 0

    uplink_trace["opus_decode_ms"] = int(round((time.perf_counter() - decode_started) * 1000))
    wav_path = save_pcm_as_wav(pcm, x_opus_sample_rate, 16, x_opus_channels)
    session = store.create_session(device_id=x_device_id, input_wav_path=str(wav_path))
    session_trace = session["trace"]
    session_trace.update(uplink_trace)
    store.update_session(session["session_id"], trace=session_trace)
    start_realtime_session(store, session["session_id"])
    return RealtimeSessionAcceptedResponse(
        status="accepted",
        session_id=session["session_id"],
        received_at=session["created_at"],
        audio_stream_url=session["audio_stream_url"],
    )


@router.get("/api/v3/realtime/sessions/{session_id}", response_model=RealtimeSessionStatusResponse)
def get_realtime_session(session_id: str) -> RealtimeSessionStatusResponse:
    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session_not_found")
    return RealtimeSessionStatusResponse(**session)


@router.get("/api/v3/realtime/sessions/{session_id}/audio")
def get_realtime_audio(
    session_id: str,
    x_accept_audio_format: str | None = Header(default=None),
):
    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session_not_found")
    consumer_id = str(uuid.uuid4())
    if not store.claim_audio_consumer(session_id, consumer_id=consumer_id):
        raise HTTPException(status_code=409, detail="audio_consumer_exists")
    try:
        store.wait_for_first_audio_chunk(
            session_id,
            timeout_ms=settings.realtime_stream_first_chunk_timeout_ms,
        )
    except RuntimeError as exc:
        detail = str(exc)
        if detail == "session_not_found":
            raise HTTPException(status_code=404, detail=detail) from exc
        if detail == "stream_first_chunk_timeout":
            raise HTTPException(status_code=500, detail=detail) from exc
        raise HTTPException(status_code=500, detail=detail) from exc

    selected_format = "pcm"
    requested_formats = [
        part.strip().lower()
        for part in (x_accept_audio_format or "").split(",")
        if part.strip()
    ]
    opus_enabled = settings.realtime_audio_enable_opus
    opus_runtime_available = opus_available()
    if (
        opus_enabled
        and "opus" in requested_formats
        and opus_runtime_available
    ):
        selected_format = "opus"
    logger.info(
        "realtime_audio_negotiation session_id=%s requested_formats=%s opus_enabled=%s opus_available=%s selected_format=%s",
        session_id,
        requested_formats,
        opus_enabled,
        opus_runtime_available,
        selected_format,
    )

    body_iterator = store.consume_audio_stream(
        session_id,
        idle_timeout_ms=settings.realtime_stream_idle_timeout_ms,
    )
    headers = {
        "X-Audio-Format": selected_format,
        "X-Audio-Packetization": "framed-v1",
    }
    if selected_format == "opus":
        try:
            body_iterator = encode_pcm_stream_to_framed_opus(
                body_iterator,
                sample_rate=settings.realtime_audio_opus_sample_rate,
                channels=settings.realtime_audio_opus_channels,
                frame_duration_ms=settings.realtime_audio_opus_frame_duration_ms,
                bitrate=settings.realtime_audio_opus_bitrate,
            )
        except OpusError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        headers.update(
            {
                "X-Opus-Sample-Rate": str(settings.realtime_audio_opus_sample_rate),
                "X-Opus-Channels": str(settings.realtime_audio_opus_channels),
                "X-Opus-Frame-Duration-Ms": str(settings.realtime_audio_opus_frame_duration_ms),
            }
        )
    else:
        headers.update(
            {
                "X-Audio-Sample-Rate": str(settings.realtime_audio_sample_rate),
                "X-Audio-Sample-Width": str(settings.realtime_audio_sample_width_bits),
                "X-Audio-Channels": str(settings.realtime_audio_channels),
                "X-Audio-Endian": settings.realtime_audio_endian,
            }
        )
    body_iterator = _frame_audio_packets(body_iterator)

    return StreamingResponse(
        body_iterator,
        media_type="application/octet-stream",
        headers=headers,
        status_code=200,
    )
