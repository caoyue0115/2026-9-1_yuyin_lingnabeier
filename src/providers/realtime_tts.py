from __future__ import annotations

import audioop
import base64
import queue
import threading
from collections.abc import Iterable, Iterator
from typing import Any

from src.settings import settings

try:
    import dashscope
    from dashscope.audio.qwen_tts_realtime.qwen_tts_realtime import (
        AudioFormat,
        QwenTtsRealtime,
        QwenTtsRealtimeCallback,
    )
except Exception:  # pragma: no cover - fallback only for stripped test envs
    dashscope = None
    AudioFormat = None
    QwenTtsRealtime = None

    class QwenTtsRealtimeCallback:  # type: ignore[no-redef]
        pass


class RealtimeTtsError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def realtime_tts_health() -> bool:
    return bool(settings.dashscope_api_key and settings.realtime_tts_model and settings.realtime_tts_voice)


def decode_realtime_audio_delta(event: dict[str, Any]) -> bytes:
    if event.get("type") != "response.audio.delta":
        return b""
    delta = event.get("delta")
    if not delta:
        return b""
    try:
        return base64.b64decode(delta)
    except Exception as exc:  # pragma: no cover - defensive path
        raise RealtimeTtsError("audio_base64_decode_failed", "failed to decode realtime audio delta") from exc


def normalize_realtime_pcm_chunk(
    chunk: bytes,
    *,
    input_sample_rate: int,
    input_sample_width_bits: int,
    input_channels: int,
    output_sample_rate: int,
    output_sample_width_bits: int,
    output_channels: int,
) -> bytes:
    if not chunk:
        return b""
    input_width = input_sample_width_bits // 8
    output_width = output_sample_width_bits // 8
    if input_width <= 0 or output_width <= 0:
        raise RealtimeTtsError("unsupported_audio_format", "sample width must be positive")
    normalized = chunk
    channels = input_channels
    if channels == 2 and output_channels == 1:
        normalized = audioop.tomono(normalized, input_width, 0.5, 0.5)
        channels = 1
    if input_sample_rate != output_sample_rate:
        normalized, _ = audioop.ratecv(
            normalized,
            input_width,
            channels,
            input_sample_rate,
            output_sample_rate,
            None,
        )
    if input_width != output_width:
        normalized = audioop.lin2lin(normalized, input_width, output_width)
    if channels == 1 and output_channels == 2:
        normalized = audioop.tostereo(normalized, output_width, 1.0, 1.0)
    return normalized


class _RealtimeTtsCallback(QwenTtsRealtimeCallback):
    def __init__(self) -> None:
        self.events: queue.Queue[dict[str, Any]] = queue.Queue()

    def on_event(self, message: dict[str, Any]) -> None:
        self.events.put(message)


class PreparedRealtimeTtsSession:
    def __init__(self, client: QwenTtsRealtime, callback: _RealtimeTtsCallback) -> None:
        self._client = client
        self._callback = callback
        self._closed = False

    def stream_text_chunks(self, text_chunks: Iterable[str]) -> Iterator[bytes]:
        producer = threading.Thread(
            target=_stream_text_to_realtime_client,
            args=(self._client, self._callback, text_chunks),
            daemon=True,
        )
        producer.start()
        try:
            while True:
                event = self._callback.events.get(timeout=float(settings.tts_timeout_seconds))
                event_type = event.get("type")
                if event_type == "response.audio.delta":
                    decoded = decode_realtime_audio_delta(event)
                    normalized = normalize_realtime_pcm_chunk(
                        decoded,
                        input_sample_rate=24000,
                        input_sample_width_bits=16,
                        input_channels=1,
                        output_sample_rate=settings.realtime_audio_sample_rate,
                        output_sample_width_bits=settings.realtime_audio_sample_width_bits,
                        output_channels=settings.realtime_audio_channels,
                    )
                    if normalized:
                        yield normalized
                    continue
                if event_type == "__producer_error__":
                    raise RealtimeTtsError(
                        str(event.get("code") or "realtime_tts_input_failed"),
                        str(event.get("message") or "failed to stream text chunks to realtime tts"),
                    )
                if event_type == "response.done":
                    return
                if event_type == "error":
                    error = event.get("error") or {}
                    raise RealtimeTtsError(
                        str(error.get("code") or "realtime_tts_error"),
                        str(error.get("message") or "realtime tts request failed"),
                    )
        finally:
            producer.join(timeout=0.1)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._client.close()


def _stream_text_to_realtime_client(
    client: QwenTtsRealtime,
    callback: _RealtimeTtsCallback,
    text_chunks: Iterable[str],
) -> None:
    try:
        for text in text_chunks:
            if text:
                client.append_text(text)
        client.finish()
    except RealtimeTtsError as exc:
        callback.events.put({"type": "__producer_error__", "code": exc.code, "message": exc.message})
    except Exception as exc:
        callback.events.put(
            {
                "type": "__producer_error__",
                "code": "realtime_tts_input_failed",
                "message": str(exc) or "failed to stream text chunks to realtime tts",
            }
        )


def _build_client(callback: _RealtimeTtsCallback) -> QwenTtsRealtime:
    if dashscope is None or QwenTtsRealtime is None or AudioFormat is None:
        raise RealtimeTtsError("realtime_tts_unavailable", "dashscope realtime tts sdk unavailable")
    dashscope.api_key = settings.dashscope_api_key
    return QwenTtsRealtime(model=settings.realtime_tts_model, callback=callback)


def warmup_realtime_tts_session() -> PreparedRealtimeTtsSession:
    if not realtime_tts_health():
        raise RealtimeTtsError("realtime_tts_not_configured", "missing realtime tts model or voice")
    callback = _RealtimeTtsCallback()
    client = _build_client(callback)
    client.connect()
    client.update_session(
        voice=settings.realtime_tts_voice,
        mode="server_commit",
        response_format=AudioFormat.PCM_24000HZ_MONO_16BIT,
        sample_rate=24000,
        audio_format="pcm",
        language_type=settings.tts_language_type,
    )
    return PreparedRealtimeTtsSession(client, callback)


def stream_realtime_tts(text: str) -> Iterator[bytes]:
    return stream_realtime_tts_chunks([text])


def stream_realtime_tts_chunks(
    text_chunks: Iterable[str],
    prepared_session: PreparedRealtimeTtsSession | None = None,
) -> Iterator[bytes]:
    session = prepared_session or warmup_realtime_tts_session()
    try:
        yield from session.stream_text_chunks(text_chunks)
    finally:
        session.close()
