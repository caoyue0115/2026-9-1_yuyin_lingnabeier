from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
import wave
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from tests._stubs import install_dependency_stubs

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

install_dependency_stubs()

from fastapi import HTTPException


def _write_test_wav(pcm_bytes: bytes) -> str:
    fd, path = tempfile.mkstemp(suffix=".wav")
    Path(path).unlink(missing_ok=True)
    with wave.open(path, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(pcm_bytes)
    return path


def _parse_framed_packets(payload: bytes) -> list[tuple[int, bytes]]:
    packets: list[tuple[int, bytes]] = []
    offset = 0
    while offset < len(payload):
        seq = int.from_bytes(payload[offset : offset + 4], "big")
        packet_len = int.from_bytes(payload[offset + 4 : offset + 8], "big")
        offset += 8
        packet = payload[offset : offset + packet_len]
        packets.append((seq, packet))
        offset += packet_len
    return packets


class RealtimeSchemaTests(unittest.TestCase):
    def test_realtime_status_response_exposes_required_fields(self) -> None:
        from src.models.realtime import RealtimeSessionStatusResponse

        payload = RealtimeSessionStatusResponse(
            session_id="session-1",
            status="running",
            step="tts",
            final_reason=None,
            created_at="2026-04-09T15:34:12.245000+00:00",
            updated_at="2026-04-09T15:34:13.901000+00:00",
            started_at="2026-04-09T15:34:12.260000+00:00",
            finished_at=None,
            question_text=None,
            answer_text=None,
            audio_stream_url="http://testserver/api/v3/realtime/sessions/session-1/audio",
            trace={
                "asr_ms": None,
                "retrieval_ms": None,
                "first_llm_chunk_ms": None,
                "first_tts_chunk_ms": None,
                "first_audio_byte_ms": None,
                "done_ms": None,
                "asr_primary_provider": "volcengine",
                "asr_provider_used": "dashscope",
                "asr_fallback_provider": "dashscope",
                "asr_fallback_used": True,
                "asr_primary_error_code": "volcengine_asr_finish_failed",
                "asr_primary_error_message": "Connection to remote host was lost.",
                "asr_primary_provider_log_id": "volc-log-1",
                "provider_error_code": None,
                "provider_error_message": None,
                "provider_log_id": "dash-log-1",
                "fallback_reason": "volcengine_asr_finish_failed",
                "fallback_started_abs_ms": 1200,
                "fallback_done_abs_ms": 2200,
                "close_code": 1000,
                "close_reason": "Connection to remote host was lost.",
                "last_payload_type": 9,
                "last_log_id": "volc-log-1",
                "last_result_text": "请解释阿弥陀佛是什么意思？",
                "packets_received": 1,
            },
            error_code=None,
            error_message=None,
        )

        self.assertEqual(payload.session_id, "session-1")
        self.assertIsNone(payload.trace.first_audio_byte_ms)
        self.assertIsNone(payload.trace.tts_warmup_ms)
        self.assertIsNone(payload.trace.tts_warmup_failed)
        self.assertEqual(payload.trace.asr_primary_provider, "volcengine")
        self.assertEqual(payload.trace.asr_provider_used, "dashscope")
        self.assertEqual(payload.trace.asr_fallback_provider, "dashscope")
        self.assertTrue(payload.trace.asr_fallback_used)
        self.assertEqual(payload.trace.asr_primary_error_code, "volcengine_asr_finish_failed")
        self.assertEqual(payload.trace.asr_primary_error_message, "Connection to remote host was lost.")
        self.assertEqual(payload.trace.asr_primary_provider_log_id, "volc-log-1")
        self.assertIsNone(payload.trace.provider_error_code)
        self.assertIsNone(payload.trace.provider_error_message)
        self.assertEqual(payload.trace.provider_log_id, "dash-log-1")
        self.assertEqual(payload.trace.fallback_reason, "volcengine_asr_finish_failed")
        self.assertEqual(payload.trace.fallback_started_abs_ms, 1200)
        self.assertEqual(payload.trace.fallback_done_abs_ms, 2200)
        self.assertEqual(payload.trace.close_code, 1000)
        self.assertEqual(payload.trace.close_reason, "Connection to remote host was lost.")
        self.assertEqual(payload.trace.last_payload_type, 9)
        self.assertEqual(payload.trace.last_log_id, "volc-log-1")
        self.assertEqual(payload.trace.last_result_text, "请解释阿弥陀佛是什么意思？")
        self.assertEqual(payload.trace.packets_received, 1)

    def test_settings_expose_realtime_defaults(self) -> None:
        from src.settings import settings

        self.assertFalse(settings.realtime_enabled)
        self.assertEqual(settings.realtime_audio_sample_rate, 16000)
        self.assertEqual(settings.realtime_audio_sample_width_bits, 16)
        self.assertEqual(settings.realtime_audio_channels, 1)
        self.assertEqual(settings.realtime_audio_endian, "little")
        self.assertEqual(settings.realtime_session_ttl_seconds, 900)
        self.assertEqual(settings.realtime_tts_min_chars, 8)
        self.assertEqual(settings.realtime_tts_max_chars, 40)
        self.assertEqual(settings.realtime_tts_first_segment_min_chars, 6)
        self.assertEqual(settings.realtime_tts_first_segment_max_chars, 10)
        self.assertTrue(settings.realtime_tts_warmup_enabled)
        self.assertEqual(settings.realtime_llm_compact_top_k, 1)
        self.assertEqual(settings.realtime_llm_compact_snippet_chars, 36)

    def test_realtime_text_segmenter_prefers_sentence_punctuation(self) -> None:
        from src.services.realtime_session import split_realtime_answer_text

        segments = split_realtime_answer_text(
            "诸法因缘生。诸法因缘灭。自净其意，是诸佛教。",
            min_chars=4,
            max_chars=20,
        )

        self.assertEqual(segments, ["诸法因缘生。", "诸法因缘灭。", "自净其意，是诸佛教。"])

    def test_realtime_text_segmenter_forces_split_when_no_punctuation(self) -> None:
        from src.services.realtime_session import split_realtime_answer_text

        segments = split_realtime_answer_text(
            "一二三四五六七八九十一二三四五六七八九十一二三四五六七八九十",
            min_chars=8,
            max_chars=12,
        )

        self.assertEqual(segments, ["一二三四五六七八九十一二", "三四五六七八九十一二三四", "五六七八九十"])

    def test_realtime_text_segmenter_prefers_soft_pause_boundaries_before_hard_cut(self) -> None:
        from src.services.realtime_session import split_realtime_answer_text

        segments = split_realtime_answer_text(
            "色即是空，空即是色，受想行识，亦复如是",
            min_chars=4,
            max_chars=6,
        )

        self.assertEqual(segments, ["色即是空，", "空即是色，", "受想行识，", "亦复如是"])

    def test_realtime_stream_buffer_emits_segment_at_soft_pause_once_min_chars_reached(self) -> None:
        from src.services.realtime_session import _split_stream_buffer

        ready, remaining = _split_stream_buffer(
            "诸法无我，诸行无常",
            min_chars=4,
            max_chars=20,
        )

        self.assertEqual(ready, ["诸法无我，"])
        self.assertEqual(remaining, "诸行无常")

    def test_realtime_stream_buffer_emits_first_segment_by_shorter_limit(self) -> None:
        from src.services.realtime_session import _split_stream_buffer

        ready, remaining = _split_stream_buffer(
            "诸法因缘生起于心中",
            min_chars=8,
            max_chars=40,
            first_segment=True,
            first_segment_min_chars=6,
            first_segment_max_chars=10,
        )

        self.assertEqual(ready, ["诸法因缘生起于心中"])
        self.assertEqual(remaining, "")

    def test_realtime_stream_buffer_waits_for_first_segment_min_chars(self) -> None:
        from src.services.realtime_session import _split_stream_buffer

        ready, remaining = _split_stream_buffer(
            "诸法因缘",
            min_chars=8,
            max_chars=40,
            first_segment=True,
            first_segment_min_chars=6,
            first_segment_max_chars=10,
        )

        self.assertEqual(ready, [])
        self.assertEqual(remaining, "诸法因缘")

    def test_store_creates_and_fetches_session(self) -> None:
        from src.storage.realtime_store import InMemoryRealtimeSessionStore

        store = InMemoryRealtimeSessionStore(base_url="http://testserver")
        session = store.create_session(device_id="esp-1", input_wav_path="/tmp/test.wav")

        fetched = store.get_session(session["session_id"])

        self.assertEqual(fetched["session_id"], session["session_id"])
        self.assertEqual(fetched["status"], "accepted")
        self.assertEqual(fetched["input_wav_path"], "/tmp/test.wav")
        self.assertEqual(
            fetched["audio_stream_url"],
            f"http://testserver/api/v3/realtime/sessions/{session['session_id']}/audio",
        )
        self.assertIn("asr_primary_provider", fetched["trace"])
        self.assertIn("asr_provider_used", fetched["trace"])
        self.assertIn("asr_fallback_provider", fetched["trace"])
        self.assertIn("asr_fallback_used", fetched["trace"])
        self.assertIn("asr_primary_error_code", fetched["trace"])
        self.assertIn("asr_primary_error_message", fetched["trace"])
        self.assertIn("asr_primary_provider_log_id", fetched["trace"])
        self.assertIn("fallback_reason", fetched["trace"])
        self.assertIn("fallback_started_abs_ms", fetched["trace"])
        self.assertIn("fallback_done_abs_ms", fetched["trace"])
        self.assertIn("close_code", fetched["trace"])
        self.assertIn("close_reason", fetched["trace"])
        self.assertIn("last_payload_type", fetched["trace"])
        self.assertIn("last_log_id", fetched["trace"])
        self.assertIn("last_result_text", fetched["trace"])
        self.assertIn("packets_received", fetched["trace"])

    def test_store_claim_audio_consumer_allows_only_first_consumer(self) -> None:
        from src.storage.realtime_store import InMemoryRealtimeSessionStore

        store = InMemoryRealtimeSessionStore(base_url="http://testserver")
        session = store.create_session(device_id="esp-1")

        first_claim = store.claim_audio_consumer(session["session_id"], consumer_id="consumer-1")
        second_claim = store.claim_audio_consumer(session["session_id"], consumer_id="consumer-2")

        self.assertTrue(first_claim)
        self.assertFalse(second_claim)

    def test_store_update_session_refreshes_updated_at(self) -> None:
        from src.storage.realtime_store import InMemoryRealtimeSessionStore

        store = InMemoryRealtimeSessionStore(base_url="http://testserver")
        session = store.create_session(device_id="esp-1")

        updated = store.update_session(
            session["session_id"],
            status="running",
            step="asr",
            started_at="2026-04-09T15:34:12.260000+00:00",
        )

        self.assertEqual(updated["status"], "running")
        self.assertEqual(updated["step"], "asr")
        self.assertEqual(updated["started_at"], "2026-04-09T15:34:12.260000+00:00")
        self.assertNotEqual(updated["updated_at"], session["updated_at"])

    def test_store_mark_done_sets_final_reason_and_finished_at(self) -> None:
        from src.storage.realtime_store import InMemoryRealtimeSessionStore

        store = InMemoryRealtimeSessionStore(base_url="http://testserver")
        session = store.create_session(device_id="esp-1")

        updated = store.mark_done(
            session["session_id"],
            final_reason="completed_answer",
            answer_text="测试回答",
            done_ms=1234,
        )

        self.assertEqual(updated["status"], "done")
        self.assertEqual(updated["step"], "done")
        self.assertEqual(updated["final_reason"], "completed_answer")
        self.assertEqual(updated["answer_text"], "测试回答")
        self.assertEqual(updated["trace"]["done_ms"], 1234)
        self.assertIsNotNone(updated["finished_at"])

    def test_realtime_session_populates_elapsed_trace_metrics(self) -> None:
        from src.services import realtime_session as realtime_session_service
        from src.storage.realtime_store import InMemoryRealtimeSessionStore
        from src.providers.asr import ASRResult

        wav_path = _write_test_wav(b"\x01\x00\x02\x00")
        store = InMemoryRealtimeSessionStore(base_url="http://testserver")
        session = store.create_session(device_id="esp-1", input_wav_path="/tmp/test.wav")

        try:
            with mock.patch.object(
                realtime_session_service,
                "transcribe_wav_result",
                return_value=ASRResult("什么是无相", None, None),
            ), mock.patch.object(
                realtime_session_service,
                "retrieve_references",
                return_value=([{"source_title": "金刚经", "snippet": "应无所住而生其心", "text": "应无所住而生其心"}], 0.9),
            ), mock.patch.object(
                realtime_session_service,
                "is_buddhist_question",
                return_value=True,
            ), mock.patch.object(
                realtime_session_service,
                "stream_answer_text",
                return_value=iter(["真实回答"]),
            ), mock.patch.object(
                realtime_session_service,
                "synthesize_audio",
                return_value=(wav_path, None),
            ), mock.patch.object(
                realtime_session_service.time,
                "perf_counter",
                side_effect=[0.0, 0.01, 0.11, 0.12, 0.18, 0.26, 0.31, 0.31, 0.31, 0.44],
            ):
                realtime_session_service.run_stub_realtime_session(store, session["session_id"])

            updated = store.get_session(session["session_id"])
            self.assertEqual(updated["trace"]["asr_ms"], 100)
            self.assertEqual(updated["trace"]["retrieval_ms"], 60)
            self.assertEqual(updated["trace"]["first_llm_chunk_ms"], 260)
            self.assertEqual(updated["trace"]["first_tts_chunk_ms"], 310)
            self.assertEqual(updated["trace"]["first_audio_byte_ms"], 310)
            self.assertEqual(updated["trace"]["done_ms"], 440)
            self.assertEqual(updated["trace"]["audio_chunk_count"], 1)
            self.assertEqual(updated["trace"]["audio_bytes"], 4)
            self.assertEqual(updated["trace"]["audio_duration_ms"], 0)
            self.assertEqual(updated["trace"]["audio_stream_wall_ms"], 0)
            self.assertEqual(updated["trace"]["audio_max_chunk_gap_ms"], 0)
        finally:
            Path(wav_path).unlink(missing_ok=True)

    def test_realtime_session_logs_terminal_trace_for_post_ttl_debugging(self) -> None:
        from src.services import realtime_session as realtime_session_service
        from src.storage.realtime_store import InMemoryRealtimeSessionStore
        from src.providers.asr import ASRResult

        wav_path = _write_test_wav(b"\x01\x00\x02\x00")
        store = InMemoryRealtimeSessionStore(base_url="http://testserver")
        session = store.create_session(device_id="esp-1", input_wav_path="/tmp/test.wav")

        try:
            with mock.patch.object(
                realtime_session_service,
                "transcribe_wav_result",
                return_value=ASRResult("什么是无相", None, None),
            ), mock.patch.object(
                realtime_session_service,
                "retrieve_references",
                return_value=([{"source_title": "金刚经", "snippet": "应无所住而生其心", "text": "应无所住而生其心"}], 0.9),
            ), mock.patch.object(
                realtime_session_service,
                "is_buddhist_question",
                return_value=True,
            ), mock.patch.object(
                realtime_session_service,
                "stream_answer_text",
                return_value=iter(["真实回答"]),
            ), mock.patch.object(
                realtime_session_service,
                "synthesize_audio",
                return_value=(wav_path, None),
            ), mock.patch.object(
                realtime_session_service.logger,
                "info",
            ) as logger_info:
                realtime_session_service.run_stub_realtime_session(store, session["session_id"])

            terminal_logs = [
                call for call in logger_info.call_args_list if call.args and call.args[0] == "realtime_session_done"
            ]
            self.assertEqual(len(terminal_logs), 1)
            log_payload = terminal_logs[0].kwargs["extra"]["realtime"]
            self.assertEqual(log_payload["session_id"], session["session_id"])
            self.assertEqual(log_payload["device_id"], "esp-1")
            self.assertEqual(log_payload["status"], "done")
            self.assertEqual(log_payload["final_reason"], "completed_answer")
            self.assertEqual(log_payload["audio_bytes"], 4)
            self.assertIn("audio_max_chunk_gap_ms", log_payload)
            self.assertIn("production_ratio", log_payload)
        finally:
            Path(wav_path).unlink(missing_ok=True)

    def test_store_returns_none_for_expired_session(self) -> None:
        from src.storage.realtime_store import InMemoryRealtimeSessionStore

        store = InMemoryRealtimeSessionStore(base_url="http://testserver")
        session = store.create_session(device_id="esp-1")
        expired_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        store.update_session(session["session_id"], expires_at=expired_at)

        self.assertIsNone(store.get_session(session["session_id"]))

    def test_store_consume_audio_stream_yields_chunks_then_finishes(self) -> None:
        from src.storage.realtime_store import InMemoryRealtimeSessionStore

        store = InMemoryRealtimeSessionStore(base_url="http://testserver")
        session = store.create_session(device_id="esp-1")
        store.append_audio_chunk(session["session_id"], b"ab")
        store.append_audio_chunk(session["session_id"], b"cd")
        store.finish_audio(session["session_id"])

        chunks = list(store.consume_audio_stream(session["session_id"], idle_timeout_ms=0))

        self.assertEqual(chunks, [b"ab", b"cd"])

    def test_store_consume_audio_stream_raises_idle_timeout(self) -> None:
        from src.storage.realtime_store import InMemoryRealtimeSessionStore

        store = InMemoryRealtimeSessionStore(base_url="http://testserver")
        session = store.create_session(device_id="esp-1")
        store.append_audio_chunk(session["session_id"], b"ab")

        stream = store.consume_audio_stream(session["session_id"], idle_timeout_ms=0)

        self.assertEqual(next(stream), b"ab")
        with self.assertRaises(RuntimeError) as exc:
            next(stream)

        self.assertEqual(str(exc.exception), "stream_idle_timeout")

    def test_post_realtime_session_returns_accepted_payload(self) -> None:
        from src.api.realtime import create_realtime_session

        class _Request:
            def __init__(self, body: bytes) -> None:
                self._body = body
                self.headers = {"content-type": "application/octet-stream"}

            async def body(self) -> bytes:
                return self._body

        payload = asyncio.run(
            create_realtime_session(
                _Request(b"\x00\x00" * 16),
                x_device_id="esp-1",
                x_sample_rate=16000,
                x_sample_width=16,
                x_channels=1,
            )
        )

        self.assertEqual(payload.status, "accepted")
        self.assertIn("/api/v3/realtime/sessions/", payload.audio_stream_url)

    def test_post_realtime_session_rejects_invalid_content_type(self) -> None:
        from src.api.realtime import create_realtime_session

        class _Request:
            def __init__(self) -> None:
                self.headers = {"content-type": "audio/wav"}

            async def body(self) -> bytes:
                return b"\x00\x00" * 16

        with self.assertRaises(HTTPException) as exc:
            asyncio.run(
                create_realtime_session(
                    _Request(),
                    x_device_id="esp-1",
                    x_sample_rate=16000,
                    x_sample_width=16,
                    x_channels=1,
                )
            )

        self.assertEqual(exc.exception.status_code, 400)
        self.assertEqual(exc.exception.detail, "invalid_request")

    def test_post_realtime_session_rejects_empty_body(self) -> None:
        from src.api.realtime import create_realtime_session

        class _Request:
            def __init__(self) -> None:
                self.headers = {"content-type": "application/octet-stream"}

            async def body(self) -> bytes:
                return b""

        with self.assertRaises(HTTPException) as exc:
            asyncio.run(
                create_realtime_session(
                    _Request(),
                    x_device_id="esp-1",
                    x_sample_rate=16000,
                    x_sample_width=16,
                    x_channels=1,
                )
            )

        self.assertEqual(exc.exception.status_code, 400)
        self.assertEqual(exc.exception.detail, "empty_audio_body")

    def test_post_realtime_session_rejects_too_large_body(self) -> None:
        from src.api import realtime as realtime_api

        class _Request:
            def __init__(self) -> None:
                self.headers = {"content-type": "application/octet-stream"}

            async def body(self) -> bytes:
                return b"\x00" * 2

        with mock.patch.object(realtime_api.settings, "max_upload_mb", 0):
            with self.assertRaises(HTTPException) as exc:
                asyncio.run(
                    realtime_api.create_realtime_session(
                        _Request(),
                        x_device_id="esp-1",
                        x_sample_rate=16000,
                        x_sample_width=16,
                        x_channels=1,
                    )
                )

        self.assertEqual(exc.exception.status_code, 413)
        self.assertEqual(exc.exception.detail, "audio_too_large")

    def test_get_realtime_session_returns_session_payload(self) -> None:
        from src.api import realtime as realtime_api

        session = realtime_api.store.create_session(device_id="esp-1")
        payload = realtime_api.get_realtime_session(session["session_id"])

        self.assertEqual(payload.session_id, session["session_id"])
        self.assertEqual(payload.status, "accepted")

    def test_get_realtime_session_raises_404_when_missing(self) -> None:
        from src.api import realtime as realtime_api

        with self.assertRaises(HTTPException) as exc:
            realtime_api.get_realtime_session("missing")

        self.assertEqual(exc.exception.status_code, 404)
        self.assertEqual(exc.exception.detail, "session_not_found")

    def test_get_realtime_audio_raises_500_when_not_ready_times_out(self) -> None:
        from src.api import realtime as realtime_api

        session = realtime_api.store.create_session(device_id="esp-1")

        with mock.patch.object(realtime_api.settings, "realtime_stream_first_chunk_timeout_ms", 0):
            with self.assertRaises(HTTPException) as exc:
                realtime_api.get_realtime_audio(session["session_id"])

        self.assertEqual(exc.exception.status_code, 500)
        self.assertEqual(exc.exception.detail, "stream_first_chunk_timeout")

    def test_get_realtime_audio_returns_streaming_response_when_first_chunk_ready(self) -> None:
        from src.api import realtime as realtime_api

        session = realtime_api.store.create_session(device_id="esp-1")
        realtime_api.store.append_audio_chunk(session["session_id"], b"ab")
        realtime_api.store.finish_audio(session["session_id"])

        response = realtime_api.get_realtime_audio(session["session_id"])
        body = b"".join(response.body_iterator)
        packets = _parse_framed_packets(body)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.media_type, "application/octet-stream")
        self.assertEqual(response.headers["X-Audio-Format"], "pcm")
        self.assertEqual(response.headers["X-Audio-Packetization"], "framed-v1")
        self.assertEqual(response.headers["X-Audio-Endian"], "little")
        self.assertEqual(packets, [(0, b"ab")])

    def test_get_realtime_audio_returns_opus_when_requested_and_enabled(self) -> None:
        from src.api import realtime as realtime_api

        pcm_frame = b"\x01\x00" * 960
        session = realtime_api.store.create_session(device_id="esp-1")
        realtime_api.store.append_audio_chunk(session["session_id"], pcm_frame)
        realtime_api.store.finish_audio(session["session_id"])

        with mock.patch.object(realtime_api.settings, "realtime_audio_enable_opus", True):
            response = realtime_api.get_realtime_audio(
                session["session_id"],
                x_accept_audio_format="opus,pcm",
            )

        body = b"".join(response.body_iterator)
        packets = _parse_framed_packets(body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.media_type, "application/octet-stream")
        self.assertEqual(response.headers["X-Audio-Format"], "opus")
        self.assertEqual(response.headers["X-Audio-Packetization"], "framed-v1")
        self.assertEqual(response.headers["X-Opus-Sample-Rate"], "16000")
        self.assertEqual(response.headers["X-Opus-Channels"], "1")
        self.assertEqual(response.headers["X-Opus-Frame-Duration-Ms"], "60")
        self.assertEqual(len(packets), 1)
        self.assertEqual(packets[0][0], 0)
        self.assertGreater(len(packets[0][1]), 2)
        packet_len = int.from_bytes(packets[0][1][:2], "big")
        self.assertGreater(packet_len, 0)
        self.assertEqual(len(packets[0][1][2:]), packet_len)

    def test_get_realtime_audio_raises_500_when_first_chunk_times_out(self) -> None:
        from src.api import realtime as realtime_api

        session = realtime_api.store.create_session(device_id="esp-1")

        with mock.patch.object(realtime_api.settings, "realtime_stream_first_chunk_timeout_ms", 0):
            with self.assertRaises(HTTPException) as exc:
                realtime_api.get_realtime_audio(session["session_id"])

        self.assertEqual(exc.exception.status_code, 500)
        self.assertEqual(exc.exception.detail, "stream_first_chunk_timeout")

    def test_get_realtime_audio_raises_409_when_consumer_already_exists(self) -> None:
        from src.api import realtime as realtime_api

        session = realtime_api.store.create_session(device_id="esp-1")
        realtime_api.store.claim_audio_consumer(session["session_id"], consumer_id="consumer-1")

        with self.assertRaises(HTTPException) as exc:
            realtime_api.get_realtime_audio(session["session_id"])

        self.assertEqual(exc.exception.status_code, 409)
        self.assertEqual(exc.exception.detail, "audio_consumer_exists")

    def test_stub_producer_pushes_session_to_done_and_emits_audio(self) -> None:
        from src.api import realtime as realtime_api
        from src.services.realtime_session import run_stub_realtime_session
        from src.providers.asr import ASRResult

        session = realtime_api.store.create_session(device_id="esp-1")
        realtime_api.store.update_session(session["session_id"], input_wav_path="/tmp/test.wav")
        wav_path = _write_test_wav(b"\x01\x02\x03\x04")
        try:
            with mock.patch("src.services.realtime_session.transcribe_wav_result", return_value=ASRResult("什么是无相", None, None)), mock.patch(
                "src.services.realtime_session.retrieve_references",
                return_value=([{"source_title": "金刚经", "snippet": "应无所住而生其心", "text": "应无所住而生其心"}], 0.9),
            ), mock.patch("src.services.realtime_session.is_buddhist_question", return_value=True), mock.patch(
                "src.services.realtime_session.stream_answer_text",
                return_value=iter(["真实回答"]),
            ), mock.patch(
                "src.services.realtime_session.synthesize_audio",
                return_value=(wav_path, None),
            ):
                run_stub_realtime_session(realtime_api.store, session["session_id"])
        finally:
            Path(wav_path).unlink(missing_ok=True)

        updated = realtime_api.store.get_session(session["session_id"])

        self.assertEqual(updated["status"], "done")
        self.assertEqual(updated["step"], "done")
        self.assertEqual(updated["final_reason"], "completed_answer")
        self.assertEqual(updated["answer_text"], "真实回答")
        self.assertEqual(updated["question_text"], "什么是无相")
        self.assertIsNotNone(updated["trace"]["asr_ms"])
        self.assertIsNotNone(updated["trace"]["retrieval_ms"])
        self.assertIsNotNone(updated["trace"]["first_llm_chunk_ms"])
        self.assertIsNotNone(updated["trace"]["first_tts_chunk_ms"])
        self.assertIsNotNone(updated["trace"]["first_audio_byte_ms"])

        response = realtime_api.get_realtime_audio(session["session_id"])
        body = b"".join(response.body_iterator)
        self.assertEqual(_parse_framed_packets(body), [(0, b"\x01\x02\x03\x04")])

    def test_stub_producer_advances_session_through_expected_steps(self) -> None:
        from src.services.realtime_session import run_stub_realtime_session
        from src.storage.realtime_store import InMemoryRealtimeSessionStore
        from src.providers.asr import ASRResult

        store = InMemoryRealtimeSessionStore(base_url="http://testserver")
        session = store.create_session(device_id="esp-1", input_wav_path="/tmp/test.wav")

        observed_steps: list[str] = []
        original_update = store.update_session

        def _recording_update(session_id: str, **changes):
            updated = original_update(session_id, **changes)
            if updated is not None and "step" in changes:
                observed_steps.append(updated["step"])
            return updated

        store.update_session = _recording_update  # type: ignore[method-assign]

        wav_path = _write_test_wav(b"\x01\x02\x03\x04")
        try:
            with mock.patch("src.services.realtime_session.transcribe_wav_result", return_value=ASRResult("什么是无相", None, None)), mock.patch(
                "src.services.realtime_session.retrieve_references",
                return_value=([{"source_title": "金刚经", "snippet": "应无所住而生其心", "text": "应无所住而生其心"}], 0.9),
            ), mock.patch("src.services.realtime_session.is_buddhist_question", return_value=True), mock.patch(
                "src.services.realtime_session.stream_answer_text",
                return_value=iter(["真实回答"]),
            ), mock.patch(
                "src.services.realtime_session.synthesize_audio",
                return_value=(wav_path, None),
            ):
                run_stub_realtime_session(store, session["session_id"])
        finally:
            Path(wav_path).unlink(missing_ok=True)

        self.assertEqual(
            observed_steps,
            ["asr", "retrieval", "llm", "tts", "streaming"],
        )

    def test_realtime_session_uses_asr_result_and_retrieval(self) -> None:
        from src.services import realtime_session as realtime_session_service
        from src.storage.realtime_store import InMemoryRealtimeSessionStore
        from src.providers.asr import ASRResult

        store = InMemoryRealtimeSessionStore(base_url="http://testserver")
        session = store.create_session(device_id="esp-1", input_wav_path="/tmp/test.wav")

        wav_path = _write_test_wav(b"\x01\x02\x03\x04")
        try:
            with mock.patch.object(
                realtime_session_service,
                "transcribe_wav_result",
                return_value=ASRResult("什么是无相", None, None),
            ) as transcribe, mock.patch.object(
                realtime_session_service,
                "retrieve_references",
                return_value=([{"source_title": "金刚经", "snippet": "应无所住而生其心", "text": "应无所住而生其心"}], 0.9),
            ) as retrieve, mock.patch.object(
                realtime_session_service,
                "is_buddhist_question",
                return_value=True,
            ), mock.patch.object(
                realtime_session_service,
                "stream_answer_text",
                return_value=iter(["真实回答"]),
            ), mock.patch.object(
                realtime_session_service,
                "synthesize_audio",
                return_value=(wav_path, None),
            ):
                realtime_session_service.run_stub_realtime_session(store, session["session_id"])
        finally:
            Path(wav_path).unlink(missing_ok=True)

        updated = store.get_session(session["session_id"])
        transcribe.assert_called_once_with("/tmp/test.wav")
        retrieve.assert_called_once_with("什么是无相", top_k=realtime_session_service.settings.top_k)
        self.assertEqual(updated["question_text"], "什么是无相")
        self.assertEqual(updated["final_reason"], "completed_answer")

    def test_realtime_session_marks_failed_when_asr_returns_error(self) -> None:
        from src.services import realtime_session as realtime_session_service
        from src.storage.realtime_store import InMemoryRealtimeSessionStore
        from src.providers.asr import ASRResult

        store = InMemoryRealtimeSessionStore(base_url="http://testserver")
        session = store.create_session(device_id="esp-1", input_wav_path="/tmp/test.wav")

        with mock.patch.object(
            realtime_session_service,
            "transcribe_wav_result",
            return_value=ASRResult(None, "asr_empty_text", "empty"),
        ):
            realtime_session_service.run_stub_realtime_session(store, session["session_id"])

        updated = store.get_session(session["session_id"])
        self.assertEqual(updated["status"], "failed")
        self.assertEqual(updated["step"], "failed")
        self.assertEqual(updated["final_reason"], "failed")
        self.assertEqual(updated["error_code"], "asr_empty_text")

    def test_realtime_session_marks_reject_when_retrieval_below_threshold(self) -> None:
        from src.services import realtime_session as realtime_session_service
        from src.storage.realtime_store import InMemoryRealtimeSessionStore
        from src.providers.asr import ASRResult

        store = InMemoryRealtimeSessionStore(base_url="http://testserver")
        session = store.create_session(device_id="esp-1", input_wav_path="/tmp/test.wav")

        with mock.patch.object(
            realtime_session_service,
            "transcribe_wav_result",
            return_value=ASRResult("什么是无相", None, None),
        ), mock.patch.object(
            realtime_session_service,
            "retrieve_references",
            return_value=([], 0.0),
        ), mock.patch.object(
            realtime_session_service,
            "is_buddhist_question",
            return_value=True,
        ):
            realtime_session_service.run_stub_realtime_session(store, session["session_id"])

        updated = store.get_session(session["session_id"])
        self.assertEqual(updated["status"], "done")
        self.assertEqual(updated["final_reason"], "completed_reject")
        self.assertEqual(updated["answer_text"], "佛说不可曰")

    def test_realtime_session_marks_failed_when_retrieval_raises(self) -> None:
        from src.services import realtime_session as realtime_session_service
        from src.storage.realtime_store import InMemoryRealtimeSessionStore
        from src.providers.asr import ASRResult

        store = InMemoryRealtimeSessionStore(base_url="http://testserver")
        session = store.create_session(device_id="esp-1", input_wav_path="/tmp/test.wav")

        with mock.patch.object(
            realtime_session_service,
            "transcribe_wav_result",
            return_value=ASRResult("什么是无相", None, None),
        ), mock.patch.object(
            realtime_session_service,
            "retrieve_references",
            side_effect=FileNotFoundError("buddhism index not found; run ingest first"),
        ):
            realtime_session_service.run_stub_realtime_session(store, session["session_id"])

        updated = store.get_session(session["session_id"])
        self.assertEqual(updated["status"], "failed")
        self.assertEqual(updated["step"], "failed")
        self.assertEqual(updated["error_code"], "retrieval_unavailable")

    def test_realtime_session_uses_stream_answer_text_for_non_reject_path(self) -> None:
        from src.services import realtime_session as realtime_session_service
        from src.storage.realtime_store import InMemoryRealtimeSessionStore
        from src.providers.asr import ASRResult

        references = [{"source_title": "金刚经", "snippet": "应无所住而生其心", "text": "应无所住而生其心"}]
        store = InMemoryRealtimeSessionStore(base_url="http://testserver")
        session = store.create_session(device_id="esp-1", input_wav_path="/tmp/test.wav")

        wav_path = _write_test_wav(b"\x01\x02\x03\x04")
        try:
            with mock.patch.object(
                realtime_session_service,
                "transcribe_wav_result",
                return_value=ASRResult("什么是无相", None, None),
            ), mock.patch.object(
                realtime_session_service,
                "retrieve_references",
                return_value=(references, 0.9),
            ), mock.patch.object(
                realtime_session_service,
                "is_buddhist_question",
                return_value=True,
            ), mock.patch.object(
                realtime_session_service,
                "stream_answer_text",
                return_value=iter(["真实回答"]),
            ) as stream_answer_text, mock.patch.object(
                realtime_session_service,
                "synthesize_audio",
                return_value=(wav_path, None),
            ):
                realtime_session_service.run_stub_realtime_session(store, session["session_id"])
        finally:
            Path(wav_path).unlink(missing_ok=True)

        updated = store.get_session(session["session_id"])
        stream_answer_text.assert_called_once_with("什么是无相", references)
        self.assertEqual(updated["status"], "done")
        self.assertEqual(updated["final_reason"], "completed_answer")
        self.assertEqual(updated["answer_text"], "真实回答")

    def test_realtime_session_marks_failed_when_stream_answer_text_raises(self) -> None:
        from src.services import realtime_session as realtime_session_service
        from src.storage.realtime_store import InMemoryRealtimeSessionStore
        from src.providers.asr import ASRResult

        store = InMemoryRealtimeSessionStore(base_url="http://testserver")
        session = store.create_session(device_id="esp-1", input_wav_path="/tmp/test.wav")

        with mock.patch.object(
            realtime_session_service,
            "transcribe_wav_result",
            return_value=ASRResult("什么是无相", None, None),
        ), mock.patch.object(
            realtime_session_service,
            "retrieve_references",
            return_value=([{"source_title": "金刚经", "snippet": "应无所住而生其心", "text": "应无所住而生其心"}], 0.9),
        ), mock.patch.object(
            realtime_session_service,
            "is_buddhist_question",
            return_value=True,
        ), mock.patch.object(
            realtime_session_service,
            "stream_answer_text",
            side_effect=RuntimeError("boom"),
        ):
            realtime_session_service.run_stub_realtime_session(store, session["session_id"])

        updated = store.get_session(session["session_id"])
        self.assertEqual(updated["status"], "failed")
        self.assertEqual(updated["step"], "failed")
        self.assertEqual(updated["final_reason"], "failed")
        self.assertEqual(updated["error_code"], "llm_request_failed")

    def test_realtime_session_uses_tts_wav_frames_as_pcm_stream(self) -> None:
        from src.services import realtime_session as realtime_session_service
        from src.storage.realtime_store import InMemoryRealtimeSessionStore
        from src.providers.asr import ASRResult

        pcm_bytes = b"\x10\x00\x20\x00\x30\x00\x40\x00"
        wav_path = _write_test_wav(pcm_bytes)
        store = InMemoryRealtimeSessionStore(base_url="http://testserver")
        session = store.create_session(device_id="esp-1", input_wav_path="/tmp/test.wav")

        try:
            with mock.patch.object(
                realtime_session_service,
                "transcribe_wav_result",
                return_value=ASRResult("什么是无相", None, None),
            ), mock.patch.object(
                realtime_session_service,
                "retrieve_references",
                return_value=([{"source_title": "金刚经", "snippet": "应无所住而生其心", "text": "应无所住而生其心"}], 0.9),
            ), mock.patch.object(
                realtime_session_service,
                "is_buddhist_question",
                return_value=True,
            ), mock.patch.object(
                realtime_session_service,
                "stream_answer_text",
                return_value=iter(["真实回答"]),
            ), mock.patch.object(
                realtime_session_service,
                "synthesize_audio",
                return_value=(wav_path, None),
            ):
                realtime_session_service.run_stub_realtime_session(store, session["session_id"])

            updated = store.get_session(session["session_id"])
            self.assertEqual(updated["status"], "done")
            self.assertIsNotNone(updated["trace"]["first_tts_chunk_ms"])
            self.assertEqual(list(store.consume_audio_stream(session["session_id"], idle_timeout_ms=0)), [pcm_bytes])
        finally:
            Path(wav_path).unlink(missing_ok=True)

    def test_realtime_session_prefers_realtime_tts_when_configured(self) -> None:
        from src.services import realtime_session as realtime_session_service
        from src.storage.realtime_store import InMemoryRealtimeSessionStore
        from src.providers.asr import ASRResult

        store = InMemoryRealtimeSessionStore(base_url="http://testserver")
        session = store.create_session(device_id="esp-1", input_wav_path="/tmp/test.wav")
        observed_segments: list[str] = []

        def _stream_realtime_tts_chunks(text_chunks):
            observed_segments.extend(list(text_chunks))
            return iter([b"\x01\x00\x02\x00", b"\x03\x00\x04\x00"])

        with mock.patch.object(
            realtime_session_service,
            "transcribe_wav_result",
            return_value=ASRResult("什么是无相", None, None),
        ), mock.patch.object(
            realtime_session_service,
            "retrieve_references",
            return_value=([{"source_title": "金刚经", "snippet": "应无所住而生其心", "text": "应无所住而生其心"}], 0.9),
        ), mock.patch.object(
            realtime_session_service,
            "is_buddhist_question",
            return_value=True,
        ), mock.patch.object(
            realtime_session_service,
            "stream_answer_text",
            return_value=iter(["诸法因缘生。", "诸法因缘灭。"]),
        ), mock.patch.object(
            realtime_session_service,
            "realtime_tts_health",
            return_value=True,
        ), mock.patch.object(
            realtime_session_service,
            "stream_realtime_tts_chunks",
            side_effect=_stream_realtime_tts_chunks,
        ) as stream_realtime_tts_chunks, mock.patch.object(
            realtime_session_service,
            "synthesize_audio",
        ) as synthesize_audio:
            realtime_session_service.run_stub_realtime_session(store, session["session_id"])

        updated = store.get_session(session["session_id"])
        self.assertEqual(updated["status"], "done")
        stream_realtime_tts_chunks.assert_called_once()
        self.assertEqual(observed_segments, ["诸法因缘生。", "诸法因缘灭。"])
        synthesize_audio.assert_not_called()
        self.assertEqual(
            list(store.consume_audio_stream(session["session_id"], idle_timeout_ms=0)),
            [b"\x01\x00\x02\x00", b"\x03\x00\x04\x00"],
        )

    def test_realtime_session_uses_compact_references_for_realtime_llm(self) -> None:
        from src.services import realtime_session as realtime_session_service
        from src.storage.realtime_store import InMemoryRealtimeSessionStore
        from src.providers.asr import ASRResult
        from src.providers.realtime_tts import RealtimeTtsError

        references = [
            {"source_title": "金刚经", "snippet": "一二三四五六七八九十一二三四五六七八九十", "text": "一二三四五六七八九十一二三四五六七八九十"},
            {"source_title": "楞严经", "snippet": "第二条证据", "text": "第二条证据"},
        ]
        store = InMemoryRealtimeSessionStore(base_url="http://testserver")
        session = store.create_session(device_id="esp-1", input_wav_path="/tmp/test.wav")
        observed_references: list[dict] = []

        def _stream_answer_text(_question_text: str, refs: list[dict]):
            observed_references.extend(refs)
            yield "真实回答"

        def _stream_realtime_tts_chunks(text_chunks, **kwargs):
            del kwargs
            list(text_chunks)
            return iter([b"\x01\x00"])

        with mock.patch.object(
            realtime_session_service,
            "transcribe_wav_result",
            return_value=ASRResult("什么是无相", None, None),
        ), mock.patch.object(
            realtime_session_service,
            "retrieve_references",
            return_value=(references, 0.9),
        ), mock.patch.object(
            realtime_session_service,
            "is_buddhist_question",
            return_value=True,
        ), mock.patch.object(
            realtime_session_service,
            "realtime_tts_health",
            return_value=True,
        ), mock.patch.object(
            realtime_session_service,
            "warmup_realtime_tts_session",
            side_effect=RealtimeTtsError("warmup_failed", "warmup_failed"),
        ), mock.patch.object(
            realtime_session_service,
            "stream_answer_text",
            side_effect=_stream_answer_text,
        ), mock.patch.object(
            realtime_session_service,
            "stream_realtime_tts_chunks",
            side_effect=_stream_realtime_tts_chunks,
        ):
            realtime_session_service.run_stub_realtime_session(store, session["session_id"])

        updated = store.get_session(session["session_id"])
        self.assertEqual(len(observed_references), 1)
        self.assertEqual(observed_references[0]["source_title"], "金刚经")
        self.assertLessEqual(
            len(observed_references[0]["snippet"]),
            realtime_session_service.settings.realtime_llm_compact_snippet_chars,
        )
        self.assertTrue(updated["trace"]["tts_warmup_failed"])

    def test_realtime_session_skips_compact_references_when_disabled(self) -> None:
        from src.services import realtime_session as realtime_session_service
        from src.storage.realtime_store import InMemoryRealtimeSessionStore
        from src.providers.asr import ASRResult

        references = [
            {"source_title": "金刚经", "snippet": "第一条很长的证据文本", "text": "第一条很长的证据文本"},
            {"source_title": "楞严经", "snippet": "第二条证据", "text": "第二条证据"},
        ]
        store = InMemoryRealtimeSessionStore(base_url="http://testserver")
        session = store.create_session(device_id="esp-1", input_wav_path="/tmp/test.wav")
        observed_references: list[dict] = []

        def _stream_answer_text(_question_text: str, refs: list[dict]):
            observed_references.extend(refs)
            yield "真实回答"

        def _stream_realtime_tts_chunks(text_chunks, **kwargs):
            del kwargs
            list(text_chunks)
            return iter([b"\x01\x00"])

        with mock.patch.object(
            realtime_session_service.settings,
            "realtime_llm_compact_top_k",
            0,
        ), mock.patch.object(
            realtime_session_service,
            "transcribe_wav_result",
            return_value=ASRResult("什么是无相", None, None),
        ), mock.patch.object(
            realtime_session_service,
            "retrieve_references",
            return_value=(references, 0.9),
        ), mock.patch.object(
            realtime_session_service,
            "is_buddhist_question",
            return_value=True,
        ), mock.patch.object(
            realtime_session_service,
            "realtime_tts_health",
            return_value=True,
        ), mock.patch.object(
            realtime_session_service,
            "stream_answer_text",
            side_effect=_stream_answer_text,
        ), mock.patch.object(
            realtime_session_service,
            "stream_realtime_tts_chunks",
            side_effect=_stream_realtime_tts_chunks,
        ):
            realtime_session_service.run_stub_realtime_session(store, session["session_id"])

        self.assertEqual(len(observed_references), 2)

    def test_realtime_session_skips_warmup_when_disabled(self) -> None:
        from src.services import realtime_session as realtime_session_service
        from src.storage.realtime_store import InMemoryRealtimeSessionStore
        from src.providers.asr import ASRResult

        store = InMemoryRealtimeSessionStore(base_url="http://testserver")
        session = store.create_session(device_id="esp-1", input_wav_path="/tmp/test.wav")

        def _stream_realtime_tts_chunks(text_chunks, **kwargs):
            del kwargs
            list(text_chunks)
            return iter([b"\x01\x00"])

        with mock.patch.object(
            realtime_session_service.settings,
            "realtime_tts_warmup_enabled",
            False,
        ), mock.patch.object(
            realtime_session_service,
            "transcribe_wav_result",
            return_value=ASRResult("什么是无相", None, None),
        ), mock.patch.object(
            realtime_session_service,
            "retrieve_references",
            return_value=([{"source_title": "金刚经", "snippet": "应无所住而生其心", "text": "应无所住而生其心"}], 0.9),
        ), mock.patch.object(
            realtime_session_service,
            "is_buddhist_question",
            return_value=True,
        ), mock.patch.object(
            realtime_session_service,
            "realtime_tts_health",
            return_value=True,
        ), mock.patch.object(
            realtime_session_service,
            "warmup_realtime_tts_session",
        ) as warmup_realtime_tts_session, mock.patch.object(
            realtime_session_service,
            "stream_answer_text",
            return_value=iter(["真实回答"]),
        ), mock.patch.object(
            realtime_session_service,
            "stream_realtime_tts_chunks",
            side_effect=_stream_realtime_tts_chunks,
        ):
            realtime_session_service.run_stub_realtime_session(store, session["session_id"])

        updated = store.get_session(session["session_id"])
        warmup_realtime_tts_session.assert_not_called()
        self.assertEqual(updated["status"], "done")
        self.assertIsNone(updated["trace"]["tts_warmup_ms"])
        self.assertIsNone(updated["trace"]["tts_warmup_failed"])

    def test_realtime_session_warmup_failure_does_not_fail_main_flow(self) -> None:
        from src.services import realtime_session as realtime_session_service
        from src.storage.realtime_store import InMemoryRealtimeSessionStore
        from src.providers.asr import ASRResult

        store = InMemoryRealtimeSessionStore(base_url="http://testserver")
        session = store.create_session(device_id="esp-1", input_wav_path="/tmp/test.wav")

        def _stream_realtime_tts_chunks(text_chunks, **kwargs):
            del kwargs
            list(text_chunks)
            return iter([b"\x01\x00"])

        with mock.patch.object(
            realtime_session_service,
            "transcribe_wav_result",
            return_value=ASRResult("什么是无相", None, None),
        ), mock.patch.object(
            realtime_session_service,
            "retrieve_references",
            return_value=([{"source_title": "金刚经", "snippet": "应无所住而生其心", "text": "应无所住而生其心"}], 0.9),
        ), mock.patch.object(
            realtime_session_service,
            "is_buddhist_question",
            return_value=True,
        ), mock.patch.object(
            realtime_session_service,
            "realtime_tts_health",
            return_value=True,
        ), mock.patch.object(
            realtime_session_service,
            "warmup_realtime_tts_session",
            side_effect=RuntimeError("boom"),
        ), mock.patch.object(
            realtime_session_service,
            "stream_answer_text",
            return_value=iter(["真实回答"]),
        ), mock.patch.object(
            realtime_session_service,
            "stream_realtime_tts_chunks",
            side_effect=_stream_realtime_tts_chunks,
        ):
            realtime_session_service.run_stub_realtime_session(store, session["session_id"])

        updated = store.get_session(session["session_id"])
        self.assertEqual(updated["status"], "done")
        self.assertTrue(updated["trace"]["tts_warmup_failed"])
        self.assertIsNotNone(updated["trace"]["tts_warmup_ms"])

    def test_realtime_session_starts_realtime_tts_before_llm_stream_finishes(self) -> None:
        from src.services import realtime_session as realtime_session_service
        from src.storage.realtime_store import InMemoryRealtimeSessionStore
        from src.providers.asr import ASRResult

        store = InMemoryRealtimeSessionStore(base_url="http://testserver")
        session = store.create_session(device_id="esp-1", input_wav_path="/tmp/test.wav")
        state = {"first_segment_started": False}

        def _stream_answer_text(_question_text: str, _references: list[dict]):
            yield "诸法因缘生。"
            self.assertTrue(state["first_segment_started"])
            yield "诸法因缘灭。"

        def _stream_realtime_tts_chunks(text_chunks):
            for segment in text_chunks:
                if segment == "诸法因缘生。":
                    state["first_segment_started"] = True
                    yield b"\x01\x00"
                    continue
                current = store.get_session(session["session_id"])
                self.assertEqual(current["step"], "streaming")
                yield b"\x02\x00"

        with mock.patch.object(
            realtime_session_service,
            "transcribe_wav_result",
            return_value=ASRResult("什么是无相", None, None),
        ), mock.patch.object(
            realtime_session_service,
            "retrieve_references",
            return_value=([{"source_title": "金刚经", "snippet": "应无所住而生其心", "text": "应无所住而生其心"}], 0.9),
        ), mock.patch.object(
            realtime_session_service,
            "is_buddhist_question",
            return_value=True,
        ), mock.patch.object(
            realtime_session_service,
            "stream_answer_text",
            side_effect=_stream_answer_text,
        ), mock.patch.object(
            realtime_session_service,
            "realtime_tts_health",
            return_value=True,
        ), mock.patch.object(
            realtime_session_service,
            "stream_realtime_tts_chunks",
            side_effect=_stream_realtime_tts_chunks,
        ), mock.patch.object(
            realtime_session_service,
            "synthesize_audio",
        ) as synthesize_audio:
            realtime_session_service.run_stub_realtime_session(store, session["session_id"])

        updated = store.get_session(session["session_id"])
        self.assertEqual(updated["status"], "done")
        synthesize_audio.assert_not_called()
        self.assertEqual(list(store.consume_audio_stream(session["session_id"], idle_timeout_ms=0)), [b"\x01\x00", b"\x02\x00"])

    def test_realtime_session_falls_back_to_wav_tts_when_realtime_tts_unavailable(self) -> None:
        from src.services import realtime_session as realtime_session_service
        from src.storage.realtime_store import InMemoryRealtimeSessionStore
        from src.providers.asr import ASRResult

        wav_path = _write_test_wav(b"\x01\x00\x02\x00")
        store = InMemoryRealtimeSessionStore(base_url="http://testserver")
        session = store.create_session(device_id="esp-1", input_wav_path="/tmp/test.wav")

        try:
            with mock.patch.object(
                realtime_session_service,
                "transcribe_wav_result",
                return_value=ASRResult("什么是无相", None, None),
            ), mock.patch.object(
                realtime_session_service,
                "retrieve_references",
                return_value=([{"source_title": "金刚经", "snippet": "应无所住而生其心", "text": "应无所住而生其心"}], 0.9),
            ), mock.patch.object(
                realtime_session_service,
                "is_buddhist_question",
                return_value=True,
            ), mock.patch.object(
                realtime_session_service,
                "stream_answer_text",
                return_value=iter(["真实回答"]),
            ), mock.patch.object(
                realtime_session_service,
                "realtime_tts_health",
                return_value=False,
            ), mock.patch.object(
                realtime_session_service,
                "stream_realtime_tts_chunks",
            ) as stream_realtime_tts_chunks, mock.patch.object(
                realtime_session_service,
                "synthesize_audio",
                return_value=(wav_path, None),
            ) as synthesize_audio:
                realtime_session_service.run_stub_realtime_session(store, session["session_id"])

            updated = store.get_session(session["session_id"])
            self.assertEqual(updated["status"], "done")
            stream_realtime_tts_chunks.assert_not_called()
            synthesize_audio.assert_called_once_with("真实回答")
        finally:
            Path(wav_path).unlink(missing_ok=True)

    def test_realtime_session_synthesizes_answer_in_multiple_segments(self) -> None:
        from src.services import realtime_session as realtime_session_service
        from src.storage.realtime_store import InMemoryRealtimeSessionStore
        from src.providers.asr import ASRResult

        wav_path_1 = _write_test_wav(b"\x01\x00\x02\x00")
        wav_path_2 = _write_test_wav(b"\x03\x00\x04\x00")
        store = InMemoryRealtimeSessionStore(base_url="http://testserver")
        session = store.create_session(device_id="esp-1", input_wav_path="/tmp/test.wav")

        try:
            with mock.patch.object(
                realtime_session_service,
                "transcribe_wav_result",
                return_value=ASRResult("什么是无相", None, None),
            ), mock.patch.object(
                realtime_session_service,
                "retrieve_references",
                return_value=([{"source_title": "金刚经", "snippet": "应无所住而生其心", "text": "应无所住而生其心"}], 0.9),
            ), mock.patch.object(
                realtime_session_service,
                "is_buddhist_question",
                return_value=True,
            ), mock.patch.object(
                realtime_session_service,
                "stream_answer_text",
                return_value=iter(["诸法因缘生。", "诸法因缘灭。"]),
            ), mock.patch.object(
                realtime_session_service,
                "synthesize_audio",
                side_effect=[(wav_path_1, None), (wav_path_2, None)],
            ) as synthesize_audio:
                realtime_session_service.run_stub_realtime_session(store, session["session_id"])

            updated = store.get_session(session["session_id"])
            self.assertEqual(updated["status"], "done")
            self.assertEqual(
                [call.args[0] for call in synthesize_audio.call_args_list],
                ["诸法因缘生。", "诸法因缘灭。"],
            )
            self.assertEqual(
                list(store.consume_audio_stream(session["session_id"], idle_timeout_ms=0)),
                [b"\x01\x00\x02\x00", b"\x03\x00\x04\x00"],
            )
        finally:
            Path(wav_path_1).unlink(missing_ok=True)
            Path(wav_path_2).unlink(missing_ok=True)

    def test_realtime_session_starts_streaming_before_all_tts_segments_finish(self) -> None:
        from src.services import realtime_session as realtime_session_service
        from src.storage.realtime_store import InMemoryRealtimeSessionStore
        from src.providers.asr import ASRResult

        wav_path_1 = _write_test_wav(b"\x01\x00\x02\x00")
        wav_path_2 = _write_test_wav(b"\x03\x00\x04\x00")
        store = InMemoryRealtimeSessionStore(base_url="http://testserver")
        session = store.create_session(device_id="esp-1", input_wav_path="/tmp/test.wav")
        stream_state = {"first_tts_called": False}

        def _stream_answer_text(_question_text: str, _references: list[dict]):
            yield "诸法因缘生。"
            self.assertTrue(stream_state["first_tts_called"])
            yield "诸法因缘灭。"

        def _synthesize_audio_side_effect(text: str):
            if text == "诸法因缘生。":
                stream_state["first_tts_called"] = True
                return wav_path_1, None
            current = store.get_session(session["session_id"])
            self.assertEqual(current["step"], "streaming")
            store.wait_for_first_audio_chunk(session["session_id"], timeout_ms=0)
            return wav_path_2, None

        try:
            with mock.patch.object(
                realtime_session_service,
                "transcribe_wav_result",
                return_value=ASRResult("什么是无相", None, None),
            ), mock.patch.object(
                realtime_session_service,
                "retrieve_references",
                return_value=([{"source_title": "金刚经", "snippet": "应无所住而生其心", "text": "应无所住而生其心"}], 0.9),
            ), mock.patch.object(
                realtime_session_service,
                "is_buddhist_question",
                return_value=True,
            ), mock.patch.object(
                realtime_session_service,
                "stream_answer_text",
                side_effect=_stream_answer_text,
            ), mock.patch.object(
                realtime_session_service,
                "synthesize_audio",
                side_effect=_synthesize_audio_side_effect,
            ):
                realtime_session_service.run_stub_realtime_session(store, session["session_id"])
        finally:
            Path(wav_path_1).unlink(missing_ok=True)
            Path(wav_path_2).unlink(missing_ok=True)

    def test_realtime_session_marks_failed_when_tts_returns_error(self) -> None:
        from src.services import realtime_session as realtime_session_service
        from src.storage.realtime_store import InMemoryRealtimeSessionStore
        from src.providers.asr import ASRResult

        store = InMemoryRealtimeSessionStore(base_url="http://testserver")
        session = store.create_session(device_id="esp-1", input_wav_path="/tmp/test.wav")

        with mock.patch.object(
            realtime_session_service,
            "transcribe_wav_result",
            return_value=ASRResult("什么是无相", None, None),
        ), mock.patch.object(
            realtime_session_service,
            "retrieve_references",
            return_value=([{"source_title": "金刚经", "snippet": "应无所住而生其心", "text": "应无所住而生其心"}], 0.9),
        ), mock.patch.object(
            realtime_session_service,
            "is_buddhist_question",
            return_value=True,
        ), mock.patch.object(
            realtime_session_service,
            "stream_answer_text",
            return_value=iter(["真实回答"]),
        ), mock.patch.object(
            realtime_session_service,
            "synthesize_audio",
            return_value=(None, "dashscope_request_failed"),
        ):
            realtime_session_service.run_stub_realtime_session(store, session["session_id"])

        updated = store.get_session(session["session_id"])
        self.assertEqual(updated["status"], "failed")
        self.assertEqual(updated["step"], "failed")
        self.assertEqual(updated["error_code"], "dashscope_request_failed")

    def test_post_realtime_session_starts_background_stub_producer(self) -> None:
        from src.api import realtime as realtime_api

        class _Request:
            def __init__(self, body: bytes) -> None:
                self._body = body
                self.headers = {"content-type": "application/octet-stream"}

            async def body(self) -> bytes:
                return self._body

        with mock.patch.object(realtime_api, "start_realtime_session") as start_stub:
            payload = asyncio.run(
                realtime_api.create_realtime_session(
                    _Request(b"\x00\x00" * 16),
                    x_device_id="esp-1",
                    x_sample_rate=16000,
                    x_sample_width=16,
                    x_channels=1,
                )
            )

        start_stub.assert_called_once()
        self.assertEqual(start_stub.call_args.args[0], realtime_api.store)
        self.assertEqual(start_stub.call_args.args[1], payload.session_id)

    def test_service_start_realtime_session_spawns_background_worker(self) -> None:
        from src.services import realtime_session as realtime_session_service
        from src.storage.realtime_store import InMemoryRealtimeSessionStore

        store = InMemoryRealtimeSessionStore(base_url="http://testserver")
        session = store.create_session(device_id="esp-1")

        with mock.patch.object(realtime_session_service.threading, "Thread") as thread_cls:
            realtime_session_service.start_realtime_session(store, session["session_id"])

        thread_cls.assert_called_once()

    def test_realtime_session_from_pretranscribed_question_skips_file_asr(self) -> None:
        from src.services import realtime_session as realtime_session_service
        from src.storage.realtime_store import InMemoryRealtimeSessionStore

        wav_path = _write_test_wav(b"\x01\x00\x02\x00")
        store = InMemoryRealtimeSessionStore(base_url="http://testserver")
        session = store.create_session(device_id="esp-1")
        question_text = "请解释阿弥陀佛是什么意思"
        store.update_session(session["session_id"], question_text=question_text)

        try:
            with mock.patch.object(
                realtime_session_service,
                "transcribe_wav_result",
            ) as transcribe_wav_result, mock.patch.object(
                realtime_session_service,
                "retrieve_references",
                return_value=([{"source_title": "阿弥陀佛", "snippet": "无量光寿", "text": "无量光寿"}], 0.9),
            ) as retrieve_references, mock.patch.object(
                realtime_session_service,
                "is_buddhist_question",
                return_value=True,
            ), mock.patch.object(
                realtime_session_service,
                "stream_answer_text",
                return_value=iter(["阿弥陀佛是无量光寿。"]),
            ), mock.patch.object(
                realtime_session_service,
                "realtime_tts_health",
                return_value=False,
            ), mock.patch.object(
                realtime_session_service,
                "synthesize_audio",
                return_value=(wav_path, None),
            ):
                realtime_session_service.run_stub_realtime_session(store, session["session_id"])
        finally:
            Path(wav_path).unlink(missing_ok=True)

        transcribe_wav_result.assert_not_called()
        retrieve_references.assert_called_once_with(question_text, top_k=mock.ANY)
        updated = store.get_session(session["session_id"])
        self.assertEqual(updated["status"], "done")
        self.assertEqual(updated["question_text"], question_text)
        self.assertEqual(updated["trace"]["retrieval_top_score"], 0.9)


if __name__ == "__main__":
    unittest.main()
