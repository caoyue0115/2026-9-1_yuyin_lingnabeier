from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid

from fastapi import APIRouter, Header, HTTPException, Request, WebSocket
from fastapi.responses import StreamingResponse

from src.models.realtime import RealtimeSessionAcceptedResponse, RealtimeSessionStatusResponse
from src.providers.opus import (
    LibOpusDecoder,
    OpusError,
    decode_framed_opus_to_pcm,
    encode_pcm_stream_to_framed_opus,
    opus_available,
    parse_framed_v1_packets,
)
from src.providers.realtime_asr import RealtimeAsrError, RealtimeAsrEvent, create_realtime_asr_session
from src.services.realtime_session import start_realtime_session, start_realtime_session_from_question
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


def _opus_error_detail(exc: OpusError) -> str:
    return str(exc).split(":", 1)[0] or "opus_decode_failed"


async def _send_stream_error(websocket: WebSocket, error_code: str, *, close_code: int = 1003) -> None:
    await websocket.send_json(
        {
            "type": "error",
            "error_code": error_code,
            "error_message": error_code,
        }
    )
    await websocket.close(code=close_code)


async def _send_asr_events(websocket: WebSocket, events: list[RealtimeAsrEvent]) -> None:
    for event in events:
        await websocket.send_json(
            {
                "type": event.event_type,
                "text": event.text,
                "elapsed_ms": event.elapsed_ms,
                "request_id": event.request_id,
            }
        )


def _decode_stream_opus_payload(
    decoder: LibOpusDecoder,
    payload: bytes,
    *,
    frame_size: int,
) -> tuple[bytes, int]:
    if len(payload) < 2:
        raise OpusError("opus_packet_truncated")
    packet_len = int.from_bytes(payload[:2], "big")
    packet = payload[2:]
    if len(packet) != packet_len:
        raise OpusError("opus_packet_truncated")
    return decoder.decode_packet(packet, frame_size=frame_size), len(packet)


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


@router.websocket("/api/v5/realtime/opus-stream")
async def stream_opus_realtime_session(
    websocket: WebSocket,
    x_device_id: str = Header(default="pc-opus-uplink-stream-001"),
    x_audio_packetization: str = Header(default="framed-v1"),
    x_audio_format: str = Header(default="opus"),
    x_opus_sample_rate: int = Header(default=settings.realtime_audio_opus_sample_rate),
    x_opus_channels: int = Header(default=settings.realtime_audio_opus_channels),
    x_opus_frame_duration_ms: int = Header(default=settings.realtime_audio_opus_frame_duration_ms),
    x_original_pcm_bytes: int | None = Header(default=None),
) -> None:
    accept_started = time.perf_counter()
    await websocket.accept()
    accepted_at = time.perf_counter()
    stream_accept_ms = int(round((accepted_at - accept_started) * 1000))

    if x_audio_packetization != "framed-v1":
        await _send_stream_error(websocket, "invalid_packetization", close_code=1008)
        return
    if x_audio_format != "opus":
        await _send_stream_error(websocket, "invalid_audio_format", close_code=1008)
        return

    frame_size = x_opus_sample_rate * x_opus_frame_duration_ms // 1000
    if frame_size <= 0:
        await _send_stream_error(websocket, "invalid_opus_frame_size")
        return

    expected_sequence = 0
    opus_bytes = 0
    decoded = bytearray()
    decode_seconds = 0.0
    first_frame_server_ms: int | None = None
    last_frame_server_ms: int | None = None
    client_stream_duration_ms: int | None = None
    end_received_at: float | None = None
    run_session_after_stream = False
    run_asr = False
    run_full_chain = False
    realtime_asr = None
    asr_started_server_ms: int | None = None
    first_pcm_to_asr_ms: int | None = None
    asr_result = None

    try:
        with LibOpusDecoder(sample_rate=x_opus_sample_rate, channels=x_opus_channels) as decoder:
            while True:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    await _send_stream_error(websocket, "stream_disconnected", close_code=1000)
                    return

                message_bytes = message.get("bytes")
                if message_bytes is not None:
                    if first_frame_server_ms is None:
                        first_frame_server_ms = int(round((time.perf_counter() - accepted_at) * 1000))
                    outer_packets = parse_framed_v1_packets(
                        message_bytes,
                        expected_sequence=expected_sequence,
                    )
                    for sequence, payload in outer_packets:
                        decode_started = time.perf_counter()
                        pcm_chunk, packet_bytes = _decode_stream_opus_payload(
                            decoder,
                            payload,
                            frame_size=frame_size,
                        )
                        decode_seconds += time.perf_counter() - decode_started
                        decoded.extend(pcm_chunk)
                        opus_bytes += packet_bytes
                        expected_sequence = sequence + 1
                        if realtime_asr is not None:
                            if first_pcm_to_asr_ms is None:
                                first_pcm_to_asr_ms = int(round((time.perf_counter() - accepted_at) * 1000))
                            await _send_asr_events(websocket, realtime_asr.send_pcm_chunk(pcm_chunk))
                        last_frame_server_ms = int(round((time.perf_counter() - accepted_at) * 1000))
                        await websocket.send_json(
                            {
                                "type": "ack",
                                "frame_count": expected_sequence,
                                "received_opus_bytes": opus_bytes,
                                "decoded_pcm_bytes": len(decoded),
                            }
                        )
                    continue

                message_text = message.get("text")
                if message_text is None:
                    continue
                try:
                    control = json.loads(message_text)
                except json.JSONDecodeError:
                    await _send_stream_error(websocket, "invalid_control_json", close_code=1003)
                    return
                if control.get("type") == "start":
                    if expected_sequence != 0 or decoded:
                        await _send_stream_error(websocket, "invalid_start_order", close_code=1003)
                        return
                    run_asr = bool(control.get("run_asr", False))
                    run_full_chain = bool(control.get("run_full_chain", False))
                    if run_asr:
                        try:
                            realtime_asr = create_realtime_asr_session(
                                sample_rate=x_opus_sample_rate,
                                audio_format="pcm",
                            )
                            asr_started_server_ms = int(round((time.perf_counter() - accepted_at) * 1000))
                            realtime_asr.start()
                        except RealtimeAsrError as exc:
                            await _send_stream_error(websocket, exc.code, close_code=1011)
                            return
                    continue
                if control.get("type") != "end":
                    await _send_stream_error(websocket, "invalid_control_type", close_code=1003)
                    return
                raw_client_duration = control.get("client_stream_duration_ms")
                if isinstance(raw_client_duration, int):
                    client_stream_duration_ms = raw_client_duration
                run_session_after_stream = bool(control.get("run_session_after_stream", False))
                if bool(control.get("run_full_chain", False)):
                    run_full_chain = True
                end_received_at = time.perf_counter()
                break
    except OpusError as exc:
        await _send_stream_error(websocket, _opus_error_detail(exc))
        return
    except RealtimeAsrError as exc:
        await _send_stream_error(websocket, exc.code, close_code=1011)
        return

    if not decoded:
        await _send_stream_error(websocket, "empty_decoded_audio")
        return
    if x_original_pcm_bytes is not None:
        if x_original_pcm_bytes <= 0 or x_original_pcm_bytes > len(decoded):
            await _send_stream_error(websocket, "invalid_original_pcm_bytes")
            return
        decoded = decoded[:x_original_pcm_bytes]

    byte_rate = x_opus_sample_rate * x_opus_channels * 2
    reconstructed_audio_ms = int(round((len(decoded) / byte_rate) * 1000)) if byte_rate else 0
    compression_ratio = round(len(decoded) / opus_bytes, 3) if opus_bytes else None
    wav_path = save_pcm_as_wav(bytes(decoded), x_opus_sample_rate, 16, x_opus_channels)
    reconstruct_done_at = time.perf_counter()

    if realtime_asr is not None:
        asr_result = await asyncio.to_thread(realtime_asr.finish)
        await _send_asr_events(websocket, realtime_asr.drain_events())
        first_asr_partial_abs_ms = (
            asr_started_server_ms + asr_result.first_asr_partial_ms
            if asr_started_server_ms is not None and asr_result.first_asr_partial_ms is not None
            else None
        )
        asr_final_abs_ms = (
            asr_started_server_ms + asr_result.asr_final_ms
            if asr_started_server_ms is not None and asr_result.asr_final_ms is not None
            else None
        )
        if asr_result.error_code or not asr_result.text:
            await websocket.send_json(
                {
                    "type": "error",
                    "error_code": asr_result.error_code or "asr_empty_text",
                    "error_message": asr_result.error_message or "ASR failed",
                    "first_pcm_to_asr_ms": first_pcm_to_asr_ms,
                    "first_asr_partial_ms": asr_result.first_asr_partial_ms,
                    "asr_final_ms": asr_result.asr_final_ms,
                    "first_pcm_to_asr_abs_ms": first_pcm_to_asr_ms,
                    "first_asr_partial_abs_ms": first_asr_partial_abs_ms,
                    "asr_final_abs_ms": asr_final_abs_ms,
                    "request_id": asr_result.request_id,
                }
            )
            await websocket.close(code=1011)
            return
        await websocket.send_json(
            {
                "type": "asr_final",
                "text": asr_result.text,
                "first_asr_partial_ms": asr_result.first_asr_partial_ms,
                "asr_final_ms": asr_result.asr_final_ms,
                "first_asr_partial_abs_ms": first_asr_partial_abs_ms,
                "asr_final_abs_ms": asr_final_abs_ms,
                "request_id": asr_result.request_id,
            }
        )
    else:
        first_asr_partial_abs_ms = None
        asr_final_abs_ms = None

    record_end_to_reconstruct_done_ms = (
        int(round((reconstruct_done_at - end_received_at) * 1000))
        if end_received_at is not None
        else None
    )
    server_receive_duration_ms = (
        last_frame_server_ms - first_frame_server_ms
        if first_frame_server_ms is not None and last_frame_server_ms is not None
        else None
    )
    websocket_done_abs_ms = max(
        value
        for value in [
            int(round((time.perf_counter() - accepted_at) * 1000)),
            first_pcm_to_asr_ms,
            first_asr_partial_abs_ms,
            asr_final_abs_ms,
        ]
        if value is not None
    )
    done_payload = {
        "type": "done",
        "stream_accept_ms": stream_accept_ms,
        "first_frame_server_ms": first_frame_server_ms,
        "last_frame_server_ms": last_frame_server_ms,
        "client_stream_duration_ms": client_stream_duration_ms,
        "server_receive_duration_ms": server_receive_duration_ms,
        "uplink_frame_count": expected_sequence,
        "uplink_opus_bytes": opus_bytes,
        "uplink_pcm_bytes": len(decoded),
        "uplink_compression_ratio": compression_ratio,
        "opus_decode_ms": int(round(decode_seconds * 1000)),
        "reconstructed_audio_ms": reconstructed_audio_ms,
        "record_end_to_reconstruct_done_ms": record_end_to_reconstruct_done_ms,
        "first_pcm_to_asr_ms": first_pcm_to_asr_ms,
        "first_asr_partial_ms": asr_result.first_asr_partial_ms if asr_result is not None else None,
        "asr_final_ms": asr_result.asr_final_ms if asr_result is not None else None,
        "server_stream_accept_abs_ms": 0,
        "first_frame_server_abs_ms": first_frame_server_ms,
        "first_pcm_to_asr_abs_ms": first_pcm_to_asr_ms,
        "first_asr_partial_abs_ms": first_asr_partial_abs_ms,
        "asr_final_abs_ms": asr_final_abs_ms,
        "done_abs_ms": websocket_done_abs_ms,
        "question_text": asr_result.text if asr_result is not None else None,
        "realtime_asr_request_id": asr_result.request_id if asr_result is not None else None,
        "error_code": None,
        "error_message": None,
        "session_started": False,
    }

    if run_full_chain and asr_result is not None and asr_result.text:
        stream_to_session_start_abs_ms = int(round((time.perf_counter() - accepted_at) * 1000))
        session = store.create_session(device_id=x_device_id, input_wav_path=str(wav_path))
        session_trace = session["trace"]
        session_trace.update(
            {
                "uplink_opus_bytes": opus_bytes,
                "uplink_pcm_bytes": len(decoded),
                "uplink_compression_ratio": compression_ratio,
                "uplink_frame_count": expected_sequence,
                "opus_decode_ms": int(round(decode_seconds * 1000)),
                "reconstructed_audio_ms": reconstructed_audio_ms,
                "first_pcm_to_asr_ms": first_pcm_to_asr_ms,
                "first_asr_partial_ms": asr_result.first_asr_partial_ms,
                "asr_final_ms": asr_result.asr_final_ms,
                "asr_ms": asr_result.asr_final_ms,
                "realtime_asr_request_id": asr_result.request_id,
                "stream_to_session_start_abs_ms": stream_to_session_start_abs_ms,
                "server_stream_accept_abs_ms": 0,
                "first_frame_server_abs_ms": first_frame_server_ms,
                "first_pcm_to_asr_abs_ms": first_pcm_to_asr_ms,
                "first_asr_partial_abs_ms": first_asr_partial_abs_ms,
                "asr_final_abs_ms": asr_final_abs_ms,
            }
        )
        store.update_session(session["session_id"], trace=session_trace, question_text=asr_result.text)
        start_realtime_session_from_question(store, session["session_id"], asr_result.text)
        done_payload.update(
            {
                "session_started": True,
                "session_id": session["session_id"],
                "audio_stream_url": session["audio_stream_url"],
            }
        )
    elif run_session_after_stream:
        stream_to_session_start_abs_ms = int(round((time.perf_counter() - accepted_at) * 1000))
        session = store.create_session(device_id=x_device_id, input_wav_path=str(wav_path))
        session_trace = session["trace"]
        session_trace.update(
            {
                "uplink_opus_bytes": opus_bytes,
                "uplink_pcm_bytes": len(decoded),
                "uplink_compression_ratio": compression_ratio,
                "uplink_frame_count": expected_sequence,
                "opus_decode_ms": int(round(decode_seconds * 1000)),
                "reconstructed_audio_ms": reconstructed_audio_ms,
                "stream_to_session_start_abs_ms": stream_to_session_start_abs_ms,
                "server_stream_accept_abs_ms": 0,
                "first_frame_server_abs_ms": first_frame_server_ms,
            }
        )
        store.update_session(session["session_id"], trace=session_trace)
        start_realtime_session(store, session["session_id"])
        done_payload.update(
            {
                "session_started": True,
                "session_id": session["session_id"],
                "audio_stream_url": session["audio_stream_url"],
            }
        )

    await websocket.send_json(done_payload)
    await websocket.close(code=1000)


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
