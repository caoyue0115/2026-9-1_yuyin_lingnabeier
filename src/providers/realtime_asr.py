from __future__ import annotations

import queue
import time
from dataclasses import dataclass
from typing import Any

from src.providers import asr as wav_asr
from src.settings import settings


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


def create_realtime_asr_session(*, sample_rate: int, audio_format: str = "pcm") -> DashScopeRealtimeAsrSession:
    return DashScopeRealtimeAsrSession(sample_rate=sample_rate, audio_format=audio_format)
