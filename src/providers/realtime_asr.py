from __future__ import annotations

import gzip
import json
import os
import queue
import time
import uuid
from dataclasses import dataclass
from typing import Any

from src.providers import asr as wav_asr
from src.settings import settings


ASR_PROVIDER_DASHSCOPE = "dashscope"
ASR_PROVIDER_VOLCENGINE = "volcengine"
ASR_PROVIDER_CHOICES = {ASR_PROVIDER_DASHSCOPE, ASR_PROVIDER_VOLCENGINE}

VOLCENGINE_ASR_STREAMING_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"

PROTOCOL_VERSION = 0b0001
DEFAULT_HEADER_SIZE = 0b0001
FULL_CLIENT_REQUEST = 0b0001
AUDIO_ONLY_REQUEST = 0b0010
SERVER_ERROR_RESPONSE = 0b1111
NO_SEQUENCE = 0b0000
POS_SEQUENCE = 0b0001
NEG_WITH_SEQUENCE = 0b0011
NO_SERIALIZATION = 0b0000
JSON_SERIALIZATION = 0b0001
GZIP_COMPRESSION = 0b0001


class RealtimeAsrError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class RealtimeAsrEvent:
    event_type: str
    text: str
    elapsed_ms: int | None
    request_id: str | None = None


@dataclass(frozen=True)
class RealtimeAsrResult:
    text: str | None
    error_code: str | None
    error_message: str | None = None
    first_asr_partial_ms: int | None = None
    asr_final_ms: int | None = None
    request_id: str | None = None


def _elapsed_ms(started_at: float) -> int:
    return max(0, int(round((time.perf_counter() - started_at) * 1000)))


def _env_value(key: str, default: str = "") -> str:
    value = os.getenv(key)
    if value is not None:
        return value.strip()
    env_path = settings.project_root / ".env"
    if env_path.exists():
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, raw_value = line.split("=", 1)
            if name.strip() == key:
                return raw_value.strip().strip('"').strip("'")
    return default.strip()


def _is_sentence_final(result: Any, sentence: Any) -> bool:
    if not isinstance(sentence, dict):
        return False
    recognition_result_class = getattr(result, "__class__", None)
    is_sentence_end = getattr(recognition_result_class, "is_sentence_end", None)
    if callable(is_sentence_end):
        try:
            return bool(is_sentence_end(sentence))
        except Exception:
            return False
    return sentence.get("end_time") is not None


class _StreamingRecognitionCallback:
    def __init__(self) -> None:
        from dashscope.audio.asr import RecognitionCallback

        class _Callback(RecognitionCallback):
            def __init__(self, owner: "_StreamingRecognitionCallback") -> None:
                self._owner = owner

            def on_event(self, result) -> None:
                self._owner.on_event(result)

            def on_error(self, result) -> None:
                self._owner.on_error(result)

            def on_complete(self) -> None:
                self._owner.on_complete()

            def on_close(self) -> None:
                self._owner.on_close()

        self.callback = _Callback(self)
        self._events: queue.Queue[RealtimeAsrEvent] = queue.Queue()
        self._started_at = time.perf_counter()
        self._first_partial_ms: int | None = None
        self._final_ms: int | None = None
        self._final_parts: list[str] = []
        self._last_text: str | None = None
        self._request_id: str | None = None
        self._error_code: str | None = None
        self._error_message: str | None = None

    def on_event(self, result: Any) -> None:
        sentence = result.get_sentence() if hasattr(result, "get_sentence") else None
        text = wav_asr._extract_result_text(result)
        if not text:
            return
        elapsed = _elapsed_ms(self._started_at)
        if self._first_partial_ms is None:
            self._first_partial_ms = elapsed
        self._last_text = text
        request_id = result.get_request_id() if hasattr(result, "get_request_id") else None
        if request_id:
            self._request_id = request_id
        final = _is_sentence_final(result, sentence)
        event_type = "asr_final" if final else "asr_partial"
        if final:
            self._final_ms = elapsed
            self._final_parts.append(text)
        self._events.put(
            RealtimeAsrEvent(
                event_type=event_type,
                text=text,
                elapsed_ms=elapsed,
                request_id=request_id,
            )
        )

    def on_error(self, result: Any) -> None:
        status_code = getattr(result, "status_code", None)
        self._error_code = wav_asr._status_error_code(status_code)
        self._error_message = wav_asr._status_error_message(result) or self._error_code

    def on_complete(self) -> None:
        if self._final_ms is None:
            self._final_ms = _elapsed_ms(self._started_at)

    def on_close(self) -> None:
        return None

    def drain_events(self) -> list[RealtimeAsrEvent]:
        events: list[RealtimeAsrEvent] = []
        while True:
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                return events

    def result(self) -> RealtimeAsrResult:
        text = " ".join(part for part in self._final_parts if part).strip() or (self._last_text or "").strip()
        if self._error_code:
            return RealtimeAsrResult(
                text=None,
                error_code=self._error_code,
                error_message=self._error_message,
                first_asr_partial_ms=self._first_partial_ms,
                asr_final_ms=self._final_ms,
                request_id=self._request_id,
            )
        if not text:
            return RealtimeAsrResult(
                text=None,
                error_code="asr_empty_text",
                error_message="DashScope realtime ASR returned empty text",
                first_asr_partial_ms=self._first_partial_ms,
                asr_final_ms=self._final_ms,
                request_id=self._request_id,
            )
        return RealtimeAsrResult(
            text=text,
            error_code=None,
            error_message=None,
            first_asr_partial_ms=self._first_partial_ms,
            asr_final_ms=self._final_ms,
            request_id=self._request_id,
        )


class DashScopeRealtimeAsrSession:
    def __init__(self, *, sample_rate: int, audio_format: str = "pcm") -> None:
        if not wav_asr._is_asr_configured():
            raise RealtimeAsrError("asr_not_configured", "DashScope ASR is not fully configured")
        try:
            wav_asr._configure_dashscope_sdk()
            recognition_class = wav_asr._load_recognition_class()
        except ImportError as exc:
            raise RealtimeAsrError("asr_sdk_unavailable", str(exc) or "DashScope ASR SDK unavailable") from exc

        self._callback = _StreamingRecognitionCallback()
        kwargs: dict[str, Any] = {
            "model": settings.asr_model,
            "callback": self._callback.callback,
            "format": audio_format,
            "sample_rate": sample_rate,
            "language_hints": settings.asr_language_hints_list,
        }
        self._recognition = recognition_class(**kwargs)
        self._phrase_id = settings.asr_vocabulary_id or None
        self._started = False

    def start(self) -> None:
        try:
            self._recognition.start(phrase_id=self._phrase_id)
            self._started = True
        except Exception as exc:
            raise RealtimeAsrError("asr_start_failed", str(exc) or "DashScope realtime ASR start failed") from exc

    def send_pcm_chunk(self, pcm_chunk: bytes) -> list[RealtimeAsrEvent]:
        if not pcm_chunk:
            return self.drain_events()
        try:
            self._recognition.send_audio_frame(pcm_chunk)
        except Exception as exc:
            raise RealtimeAsrError("asr_send_failed", str(exc) or "DashScope realtime ASR send failed") from exc
        return self.drain_events()

    def drain_events(self) -> list[RealtimeAsrEvent]:
        return self._callback.drain_events()

    def finish(self) -> RealtimeAsrResult:
        try:
            if self._started:
                self._recognition.stop()
        except Exception as exc:
            return RealtimeAsrResult(
                text=None,
                error_code="asr_finish_failed",
                error_message=str(exc) or "DashScope realtime ASR finish failed",
            )
        return self._callback.result()


def _generate_volcengine_asr_header(
    message_type: int,
    message_type_specific_flags: int,
    serial_method: int,
    compression_type: int,
) -> bytearray:
    return bytearray(
        [
            (PROTOCOL_VERSION << 4) | DEFAULT_HEADER_SIZE,
            (message_type << 4) | message_type_specific_flags,
            (serial_method << 4) | compression_type,
            0x00,
        ]
    )


def _build_volcengine_initial_request(*, sample_rate: int, model_name: str) -> bytes:
    request = {
        "user": {"uid": "v5-opus-uplink"},
        "audio": {
            "format": "pcm",
            "codec": "raw",
            "rate": sample_rate,
            "bits": 16,
            "channel": 1,
        },
        "request": {
            "model_name": model_name,
            "enable_itn": True,
            "enable_punc": True,
            "enable_ddc": True,
            "show_utterances": True,
            "enable_nonstream": True,
        },
    }
    payload = gzip.compress(json.dumps(request, ensure_ascii=False).encode("utf-8"))
    frame = _generate_volcengine_asr_header(FULL_CLIENT_REQUEST, POS_SEQUENCE, JSON_SERIALIZATION, GZIP_COMPRESSION)
    frame.extend((1).to_bytes(4, "big", signed=True))
    frame.extend(len(payload).to_bytes(4, "big"))
    frame.extend(payload)
    return bytes(frame)


def _build_volcengine_audio_frame(chunk: bytes, *, sequence: int, final: bool) -> bytes:
    payload = gzip.compress(chunk)
    frame = _generate_volcengine_asr_header(AUDIO_ONLY_REQUEST, NEG_WITH_SEQUENCE if final else POS_SEQUENCE, NO_SERIALIZATION, GZIP_COMPRESSION)
    seq = -abs(sequence) if final else abs(sequence)
    frame.extend(int(seq).to_bytes(4, "big", signed=True))
    frame.extend(len(payload).to_bytes(4, "big"))
    frame.extend(payload)
    return bytes(frame)


def _parse_volcengine_asr_message(message: bytes) -> dict[str, Any]:
    if not isinstance(message, (bytes, bytearray)) or len(message) < 8:
        return {"message_type": None, "payload": None}
    header_size = (message[0] & 0x0F) * 4
    message_type = (message[1] & 0xF0) >> 4
    flags = message[1] & 0x0F
    serialization = (message[2] & 0xF0) >> 4
    compression = message[2] & 0x0F
    offset = header_size
    sequence: int | None = None
    if flags in {POS_SEQUENCE, NEG_WITH_SEQUENCE} and len(message) >= offset + 4:
        sequence = int.from_bytes(message[offset : offset + 4], "big", signed=True)
        offset += 4
    if len(message) < offset + 4:
        return {"message_type": message_type, "flags": flags, "sequence": sequence, "payload": None}
    payload_size = int.from_bytes(message[offset : offset + 4], "big")
    offset += 4
    payload = bytes(message[offset : offset + payload_size])
    if compression == GZIP_COMPRESSION and payload:
        payload = gzip.decompress(payload)
    parsed_payload: Any = payload
    if serialization == JSON_SERIALIZATION and payload:
        parsed_payload = json.loads(payload.decode("utf-8"))
    return {
        "message_type": message_type,
        "flags": flags,
        "sequence": sequence,
        "payload": parsed_payload,
    }


def _extract_volcengine_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    result = payload.get("result")
    if isinstance(result, dict) and isinstance(result.get("text"), str):
        return result["text"].strip()
    if isinstance(result, dict) and isinstance(result.get("utterances"), list):
        fallback_text = ""
        for utterance in result["utterances"]:
            if not isinstance(utterance, dict) or not isinstance(utterance.get("text"), str):
                continue
            text = utterance["text"].strip()
            if utterance.get("definite") is True and text:
                return text
            if text:
                fallback_text = text
        return fallback_text
    return ""


def _extract_volcengine_log_id(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    result = payload.get("result")
    if not isinstance(result, dict):
        return None
    additions = result.get("additions")
    if isinstance(additions, dict) and isinstance(additions.get("log_id"), str):
        return additions["log_id"]
    return None


class VolcengineRealtimeAsrSession:
    def __init__(self, *, sample_rate: int, audio_format: str = "pcm") -> None:
        if audio_format != "pcm":
            raise RealtimeAsrError("volcengine_asr_invalid_audio_format", "Volcengine ASR provider expects pcm chunks")
        self._sample_rate = sample_rate
        self._app_id = _env_value("VOLCENGINE_SPEECH_APP_ID")
        self._access_token = _env_value("VOLCENGINE_SPEECH_ACCESS_TOKEN")
        self._resource_id = _env_value("VOLCENGINE_ASR_RESOURCE_ID", "volc.seedasr.sauc.duration")
        self._model_name = _env_value("VOLCENGINE_ASR_MODEL_NAME", "bigmodel")
        self._endpoint = _env_value("VOLCENGINE_ASR_ENDPOINT", VOLCENGINE_ASR_STREAMING_URL)
        self._timeout = float(_env_value("VOLCENGINE_ASR_TIMEOUT", "30") or "30")
        if not self._app_id or not self._access_token:
            raise RealtimeAsrError("volcengine_asr_not_configured", "Volcengine ASR app id or access token is missing")

        self._ws = None
        self._started_at = 0.0
        self._sequence = 2
        self._pending_chunk: bytes | None = None
        self._first_partial_ms: int | None = None
        self._final_ms: int | None = None
        self._latest_text = ""
        self._log_id: str | None = None
        self._started = False

    def start(self) -> None:
        try:
            import websocket
        except ImportError as exc:
            raise RealtimeAsrError("volcengine_asr_dependency_missing", "websocket-client is required") from exc

        connect_id = str(uuid.uuid4())
        headers = [
            f"X-Api-App-Key: {self._app_id}",
            f"X-Api-Access-Key: {self._access_token}",
            f"X-Api-Resource-Id: {self._resource_id}",
            f"X-Api-Connect-Id: {connect_id}",
        ]
        try:
            self._started_at = time.perf_counter()
            self._ws = websocket.create_connection(self._endpoint, header=headers, timeout=self._timeout)
            self._ws.settimeout(min(2.0, self._timeout))
            self._ws.send_binary(
                _build_volcengine_initial_request(sample_rate=self._sample_rate, model_name=self._model_name)
            )
            self._started = True
        except Exception as exc:
            raise RealtimeAsrError("volcengine_asr_start_failed", str(exc) or "Volcengine ASR start failed") from exc

    def _send_audio_frame(self, chunk: bytes, *, final: bool) -> None:
        if self._ws is None:
            raise RealtimeAsrError("volcengine_asr_not_started", "Volcengine ASR websocket is not started")
        self._ws.send_binary(_build_volcengine_audio_frame(chunk, sequence=self._sequence, final=final))
        self._sequence += 1

    def send_pcm_chunk(self, pcm_chunk: bytes) -> list[RealtimeAsrEvent]:
        if not pcm_chunk:
            return []
        try:
            if self._pending_chunk is not None:
                self._send_audio_frame(self._pending_chunk, final=False)
            self._pending_chunk = pcm_chunk
        except Exception as exc:
            raise RealtimeAsrError("volcengine_asr_send_failed", str(exc) or "Volcengine ASR send failed") from exc
        return []

    def drain_events(self) -> list[RealtimeAsrEvent]:
        return []

    def finish(self) -> RealtimeAsrResult:
        if not self._started or self._ws is None:
            return RealtimeAsrResult(text=None, error_code="volcengine_asr_not_started", error_message="Volcengine ASR was not started")
        try:
            if self._pending_chunk is None:
                self._pending_chunk = b""
            self._send_audio_frame(self._pending_chunk, final=True)
            receive_deadline = time.perf_counter() + self._timeout
            while time.perf_counter() < receive_deadline:
                try:
                    response = _parse_volcengine_asr_message(self._ws.recv())
                except Exception as exc:
                    if exc.__class__.__name__ == "WebSocketTimeoutException":
                        continue
                    if self._latest_text and "already closed" in str(exc).lower():
                        break
                    raise
                payload = response.get("payload")
                log_id = _extract_volcengine_log_id(payload)
                if log_id:
                    self._log_id = log_id
                if response.get("message_type") == SERVER_ERROR_RESPONSE:
                    return RealtimeAsrResult(
                        text=None,
                        error_code="volcengine_asr_server_error",
                        error_message=json.dumps(payload, ensure_ascii=False) if payload is not None else "Volcengine ASR server error",
                        first_asr_partial_ms=self._first_partial_ms,
                        asr_final_ms=_elapsed_ms(self._started_at),
                        request_id=self._log_id,
                    )
                text = _extract_volcengine_text(payload)
                if text:
                    elapsed = _elapsed_ms(self._started_at)
                    if self._first_partial_ms is None:
                        self._first_partial_ms = elapsed
                    self._latest_text = text
                    self._final_ms = elapsed
                response_sequence = response.get("sequence")
                if isinstance(response_sequence, int) and response_sequence < 0:
                    break
        except Exception as exc:
            return RealtimeAsrResult(
                text=None,
                error_code="volcengine_asr_finish_failed",
                error_message=str(exc) or "Volcengine ASR finish failed",
                first_asr_partial_ms=self._first_partial_ms,
                asr_final_ms=self._final_ms,
                request_id=self._log_id,
            )
        finally:
            try:
                self._ws.close()
            except Exception:
                pass
        if not self._latest_text:
            return RealtimeAsrResult(
                text=None,
                error_code="volcengine_asr_empty_text",
                error_message="Volcengine ASR returned empty text",
                first_asr_partial_ms=self._first_partial_ms,
                asr_final_ms=self._final_ms,
                request_id=self._log_id,
            )
        return RealtimeAsrResult(
            text=self._latest_text,
            error_code=None,
            error_message=None,
            first_asr_partial_ms=self._first_partial_ms,
            asr_final_ms=self._final_ms,
            request_id=self._log_id,
        )


def create_realtime_asr_session(
    *,
    sample_rate: int,
    audio_format: str = "pcm",
    provider: str = ASR_PROVIDER_DASHSCOPE,
):
    if provider == ASR_PROVIDER_DASHSCOPE:
        return DashScopeRealtimeAsrSession(sample_rate=sample_rate, audio_format=audio_format)
    if provider == ASR_PROVIDER_VOLCENGINE:
        return VolcengineRealtimeAsrSession(sample_rate=sample_rate, audio_format=audio_format)
    raise RealtimeAsrError("invalid_asr_provider", f"Unsupported ASR provider: {provider}")
