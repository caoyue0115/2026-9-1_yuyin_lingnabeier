from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _is_expired(payload: dict[str, Any]) -> bool:
    expires_at = payload.get("expires_at")
    if not expires_at:
        return False
    return datetime.fromisoformat(expires_at) <= _now()


class InMemoryRealtimeSessionStore:
    def __init__(self, base_url: str, ttl_seconds: int = 900) -> None:
        self._base_url = base_url.rstrip("/")
        self._ttl_seconds = ttl_seconds
        self._lock = threading.RLock()
        self._sessions: dict[str, dict[str, Any]] = {}
        self._audio_states: dict[str, dict[str, Any]] = {}

    def create_session(self, device_id: str, input_wav_path: str | None = None) -> dict[str, Any]:
        session_id = str(uuid.uuid4())
        now = _now()
        payload = {
            "session_id": session_id,
            "device_id": device_id,
            "input_wav_path": input_wav_path,
            "status": "accepted",
            "step": "accepted",
            "final_reason": None,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "started_at": None,
            "finished_at": None,
            "question_text": None,
            "answer_text": None,
            "audio_stream_url": f"{self._base_url}/api/v3/realtime/sessions/{session_id}/audio",
            "trace": {
                "asr_ms": None,
                "retrieval_ms": None,
                "first_llm_chunk_ms": None,
                "first_tts_chunk_ms": None,
                "first_audio_byte_ms": None,
                "done_ms": None,
                "tts_warmup_ms": None,
                "tts_warmup_failed": None,
                "llm_chunk_count": None,
                "tts_segment_count": None,
                "segment_ready_ms": None,
                "audio_chunk_count": None,
                "audio_bytes": None,
                "audio_duration_ms": None,
                "audio_stream_wall_ms": None,
                "audio_max_chunk_gap_ms": None,
                "production_ratio": None,
                "uplink_opus_bytes": None,
                "uplink_pcm_bytes": None,
                "uplink_compression_ratio": None,
                "uplink_frame_count": None,
                "opus_decode_ms": None,
                "reconstructed_audio_ms": None,
                "first_pcm_to_asr_ms": None,
                "first_asr_partial_ms": None,
                "asr_final_ms": None,
                "realtime_asr_request_id": None,
                "asr_provider": None,
                "asr_log_id": None,
                "asr_error_code": None,
                "asr_error_message": None,
                "provider_start_abs_ms": None,
                "provider_ready_abs_ms": None,
                "provider_start_duration_ms": None,
                "first_pcm_decoded_abs_ms": None,
                "first_pcm_sent_to_provider_abs_ms": None,
                "first_provider_result_abs_ms": None,
                "provider_log_id": None,
                "provider_error_code": None,
                "provider_error_message": None,
                "answer_mode": None,
                "retrieval_top_score": None,
                "stream_to_session_start_abs_ms": None,
                "server_stream_accept_abs_ms": None,
                "first_frame_server_abs_ms": None,
                "first_pcm_to_asr_abs_ms": None,
                "first_asr_partial_abs_ms": None,
                "asr_final_abs_ms": None,
                "retrieval_done_abs_ms": None,
                "first_llm_chunk_abs_ms": None,
                "first_tts_chunk_abs_ms": None,
                "first_audio_byte_abs_ms": None,
                "done_abs_ms": None,
            },
            "error_code": None,
            "error_message": None,
            "audio_consumer_id": None,
            "expires_at": (now + timedelta(seconds=self._ttl_seconds)).isoformat(),
        }
        with self._lock:
            self._sessions[session_id] = payload
            self._audio_states[session_id] = {
                "condition": threading.Condition(self._lock),
                "chunks": [],
                "finished": False,
                "error_code": None,
            }
        return dict(payload)

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            payload = self._sessions.get(session_id)
            if payload and _is_expired(payload):
                del self._sessions[session_id]
                self._audio_states.pop(session_id, None)
                payload = None
            return dict(payload) if payload else None

    def update_session(self, session_id: str, **changes: Any) -> dict[str, Any] | None:
        with self._lock:
            payload = self._sessions.get(session_id)
            if payload and _is_expired(payload):
                del self._sessions[session_id]
                self._audio_states.pop(session_id, None)
                payload = None
            if payload is None:
                return None
            payload.update(changes)
            payload["updated_at"] = _now_iso()
            return dict(payload)

    def mark_done(
        self,
        session_id: str,
        final_reason: str,
        answer_text: str,
        done_ms: int,
    ) -> dict[str, Any] | None:
        with self._lock:
            payload = self._sessions.get(session_id)
            if payload and _is_expired(payload):
                del self._sessions[session_id]
                self._audio_states.pop(session_id, None)
                payload = None
            if payload is None:
                return None
            payload["status"] = "done"
            payload["step"] = "done"
            payload["final_reason"] = final_reason
            payload["answer_text"] = answer_text
            payload["finished_at"] = _now_iso()
            payload["trace"]["done_ms"] = done_ms
            payload["updated_at"] = _now_iso()
            return dict(payload)

    def mark_failed(self, session_id: str, error_code: str, error_message: str) -> dict[str, Any] | None:
        with self._lock:
            payload = self._sessions.get(session_id)
            if payload and _is_expired(payload):
                del self._sessions[session_id]
                self._audio_states.pop(session_id, None)
                payload = None
            if payload is None:
                return None
            payload["status"] = "failed"
            payload["step"] = "failed"
            payload["final_reason"] = "failed"
            payload["error_code"] = error_code
            payload["error_message"] = error_message
            payload["finished_at"] = _now_iso()
            payload["updated_at"] = _now_iso()
            return dict(payload)

    def claim_audio_consumer(self, session_id: str, consumer_id: str) -> bool:
        with self._lock:
            payload = self._sessions.get(session_id)
            if payload and _is_expired(payload):
                del self._sessions[session_id]
                self._audio_states.pop(session_id, None)
                payload = None
            if payload is None:
                return False
            current_consumer = payload.get("audio_consumer_id")
            if current_consumer:
                return current_consumer == consumer_id
            payload["audio_consumer_id"] = consumer_id
            payload["updated_at"] = _now_iso()
            return True

    def append_audio_chunk(self, session_id: str, chunk: bytes) -> bool:
        if not chunk:
            return False
        with self._lock:
            payload = self._sessions.get(session_id)
            state = self._audio_states.get(session_id)
            if payload is None or state is None or _is_expired(payload):
                self._sessions.pop(session_id, None)
                self._audio_states.pop(session_id, None)
                return False
            state["chunks"].append(chunk)
            state["condition"].notify_all()
            return True

    def finish_audio(self, session_id: str) -> bool:
        with self._lock:
            payload = self._sessions.get(session_id)
            state = self._audio_states.get(session_id)
            if payload is None or state is None or _is_expired(payload):
                self._sessions.pop(session_id, None)
                self._audio_states.pop(session_id, None)
                return False
            state["finished"] = True
            state["condition"].notify_all()
            return True

    def fail_audio(self, session_id: str, error_code: str) -> bool:
        with self._lock:
            payload = self._sessions.get(session_id)
            state = self._audio_states.get(session_id)
            if payload is None or state is None or _is_expired(payload):
                self._sessions.pop(session_id, None)
                self._audio_states.pop(session_id, None)
                return False
            state["finished"] = True
            state["error_code"] = error_code
            state["condition"].notify_all()
            return True

    def wait_for_first_audio_chunk(self, session_id: str, timeout_ms: int) -> None:
        deadline = time.monotonic() + max(timeout_ms, 0) / 1000.0
        with self._lock:
            while True:
                payload = self._sessions.get(session_id)
                state = self._audio_states.get(session_id)
                if payload is None or state is None or _is_expired(payload):
                    self._sessions.pop(session_id, None)
                    self._audio_states.pop(session_id, None)
                    raise RuntimeError("session_not_found")
                if state["chunks"]:
                    return
                if state["finished"]:
                    if state["error_code"]:
                        raise RuntimeError(state["error_code"])
                    raise RuntimeError("tts_empty_audio")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError("stream_first_chunk_timeout")
                state["condition"].wait(timeout=remaining)

    def consume_audio_stream(self, session_id: str, idle_timeout_ms: int):
        idle_seconds = max(idle_timeout_ms, 0) / 1000.0
        while True:
            with self._lock:
                payload = self._sessions.get(session_id)
                state = self._audio_states.get(session_id)
                if payload is None or state is None or _is_expired(payload):
                    self._sessions.pop(session_id, None)
                    self._audio_states.pop(session_id, None)
                    raise RuntimeError("session_not_found")
                if state["chunks"]:
                    chunk = state["chunks"].pop(0)
                elif state["finished"]:
                    if state["error_code"]:
                        raise RuntimeError(state["error_code"])
                    return
                else:
                    notified = state["condition"].wait(timeout=idle_seconds)
                    if not notified:
                        raise RuntimeError("stream_idle_timeout")
                    continue
            yield chunk
