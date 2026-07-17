from __future__ import annotations

import asyncio
import json
import secrets
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Header, HTTPException, WebSocket
from fastapi.responses import StreamingResponse

from src.models.conversation_v6 import (
    MAX_TURNS,
    ProtocolError,
    TurnOutcome,
    TurnState,
    ack_event,
    asr_final_event,
    build_turn_event,
    conversation_done_event,
    conversation_ready_event,
    error_event,
    parse_client_control,
    turn_complete_event,
    turn_result_event,
)
from src.providers.asr import transcribe_wav_result
from src.providers.opus import (
    OpusError,
    decode_framed_opus_to_pcm,
    encode_pcm_stream_to_framed_opus,
    opus_available,
    pack_framed_v1_packets,
)
from src.services.conversation_v6 import ConversationSession
from src.settings import settings
from src.storage.files import save_pcm_as_wav


router = APIRouter()
KEEPALIVE_INTERVAL_SECONDS = 15.0
KEEPALIVE_MISSED_INTERVALS = 2
AUDIO_TOKEN_TTL_SECONDS = 120.0


class KeepaliveTimeout(TimeoutError):
    pass


@dataclass(frozen=True, slots=True)
class _AudioGrant:
    token: str
    device_id: str
    conversation_id: str
    turn_id: str
    expires_at: float


class ConversationRegistry:
    def __init__(self) -> None:
        self._sessions: dict[str, ConversationSession] = {}
        self._devices: dict[str, str] = {}
        self._grants: dict[tuple[str, str], _AudioGrant] = {}
        self._lock = threading.RLock()

    def create(self, *, device_id: str) -> ConversationSession:
        session = ConversationSession()
        with self._lock:
            self._sessions[session.conversation_id] = session
            self._devices[session.conversation_id] = str(device_id or "")
        return session

    def get(self, conversation_id: str) -> ConversationSession | None:
        with self._lock:
            return self._sessions.get(conversation_id)

    def remove(self, conversation_id: str) -> None:
        with self._lock:
            self._sessions.pop(conversation_id, None)
            self._devices.pop(conversation_id, None)
            grant_keys = [key for key in self._grants if key[0] == conversation_id]
            for key in grant_keys:
                self._grants.pop(key, None)

    def device_id(self, conversation_id: str) -> str:
        with self._lock:
            return self._devices.get(conversation_id, "")

    def issue_audio_token(
        self,
        conversation_id: str,
        turn_id: str,
        *,
        device_id: str,
        ttl_seconds: float = AUDIO_TOKEN_TTL_SECONDS,
    ) -> str:
        session = self.get(conversation_id)
        if session is None:
            raise KeyError("conversation_not_found")
        if session.audio_http_status(turn_id) == 404:
            raise KeyError("turn_not_found")
        expected_device = self.device_id(conversation_id)
        if expected_device and not secrets.compare_digest(expected_device, device_id):
            raise PermissionError("device_mismatch")
        token = secrets.token_urlsafe(24)
        grant = _AudioGrant(
            token=token,
            device_id=device_id,
            conversation_id=conversation_id,
            turn_id=turn_id,
            expires_at=time.monotonic() + max(0.0, ttl_seconds),
        )
        with self._lock:
            self._grants[(conversation_id, turn_id)] = grant
        return token

    def open_audio(
        self,
        conversation_id: str,
        turn_id: str,
        token: str,
        *,
        device_id: str,
        accepted_formats: str | None = None,
    ) -> StreamingResponse:
        with self._lock:
            session = self._sessions.get(conversation_id)
            grant = self._grants.get((conversation_id, turn_id))
        if session is None:
            raise HTTPException(status_code=404, detail="conversation_not_found")
        if grant is None or not secrets.compare_digest(grant.token, str(token or "")):
            raise HTTPException(status_code=403, detail="invalid_audio_token")
        if not secrets.compare_digest(grant.device_id, str(device_id or "")):
            raise HTTPException(status_code=403, detail="device_mismatch")
        if time.monotonic() > grant.expires_at:
            raise HTTPException(status_code=410, detail="audio_token_expired")
        status = session.audio_http_status(turn_id)
        if status == 404:
            raise HTTPException(status_code=404, detail="turn_not_found")
        if status == 410:
            raise HTTPException(status_code=410, detail="audio_revoked")
        turn = session._require_turn(turn_id)
        requested_formats = {
            part.strip().lower()
            for part in (accepted_formats or "").split(",")
            if part.strip()
        }
        body = iter(turn.audio)
        headers = {"Cache-Control": "no-store"}
        if (
            settings.realtime_audio_enable_opus
            and "opus" in requested_formats
            and opus_available()
        ):
            body = pack_framed_v1_packets(
                encode_pcm_stream_to_framed_opus(
                    body,
                    sample_rate=settings.realtime_audio_opus_sample_rate,
                    channels=settings.realtime_audio_opus_channels,
                    frame_duration_ms=settings.realtime_audio_opus_frame_duration_ms,
                    bitrate=settings.realtime_audio_opus_bitrate,
                )
            )
            headers.update(
                {
                    "X-Audio-Format": "opus",
                    "X-Audio-Packetization": "framed-v1",
                    "X-Opus-Sample-Rate": str(settings.realtime_audio_opus_sample_rate),
                    "X-Opus-Channels": str(settings.realtime_audio_opus_channels),
                    "X-Opus-Frame-Duration-Ms": str(
                        settings.realtime_audio_opus_frame_duration_ms
                    ),
                }
            )
        else:
            headers.update(
                {
                    "X-Audio-Format": "pcm",
                    "X-Audio-Sample-Rate": "16000",
                    "X-Audio-Sample-Width": "16",
                    "X-Audio-Channels": "1",
                    "X-Audio-Endian": "little",
                }
            )
        return StreamingResponse(
            body,
            media_type="application/octet-stream",
            headers=headers,
        )

    def reset(self) -> None:
        with self._lock:
            sessions = tuple(self._sessions.values())
            self._sessions.clear()
            self._devices.clear()
            self._grants.clear()
        for session in sessions:
            try:
                session.close()
            except Exception:
                pass


conversation_registry = ConversationRegistry()


async def receive_with_keepalive(
    websocket: WebSocket,
    *,
    conversation_id: str,
    interval_seconds: float = KEEPALIVE_INTERVAL_SECONDS,
    max_missed_intervals: int = KEEPALIVE_MISSED_INTERVALS,
) -> dict[str, Any]:
    missed = 0
    while True:
        try:
            return await asyncio.wait_for(websocket.receive(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            missed += 1
            if missed >= max_missed_intervals:
                await websocket.close(code=1001, reason="keepalive_timeout")
                raise KeepaliveTimeout("keepalive_timeout")
            await websocket.send_json({"type": "ping", "conversation_id": conversation_id})


class ConversationSocket:
    def __init__(
        self,
        websocket: WebSocket,
        session: ConversationSession,
        *,
        device_id: str,
    ) -> None:
        self.websocket = websocket
        self.session = session
        self.device_id = device_id
        self.started = False
        self._active_turn_id: str | None = None
        self._frames: dict[str, dict[int, bytes]] = {}
        self._tasks: set[asyncio.Task[Any]] = set()
        self._send_lock = asyncio.Lock()

    async def run(self) -> None:
        try:
            while True:
                message = await receive_with_keepalive(
                    self.websocket,
                    conversation_id=self.session.conversation_id,
                )
                if message.get("type") == "websocket.disconnect":
                    return
                try:
                    if message.get("bytes") is not None:
                        await self._handle_binary(message["bytes"])
                    elif message.get("text") is not None:
                        should_close = await self._handle_text(message["text"])
                        if should_close:
                            return
                except (ProtocolError, OpusError, ValueError, RuntimeError) as exc:
                    await self._send_error(_error_code(exc))
        except KeepaliveTimeout:
            return
        finally:
            for task in tuple(self._tasks):
                task.cancel()
            self.session.close()

    async def _handle_text(self, text: str) -> bool:
        try:
            payload = json.loads(text)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ProtocolError("invalid_control_json") from exc
        if not isinstance(payload, dict):
            raise ProtocolError("invalid_control")
        if payload.get("type") == "pong":
            return False
        requested_index = payload.get("turn_index")
        if (
            payload.get("type") == "turn_start"
            and self.session.turn_count >= MAX_TURNS
            and isinstance(requested_index, int)
            and not isinstance(requested_index, bool)
            and requested_index >= MAX_TURNS
        ):
            raise ProtocolError("turn_limit_exceeded")
        control = parse_client_control(payload)
        if control.type == "conversation_start":
            if self.started:
                raise ProtocolError("conversation_already_started")
            payload_device = str(control.data.get("device_id") or "")
            if self.device_id and payload_device != self.device_id:
                raise ProtocolError("device_mismatch")
            self.started = True
            await self._send(conversation_ready_event(control.client_conversation_id or "", self.session.conversation_id))
            return False
        self._require_started()
        if control.conversation_id != self.session.conversation_id:
            raise ProtocolError("conversation_mismatch")
        if control.type == "conversation_end":
            await self._send(conversation_done_event(self.session.conversation_id))
            await self.websocket.close(code=1000)
            return True
        if control.type == "turn_start":
            turn = self.session.start_turn(control.turn_id or "", control.turn_index if control.turn_index is not None else -1)
            self._active_turn_id = turn.turn_id
            self._frames.setdefault(turn.turn_id, {})
            await self._send(ack_event(self.session.conversation_id, turn.turn_id, turn.turn_index, "turn_start"))
            return False
        turn = self.session._require_turn(control.turn_id or "")
        turn.state_machine.validate_correlation(control)
        if control.type == "turn_cancel":
            event = await asyncio.to_thread(self.session.cancel_turn, turn.turn_id)
            if self._active_turn_id == turn.turn_id:
                self._active_turn_id = None
            await self._send(event)
        elif control.type == "turn_end":
            turn.state_machine.on_turn_end(control)
            self._active_turn_id = None
            task = asyncio.create_task(self._finish_turn(turn.turn_id))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        elif control.type == "turn_playback_complete":
            transition = turn.state_machine.on_turn_playback_complete(control)
            await self._send(build_turn_event(
                transition,
                conversation_id=self.session.conversation_id,
                turn_id=turn.turn_id,
                turn_index=turn.turn_index,
            ))
        return False

    async def _handle_binary(self, body: bytes) -> None:
        self._require_started()
        if self._active_turn_id is None:
            raise ProtocolError("no_receiving_turn")
        turn = self.session._require_turn(self._active_turn_id)
        if turn.state_machine.state is not TurnState.RECEIVING:
            raise ProtocolError("no_receiving_turn")
        frames = self._frames.setdefault(turn.turn_id, {})
        for sequence, payload in _parse_binary_frames(body):
            transition = turn.state_machine.ingest_frame(sequence, payload)
            frames.setdefault(sequence, payload)
            await self._send(build_turn_event(
                transition,
                conversation_id=self.session.conversation_id,
                turn_id=turn.turn_id,
                turn_index=turn.turn_index,
            ))

    async def _finish_turn(self, turn_id: str) -> None:
        turn = self.session._require_turn(turn_id)
        try:
            question = await asyncio.to_thread(self._transcribe_turn, turn_id)
            if turn.cancel_event.is_set():
                return
            if not question:
                transition = turn.state_machine.on_asr_empty()
                self.session.complete_asr_empty(turn.turn_id)
                await self._send(build_turn_event(
                    transition,
                    conversation_id=self.session.conversation_id,
                    turn_id=turn.turn_id,
                    turn_index=turn.turn_index,
                ))
                return
            transition = turn.state_machine.on_asr_final(question)
            await self._send(asr_final_event(
                self.session.conversation_id,
                turn.turn_id,
                turn.turn_index,
                str(transition.data["text"]),
            ))
            future: Future[Any] = self.session.process_turn(turn.turn_id, question)
            token = conversation_registry.issue_audio_token(
                self.session.conversation_id,
                turn.turn_id,
                device_id=self.device_id,
            )
            audio_url = (
                f"/api/v6/realtime/conversations/{self.session.conversation_id}"
                f"/turns/{turn.turn_id}/audio?token={token}"
            )
            turn.state_machine.on_turn_result(
                session_id=f"{self.session.conversation_id}:{turn.turn_id}",
                audio_stream_url=audio_url,
            )
            await self._send(turn_result_event(
                self.session.conversation_id,
                turn.turn_id,
                turn.turn_index,
                session_id=f"{self.session.conversation_id}:{turn.turn_id}",
                audio_stream_url=audio_url,
            ))
            await asyncio.wrap_future(future)
        except asyncio.CancelledError:
            raise
        except ProtocolError as exc:
            if not turn.cancel_event.is_set():
                await self._send_error(exc.code)
        except Exception:
            if not turn.cancel_event.is_set():
                try:
                    transition = turn.state_machine.on_technical_error()
                    self.session.complete_technical_error(turn.turn_id)
                    await self._send(turn_complete_event(
                        self.session.conversation_id,
                        turn.turn_id,
                        turn.turn_index,
                        transition.outcome or TurnOutcome.TECHNICAL_ERROR,
                    ))
                except ProtocolError:
                    await self._send_error("turn_processing_failed")

    def _transcribe_turn(self, turn_id: str) -> str:
        frames = self._frames.get(turn_id, {})
        if not frames:
            return ""
        expected = list(range(len(frames)))
        if sorted(frames) != expected:
            raise ProtocolError("sequence_gap")
        framed = [
            sequence.to_bytes(4, "big") + len(frames[sequence]).to_bytes(4, "big") + frames[sequence]
            for sequence in expected
        ]
        pcm, _trace = decode_framed_opus_to_pcm(
            framed,
            sample_rate=settings.realtime_audio_opus_sample_rate,
            channels=settings.realtime_audio_opus_channels,
            frame_duration_ms=settings.realtime_audio_opus_frame_duration_ms,
        )
        wav_path = save_pcm_as_wav(
            pcm,
            settings.realtime_audio_opus_sample_rate,
            16,
            settings.realtime_audio_opus_channels,
        )
        result = transcribe_wav_result(wav_path)
        if result.error_code:
            raise RuntimeError(result.error_code)
        return str(result.text or "").strip()

    async def _send(self, event: Any) -> None:
        payload = event.to_payload() if hasattr(event, "to_payload") else event
        async with self._send_lock:
            await self.websocket.send_json(payload)

    async def _send_error(self, code: str) -> None:
        await self._send(error_event(self.session.conversation_id, code))

    def _require_started(self) -> None:
        if not self.started:
            raise ProtocolError("conversation_not_started")


def _parse_binary_frames(body: bytes) -> list[tuple[int, bytes]]:
    if not isinstance(body, bytes):
        raise ProtocolError("invalid_binary_frame")
    frames: list[tuple[int, bytes]] = []
    offset = 0
    while offset < len(body):
        if len(body) - offset < 8:
            raise ProtocolError("framed_packet_truncated")
        sequence = int.from_bytes(body[offset : offset + 4], "big")
        size = int.from_bytes(body[offset + 4 : offset + 8], "big")
        offset += 8
        if len(body) - offset < size:
            raise ProtocolError("framed_packet_truncated")
        frames.append((sequence, body[offset : offset + size]))
        offset += size
    if not frames:
        raise ProtocolError("empty_binary_message")
    return frames


def _error_code(exc: BaseException) -> str:
    if isinstance(exc, ProtocolError):
        return exc.code
    value = str(exc).strip()
    return value or "protocol_error"


@router.websocket("/api/v6/realtime/conversation/opus-stream")
async def conversation_opus_stream(
    websocket: WebSocket,
    x_device_id: str = Header(default=""),
) -> None:
    await websocket.accept()
    session = conversation_registry.create(device_id=x_device_id)
    try:
        await ConversationSocket(websocket, session, device_id=x_device_id).run()
    finally:
        conversation_registry.remove(session.conversation_id)


@router.get("/api/v6/realtime/conversations/{conversation_id}/turns/{turn_id}/audio")
def conversation_audio(
    conversation_id: str,
    turn_id: str,
    token: str,
    x_device_id: str = Header(default=""),
    x_accept_audio_format: str | None = Header(default=None),
) -> StreamingResponse:
    return conversation_registry.open_audio(
        conversation_id,
        turn_id,
        token,
        device_id=x_device_id,
        accepted_formats=x_accept_audio_format,
    )
