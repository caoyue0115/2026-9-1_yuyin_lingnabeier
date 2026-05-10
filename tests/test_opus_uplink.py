from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import tempfile
import time
import types
import unittest
import wave
from pathlib import Path
from unittest import mock

from tests._stubs import install_dependency_stubs

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

install_dependency_stubs()

from fastapi import HTTPException


def _write_test_wav(pcm_bytes: bytes, *, sample_rate: int = 16000, channels: int = 1) -> str:
    fd, path = tempfile.mkstemp(suffix=".wav")
    Path(path).unlink(missing_ok=True)
    with wave.open(path, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(pcm_bytes)
    return path


def _outer_frame(sequence: int, payload: bytes) -> bytes:
    return sequence.to_bytes(4, "big") + len(payload).to_bytes(4, "big") + payload


def _load_opus_uplink_script():
    script_path = ROOT / "scripts" / "opus_uplink_smoke.py"
    spec = importlib.util.spec_from_file_location("opus_uplink_smoke", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["opus_uplink_smoke"] = module
    spec.loader.exec_module(module)
    return module


def _load_opus_uplink_stream_script():
    script_path = ROOT / "scripts" / "opus_uplink_stream_smoke.py"
    spec = importlib.util.spec_from_file_location("opus_uplink_stream_smoke", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["opus_uplink_stream_smoke"] = module
    spec.loader.exec_module(module)
    return module


def _load_v5_streaming_latency_eval_script():
    script_path = ROOT / "scripts" / "v5_streaming_latency_eval.py"
    spec = importlib.util.spec_from_file_location("v5_streaming_latency_eval", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["v5_streaming_latency_eval"] = module
    spec.loader.exec_module(module)
    return module


def _load_v5_asr_only_repeat_eval_script():
    script_path = ROOT / "scripts" / "v5_asr_only_repeat_eval.py"
    spec = importlib.util.spec_from_file_location("v5_asr_only_repeat_eval", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["v5_asr_only_repeat_eval"] = module
    spec.loader.exec_module(module)
    return module


def _load_v5_full_chain_repeat_eval_script():
    script_path = ROOT / "scripts" / "v5_full_chain_repeat_eval.py"
    spec = importlib.util.spec_from_file_location("v5_full_chain_repeat_eval", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["v5_full_chain_repeat_eval"] = module
    spec.loader.exec_module(module)
    return module


def _load_v5_real_voice_eval_script():
    script_path = ROOT / "scripts" / "v5_real_voice_eval.py"
    spec = importlib.util.spec_from_file_location("v5_real_voice_eval", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["v5_real_voice_eval"] = module
    spec.loader.exec_module(module)
    return module


class _FakeWebSocket:
    def __init__(self, incoming: list[dict]) -> None:
        self._incoming = list(incoming)
        self.accepted = False
        self.sent_json: list[dict] = []
        self.close_code: int | None = None

    async def accept(self) -> None:
        self.accepted = True

    async def receive(self) -> dict:
        if self._incoming:
            return self._incoming.pop(0)
        return {"type": "websocket.disconnect"}

    async def send_json(self, payload: dict) -> None:
        self.sent_json.append(payload)

    async def close(self, code: int = 1000) -> None:
        self.close_code = code


class _FakeStreamingAsrAdapter:
    def __init__(
        self,
        *,
        text: str | None = "请解释阿弥陀佛是什么意思",
        error_code: str | None = None,
        request_id: str = "req-test",
        start_delay_seconds: float = 0.0,
    ) -> None:
        self.text = text
        self.error_code = error_code
        self.request_id = request_id
        self.start_delay_seconds = start_delay_seconds
        self.started = False
        self.pcm_chunks: list[bytes] = []

    def start(self) -> None:
        if self.start_delay_seconds:
            time.sleep(self.start_delay_seconds)
        self.started = True

    def send_pcm_chunk(self, pcm_chunk: bytes) -> list:
        self.pcm_chunks.append(pcm_chunk)
        return []

    def drain_events(self) -> list:
        return []

    def finish(self):
        from src.providers.realtime_asr import RealtimeAsrResult

        return RealtimeAsrResult(
            text=self.text,
            error_code=self.error_code,
            error_message=self.error_code,
            first_asr_partial_ms=33 if self.text else None,
            asr_final_ms=123 if self.text else None,
            request_id=self.request_id,
        )


class OpusUplinkProviderTests(unittest.TestCase):
    def test_parse_framed_v1_packets_rejects_truncated_packet(self) -> None:
        from src.providers.opus import OpusError, parse_framed_v1_packets

        with self.assertRaisesRegex(OpusError, "framed_packet_truncated"):
            parse_framed_v1_packets(b"\x00\x00\x00\x00\x00\x00\x00\x04ab")

    def test_parse_framed_v1_packets_accepts_expected_sequence_offset(self) -> None:
        from src.providers.opus import parse_framed_v1_packets

        packets = parse_framed_v1_packets(_outer_frame(2, b"payload"), expected_sequence=2)

        self.assertEqual(packets, [(2, b"payload")])

    def test_decode_framed_opus_to_pcm_rejects_truncated_inner_packet(self) -> None:
        from src.providers.opus import OpusError, decode_framed_opus_to_pcm

        bad_inner = (4).to_bytes(2, "big") + b"ab"
        with self.assertRaisesRegex(OpusError, "opus_packet_truncated"):
            decode_framed_opus_to_pcm(
                [_outer_frame(0, bad_inner)],
                sample_rate=16000,
                channels=1,
                frame_duration_ms=60,
            )

    def test_opus_encode_decode_roundtrip_returns_pcm_bytes(self) -> None:
        from src.providers.opus import (
            decode_framed_opus_to_pcm,
            encode_pcm_stream_to_framed_opus,
            opus_available,
        )

        if not opus_available():
            self.skipTest("libopus unavailable")

        pcm = b"\x00\x00" * 960
        inner_packets = list(
            encode_pcm_stream_to_framed_opus(
                [pcm],
                sample_rate=16000,
                channels=1,
                frame_duration_ms=60,
                bitrate=24000,
            )
        )
        outer = b"".join(_outer_frame(index, packet) for index, packet in enumerate(inner_packets))

        decoded, metrics = decode_framed_opus_to_pcm(
            [outer],
            sample_rate=16000,
            channels=1,
            frame_duration_ms=60,
        )

        self.assertEqual(len(decoded), len(pcm))
        self.assertEqual(metrics["uplink_frame_count"], len(inner_packets))
        self.assertGreater(metrics["uplink_opus_bytes"], 0)
        self.assertEqual(metrics["uplink_pcm_bytes"], len(decoded))

    def test_volcengine_asr_start_elapsed_includes_connect_time(self) -> None:
        from src.providers import realtime_asr

        class _FakeVolcengineWebSocket:
            def settimeout(self, _timeout: float) -> None:
                return None

            def send_binary(self, _payload: bytes) -> None:
                return None

        def _fake_create_connection(*_args, **_kwargs):
            time.sleep(0.03)
            return _FakeVolcengineWebSocket()

        fake_websocket_module = types.SimpleNamespace(create_connection=_fake_create_connection)

        def _fake_env_value(key: str, default: str = "") -> str:
            values = {
                "VOLCENGINE_SPEECH_APP_ID": "app-id",
                "VOLCENGINE_SPEECH_ACCESS_TOKEN": "access-token",
                "VOLCENGINE_ASR_RESOURCE_ID": "resource-id",
                "VOLCENGINE_ASR_MODEL_NAME": "bigmodel",
                "VOLCENGINE_ASR_ENDPOINT": "wss://example.invalid/asr",
                "VOLCENGINE_ASR_TIMEOUT": "1",
            }
            return values.get(key, default)

        with mock.patch.dict(sys.modules, {"websocket": fake_websocket_module}), mock.patch.object(
            realtime_asr, "_env_value", side_effect=_fake_env_value
        ):
            session = realtime_asr.VolcengineRealtimeAsrSession(sample_rate=16000)
            session.start()

        self.assertGreaterEqual(time.perf_counter() - session._started_at, 0.025)

    def test_volcengine_asr_finish_treats_server_close_after_text_as_success(self) -> None:
        from src.providers import realtime_asr

        class WebSocketConnectionClosedException(Exception):
            status_code = 1000
            reason = "normal close"

        def _server_result_frame() -> bytes:
            payload = {
                "result": {
                    "text": "请解释阿弥陀佛是什么意思？",
                    "additions": {"log_id": "volc-log-1"},
                }
            }
            encoded = realtime_asr.gzip.compress(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            frame = realtime_asr._generate_volcengine_asr_header(
                0b1001,
                realtime_asr.POS_SEQUENCE,
                realtime_asr.JSON_SERIALIZATION,
                realtime_asr.GZIP_COMPRESSION,
            )
            frame.extend((2).to_bytes(4, "big", signed=True))
            frame.extend(len(encoded).to_bytes(4, "big"))
            frame.extend(encoded)
            return bytes(frame)

        class _FakeVolcengineWebSocket:
            def __init__(self) -> None:
                self.recv_calls = 0
                self.sent_frames: list[bytes] = []
                self.closed = False

            def settimeout(self, _timeout: float) -> None:
                return None

            def send_binary(self, payload: bytes) -> None:
                self.sent_frames.append(payload)

            def recv(self) -> bytes:
                self.recv_calls += 1
                if self.recv_calls == 1:
                    return _server_result_frame()
                raise WebSocketConnectionClosedException("Connection to remote host was lost.")

            def close(self) -> None:
                self.closed = True

        fake_ws = _FakeVolcengineWebSocket()
        fake_websocket_module = types.SimpleNamespace(
            create_connection=lambda *_args, **_kwargs: fake_ws,
            WebSocketConnectionClosedException=WebSocketConnectionClosedException,
        )

        def _fake_env_value(key: str, default: str = "") -> str:
            values = {
                "VOLCENGINE_SPEECH_APP_ID": "app-id",
                "VOLCENGINE_SPEECH_ACCESS_TOKEN": "access-token",
                "VOLCENGINE_ASR_RESOURCE_ID": "resource-id",
                "VOLCENGINE_ASR_MODEL_NAME": "bigmodel",
                "VOLCENGINE_ASR_ENDPOINT": "wss://example.invalid/asr",
                "VOLCENGINE_ASR_TIMEOUT": "1",
                "VOLCENGINE_ASR_FINAL_DRAIN_TIMEOUT": "0.1",
            }
            return values.get(key, default)

        with mock.patch.dict(sys.modules, {"websocket": fake_websocket_module}), mock.patch.object(
            realtime_asr, "_env_value", side_effect=_fake_env_value
        ):
            session = realtime_asr.VolcengineRealtimeAsrSession(sample_rate=16000)
            session.start()
            session.send_pcm_chunk(b"\x00\x00" * 320)
            result = session.finish()

        self.assertIsNone(result.error_code)
        self.assertEqual(result.text, "请解释阿弥陀佛是什么意思？")
        self.assertEqual(result.request_id, "volc-log-1")
        self.assertEqual(result.close_code, 1000)
        self.assertIn("Connection to remote host was lost", result.close_reason)
        self.assertEqual(result.last_log_id, "volc-log-1")
        self.assertEqual(result.last_result_text, "请解释阿弥陀佛是什么意思？")
        self.assertEqual(result.packets_received, 1)
        self.assertTrue(fake_ws.closed)

    def test_dashscope_realtime_adapter_ignores_global_default_provider(self) -> None:
        from src.providers import realtime_asr

        class _FakeRecognitionCallback:
            pass

        class _FakeRecognition:
            def __init__(self, **_kwargs) -> None:
                return None

        fake_dashscope_audio_asr = types.SimpleNamespace(RecognitionCallback=_FakeRecognitionCallback)

        with mock.patch.dict(
            sys.modules,
            {"dashscope.audio.asr": fake_dashscope_audio_asr},
        ), mock.patch.object(
            realtime_asr.settings, "asr_provider", "volcengine"
        ), mock.patch.object(
            realtime_asr.settings, "dashscope_api_key", "dash-key"
        ), mock.patch.object(
            realtime_asr.settings, "asr_model", "paraformer-realtime-v2"
        ), mock.patch.object(
            realtime_asr.wav_asr, "_configure_dashscope_sdk"
        ), mock.patch.object(
            realtime_asr.wav_asr, "_load_recognition_class", return_value=_FakeRecognition
        ):
            session = realtime_asr.DashScopeRealtimeAsrSession(sample_rate=16000)

        self.assertIsInstance(session, realtime_asr.DashScopeRealtimeAsrSession)


class OpusUplinkEndpointTests(unittest.TestCase):
    def test_create_opus_realtime_session_decodes_and_starts_session(self) -> None:
        from src.api import realtime as realtime_api
        from src.providers.opus import encode_pcm_stream_to_framed_opus, opus_available

        if not opus_available():
            self.skipTest("libopus unavailable")

        pcm = b"\x00\x00" * 960
        inner_packets = list(
            encode_pcm_stream_to_framed_opus(
                [pcm],
                sample_rate=16000,
                channels=1,
                frame_duration_ms=60,
                bitrate=24000,
            )
        )
        body = b"".join(_outer_frame(index, packet) for index, packet in enumerate(inner_packets))

        class _Request:
            headers = {"content-type": "application/octet-stream"}

            async def body(self) -> bytes:
                return body

        with mock.patch.object(realtime_api, "start_realtime_session") as start_stub:
            accepted = asyncio.run(
                realtime_api.create_opus_realtime_session(
                    _Request(),
                    x_device_id="pc-sim",
                    x_audio_packetization="framed-v1",
                    x_audio_format="opus",
                    x_opus_sample_rate=16000,
                    x_opus_channels=1,
                    x_opus_frame_duration_ms=60,
                    x_original_pcm_bytes=len(pcm),
                )
            )

        self.assertEqual(accepted.status, "accepted")
        start_stub.assert_called_once()
        status = realtime_api.get_realtime_session(accepted.session_id)
        self.assertEqual(status.trace.uplink_frame_count, len(inner_packets))
        self.assertGreater(status.trace.uplink_opus_bytes, 0)
        self.assertEqual(status.trace.uplink_pcm_bytes, len(pcm))
        self.assertEqual(status.trace.reconstructed_audio_ms, 60)

    def test_create_opus_realtime_session_rejects_non_framed_v1(self) -> None:
        from src.api import realtime as realtime_api

        class _Request:
            headers = {"content-type": "application/octet-stream"}

            async def body(self) -> bytes:
                return b"body"

        with self.assertRaises(HTTPException) as exc:
            asyncio.run(
                realtime_api.create_opus_realtime_session(
                    _Request(),
                    x_device_id="pc-sim",
                    x_audio_packetization="legacy",
                    x_audio_format="opus",
                    x_opus_sample_rate=16000,
                    x_opus_channels=1,
                    x_opus_frame_duration_ms=60,
                    x_original_pcm_bytes=None,
                )
            )

        self.assertEqual(exc.exception.status_code, 400)
        self.assertEqual(exc.exception.detail, "invalid_packetization")

    def test_stream_opus_realtime_session_acks_frames_and_returns_done_summary(self) -> None:
        from src.api import realtime as realtime_api
        from src.providers.opus import encode_pcm_stream_to_framed_opus, opus_available

        if not opus_available():
            self.skipTest("libopus unavailable")

        pcm = b"\x00\x00" * 1920
        inner_packets = list(
            encode_pcm_stream_to_framed_opus(
                [pcm],
                sample_rate=16000,
                channels=1,
                frame_duration_ms=60,
                bitrate=24000,
            )
        )
        framed_messages = [_outer_frame(index, packet) for index, packet in enumerate(inner_packets)]
        websocket = _FakeWebSocket(
            [{"type": "websocket.receive", "bytes": message} for message in framed_messages]
            + [
                {
                    "type": "websocket.receive",
                    "text": json.dumps({"type": "end", "client_stream_duration_ms": 120}),
                }
            ]
        )

        asyncio.run(
            realtime_api.stream_opus_realtime_session(
                websocket,
                x_device_id="pc-stream",
                x_audio_packetization="framed-v1",
                x_audio_format="opus",
                x_opus_sample_rate=16000,
                x_opus_channels=1,
                x_opus_frame_duration_ms=60,
                x_original_pcm_bytes=len(pcm),
            )
        )

        self.assertTrue(websocket.accepted)
        ack_payloads = [payload for payload in websocket.sent_json if payload["type"] == "ack"]
        done_payload = websocket.sent_json[-1]
        self.assertEqual(len(ack_payloads), len(inner_packets))
        self.assertEqual(ack_payloads[-1]["frame_count"], len(inner_packets))
        self.assertEqual(done_payload["type"], "done")
        self.assertEqual(done_payload["uplink_frame_count"], len(inner_packets))
        self.assertEqual(done_payload["uplink_pcm_bytes"], len(pcm))
        self.assertEqual(done_payload["reconstructed_audio_ms"], 120)
        self.assertEqual(done_payload["client_stream_duration_ms"], 120)
        self.assertEqual(done_payload["error_code"], None)
        self.assertIsInstance(done_payload["opus_decode_ms"], int)

    def test_stream_opus_realtime_session_reports_bad_frame_error(self) -> None:
        from src.api import realtime as realtime_api

        websocket = _FakeWebSocket([{"type": "websocket.receive", "bytes": b"\x00\x00"}])

        asyncio.run(
            realtime_api.stream_opus_realtime_session(
                websocket,
                x_device_id="pc-stream",
                x_audio_packetization="framed-v1",
                x_audio_format="opus",
                x_opus_sample_rate=16000,
                x_opus_channels=1,
                x_opus_frame_duration_ms=60,
                x_original_pcm_bytes=None,
            )
        )

        self.assertTrue(websocket.accepted)
        self.assertEqual(websocket.sent_json[-1]["type"], "error")
        self.assertEqual(websocket.sent_json[-1]["error_code"], "framed_packet_truncated")
        self.assertEqual(websocket.close_code, 1003)

    def test_stream_opus_realtime_session_run_asr_sends_each_pcm_chunk_to_adapter(self) -> None:
        from src.api import realtime as realtime_api
        from src.providers.opus import encode_pcm_stream_to_framed_opus, opus_available

        if not opus_available():
            self.skipTest("libopus unavailable")

        pcm = b"\x00\x00" * 1920
        inner_packets = list(
            encode_pcm_stream_to_framed_opus(
                [pcm],
                sample_rate=16000,
                channels=1,
                frame_duration_ms=60,
                bitrate=24000,
            )
        )
        websocket = _FakeWebSocket(
            [{"type": "websocket.receive", "text": json.dumps({"type": "start", "run_asr": True})}]
            + [
                {"type": "websocket.receive", "bytes": _outer_frame(index, packet)}
                for index, packet in enumerate(inner_packets)
            ]
            + [{"type": "websocket.receive", "text": json.dumps({"type": "end"})}]
        )
        fake_asr = _FakeStreamingAsrAdapter()

        with mock.patch.object(
            realtime_api, "create_realtime_asr_session", return_value=fake_asr
        ), mock.patch.object(realtime_api, "start_realtime_session_from_question") as start_from_question, mock.patch.object(
            realtime_api, "start_realtime_session"
        ) as start_session:
            asyncio.run(
                realtime_api.stream_opus_realtime_session(
                    websocket,
                    x_device_id="pc-stream",
                    x_audio_packetization="framed-v1",
                    x_audio_format="opus",
                    x_opus_sample_rate=16000,
                    x_opus_channels=1,
                    x_opus_frame_duration_ms=60,
                    x_original_pcm_bytes=len(pcm),
                )
            )

        self.assertTrue(fake_asr.started)
        self.assertEqual(len(fake_asr.pcm_chunks), len(inner_packets))
        self.assertEqual(sum(len(chunk) for chunk in fake_asr.pcm_chunks), 3840)
        payload_types = [payload["type"] for payload in websocket.sent_json]
        self.assertIn("asr_final", payload_types)
        done_payload = websocket.sent_json[-1]
        self.assertEqual(done_payload["type"], "done")
        self.assertEqual(done_payload["question_text"], "请解释阿弥陀佛是什么意思")
        self.assertEqual(done_payload["asr_final_ms"], 123)
        self.assertEqual(done_payload["server_stream_accept_abs_ms"], 0)
        self.assertIsInstance(done_payload["first_frame_server_abs_ms"], int)
        self.assertIsInstance(done_payload["first_pcm_to_asr_abs_ms"], int)
        self.assertIsInstance(done_payload["first_asr_partial_abs_ms"], int)
        self.assertIsInstance(done_payload["asr_final_abs_ms"], int)
        self.assertIsInstance(done_payload["done_abs_ms"], int)
        self.assertLessEqual(done_payload["server_stream_accept_abs_ms"], done_payload["first_frame_server_abs_ms"])
        self.assertLessEqual(done_payload["first_frame_server_abs_ms"], done_payload["first_pcm_to_asr_abs_ms"])
        self.assertLessEqual(done_payload["first_asr_partial_abs_ms"], done_payload["asr_final_abs_ms"])
        self.assertLessEqual(done_payload["asr_final_abs_ms"], done_payload["done_abs_ms"])
        self.assertFalse(done_payload["session_started"])
        start_from_question.assert_not_called()
        start_session.assert_not_called()

    def test_stream_opus_realtime_session_provider_start_does_not_block_first_ack(self) -> None:
        from src.api import realtime as realtime_api
        from src.providers.opus import encode_pcm_stream_to_framed_opus, opus_available

        if not opus_available():
            self.skipTest("libopus unavailable")

        class _TimedWebSocket(_FakeWebSocket):
            def __init__(self, incoming: list[dict]) -> None:
                super().__init__(incoming)
                self.sent_times: list[tuple[str, float]] = []

            async def send_json(self, payload: dict) -> None:
                self.sent_times.append((str(payload.get("type")), time.perf_counter()))
                await super().send_json(payload)

        pcm = b"\x00\x00" * 1920
        inner_packets = list(
            encode_pcm_stream_to_framed_opus(
                [pcm],
                sample_rate=16000,
                channels=1,
                frame_duration_ms=60,
                bitrate=24000,
            )
        )
        websocket = _TimedWebSocket(
            [{"type": "websocket.receive", "text": json.dumps({"type": "start", "run_asr": True})}]
            + [
                {"type": "websocket.receive", "bytes": _outer_frame(index, packet)}
                for index, packet in enumerate(inner_packets)
            ]
            + [{"type": "websocket.receive", "text": json.dumps({"type": "end"})}]
        )
        fake_asr = _FakeStreamingAsrAdapter(start_delay_seconds=0.2)

        started_at = time.perf_counter()
        with mock.patch.object(realtime_api, "create_realtime_asr_session", return_value=fake_asr):
            asyncio.run(
                realtime_api.stream_opus_realtime_session(
                    websocket,
                    x_device_id="pc-stream",
                    x_audio_packetization="framed-v1",
                    x_audio_format="opus",
                    x_opus_sample_rate=16000,
                    x_opus_channels=1,
                    x_opus_frame_duration_ms=60,
                    x_original_pcm_bytes=len(pcm),
                )
            )

        first_ack_time = next(sent_at for payload_type, sent_at in websocket.sent_times if payload_type == "ack")
        self.assertLess(first_ack_time - started_at, 0.15)
        self.assertTrue(fake_asr.started)
        self.assertEqual(len(fake_asr.pcm_chunks), len(inner_packets))
        done_payload = websocket.sent_json[-1]
        self.assertEqual(done_payload["type"], "done")
        self.assertIsInstance(done_payload["provider_start_duration_ms"], int)
        self.assertIsInstance(done_payload["provider_start_abs_ms"], int)
        self.assertIsInstance(done_payload["provider_ready_abs_ms"], int)
        self.assertIsInstance(done_payload["first_pcm_decoded_abs_ms"], int)
        self.assertIsInstance(done_payload["first_pcm_sent_to_provider_abs_ms"], int)
        self.assertIsInstance(done_payload["first_provider_result_abs_ms"], int)
        self.assertLessEqual(done_payload["first_frame_server_abs_ms"], done_payload["first_pcm_decoded_abs_ms"])
        self.assertLessEqual(done_payload["provider_start_abs_ms"], done_payload["provider_ready_abs_ms"])
        self.assertLessEqual(
            done_payload["provider_ready_abs_ms"],
            done_payload["first_pcm_sent_to_provider_abs_ms"],
        )

    def test_stream_opus_realtime_session_provider_ready_timeout_reports_error(self) -> None:
        from src.api import realtime as realtime_api
        from src.providers.opus import encode_pcm_stream_to_framed_opus, opus_available

        if not opus_available():
            self.skipTest("libopus unavailable")

        pcm = b"\x00\x00" * 960
        inner_packets = list(
            encode_pcm_stream_to_framed_opus(
                [pcm],
                sample_rate=16000,
                channels=1,
                frame_duration_ms=60,
                bitrate=24000,
            )
        )
        websocket = _FakeWebSocket(
            [{"type": "websocket.receive", "text": json.dumps({"type": "start", "run_asr": True})}]
            + [{"type": "websocket.receive", "bytes": _outer_frame(0, inner_packets[0])}]
            + [{"type": "websocket.receive", "text": json.dumps({"type": "end"})}]
        )
        fake_asr = _FakeStreamingAsrAdapter(start_delay_seconds=0.05)

        with mock.patch.object(realtime_api, "ASR_PROVIDER_READY_TIMEOUT_SECONDS", 0.001), mock.patch.object(
            realtime_api, "create_realtime_asr_session", return_value=fake_asr
        ):
            asyncio.run(
                realtime_api.stream_opus_realtime_session(
                    websocket,
                    x_device_id="pc-stream",
                    x_audio_packetization="framed-v1",
                    x_audio_format="opus",
                    x_opus_sample_rate=16000,
                    x_opus_channels=1,
                    x_opus_frame_duration_ms=60,
                    x_original_pcm_bytes=len(pcm),
                )
            )

        self.assertEqual(websocket.sent_json[-1]["type"], "error")
        self.assertEqual(websocket.sent_json[-1]["error_code"], "asr_provider_ready_timeout")
        self.assertEqual(websocket.close_code, 1011)

    def test_stream_opus_realtime_session_run_full_chain_starts_session_from_asr_text(self) -> None:
        from src.api import realtime as realtime_api
        from src.providers.opus import encode_pcm_stream_to_framed_opus, opus_available

        if not opus_available():
            self.skipTest("libopus unavailable")

        pcm = b"\x00\x00" * 960
        inner_packets = list(
            encode_pcm_stream_to_framed_opus(
                [pcm],
                sample_rate=16000,
                channels=1,
                frame_duration_ms=60,
                bitrate=24000,
            )
        )
        websocket = _FakeWebSocket(
            [
                {
                    "type": "websocket.receive",
                    "text": json.dumps({"type": "start", "run_asr": True, "run_full_chain": True}),
                },
                {"type": "websocket.receive", "bytes": _outer_frame(0, inner_packets[0])},
                {"type": "websocket.receive", "text": json.dumps({"type": "end"})},
            ]
        )
        fake_asr = _FakeStreamingAsrAdapter()

        with mock.patch.object(
            realtime_api, "create_realtime_asr_session", return_value=fake_asr
        ), mock.patch.object(realtime_api, "start_realtime_session_from_question") as start_from_question:
            asyncio.run(
                realtime_api.stream_opus_realtime_session(
                    websocket,
                    x_device_id="pc-stream",
                    x_audio_packetization="framed-v1",
                    x_audio_format="opus",
                    x_opus_sample_rate=16000,
                    x_opus_channels=1,
                    x_opus_frame_duration_ms=60,
                    x_original_pcm_bytes=len(pcm),
                )
            )

        done_payload = websocket.sent_json[-1]
        self.assertEqual(done_payload["type"], "done")
        self.assertTrue(done_payload["session_started"])
        self.assertIn("session_id", done_payload)
        start_from_question.assert_called_once()
        self.assertEqual(start_from_question.call_args.args[2], "请解释阿弥陀佛是什么意思")

    def test_stream_opus_realtime_session_passes_short_answer_mode_to_session(self) -> None:
        from src.api import realtime as realtime_api
        from src.providers.opus import encode_pcm_stream_to_framed_opus, opus_available

        if not opus_available():
            self.skipTest("libopus unavailable")

        pcm = b"\x00\x00" * 960
        inner_packets = list(
            encode_pcm_stream_to_framed_opus(
                [pcm],
                sample_rate=16000,
                channels=1,
                frame_duration_ms=60,
                bitrate=24000,
            )
        )
        websocket = _FakeWebSocket(
            [
                {
                    "type": "websocket.receive",
                    "text": json.dumps(
                        {
                            "type": "start",
                            "run_asr": True,
                            "run_full_chain": True,
                            "answer_mode": "short",
                        }
                    ),
                },
                {"type": "websocket.receive", "bytes": _outer_frame(0, inner_packets[0])},
                {"type": "websocket.receive", "text": json.dumps({"type": "end"})},
            ]
        )
        fake_asr = _FakeStreamingAsrAdapter()

        with mock.patch.object(
            realtime_api, "create_realtime_asr_session", return_value=fake_asr
        ), mock.patch.object(realtime_api, "start_realtime_session_from_question") as start_from_question:
            asyncio.run(
                realtime_api.stream_opus_realtime_session(
                    websocket,
                    x_device_id="pc-stream",
                    x_audio_packetization="framed-v1",
                    x_audio_format="opus",
                    x_opus_sample_rate=16000,
                    x_opus_channels=1,
                    x_opus_frame_duration_ms=60,
                    x_original_pcm_bytes=len(pcm),
                )
            )

        done_payload = websocket.sent_json[-1]
        self.assertEqual(done_payload["type"], "done")
        self.assertEqual(done_payload["answer_mode"], "short")
        start_from_question.assert_called_once()
        self.assertEqual(start_from_question.call_args.kwargs["answer_mode"], "short")

    def test_stream_opus_realtime_session_defaults_to_dashscope_provider(self) -> None:
        from src.api import realtime as realtime_api
        from src.providers.opus import encode_pcm_stream_to_framed_opus, opus_available

        if not opus_available():
            self.skipTest("libopus unavailable")

        pcm = b"\x00\x00" * 960
        inner_packets = list(
            encode_pcm_stream_to_framed_opus(
                [pcm],
                sample_rate=16000,
                channels=1,
                frame_duration_ms=60,
                bitrate=24000,
            )
        )
        websocket = _FakeWebSocket(
            [
                {"type": "websocket.receive", "text": json.dumps({"type": "start", "run_asr": True})},
                {"type": "websocket.receive", "bytes": _outer_frame(0, inner_packets[0])},
                {"type": "websocket.receive", "text": json.dumps({"type": "end"})},
            ]
        )
        fake_asr = _FakeStreamingAsrAdapter()

        with mock.patch.object(realtime_api, "create_realtime_asr_session", return_value=fake_asr) as factory:
            asyncio.run(
                realtime_api.stream_opus_realtime_session(
                    websocket,
                    x_device_id="pc-stream",
                    x_audio_packetization="framed-v1",
                    x_audio_format="opus",
                    x_opus_sample_rate=16000,
                    x_opus_channels=1,
                    x_opus_frame_duration_ms=60,
                    x_original_pcm_bytes=len(pcm),
                )
            )

        factory.assert_called_once()
        self.assertEqual(factory.call_args.kwargs["provider"], "dashscope")
        self.assertEqual(websocket.sent_json[-1]["asr_provider"], "dashscope")

    def test_stream_opus_realtime_session_uses_env_provider_when_start_omits_provider(self) -> None:
        from src.api import realtime as realtime_api
        from src.providers.opus import encode_pcm_stream_to_framed_opus, opus_available

        if not opus_available():
            self.skipTest("libopus unavailable")

        pcm = b"\x00\x00" * 960
        inner_packets = list(
            encode_pcm_stream_to_framed_opus(
                [pcm],
                sample_rate=16000,
                channels=1,
                frame_duration_ms=60,
                bitrate=24000,
            )
        )
        websocket = _FakeWebSocket(
            [
                {"type": "websocket.receive", "text": json.dumps({"type": "start", "run_asr": True})},
                {"type": "websocket.receive", "bytes": _outer_frame(0, inner_packets[0])},
                {"type": "websocket.receive", "text": json.dumps({"type": "end"})},
            ]
        )
        fake_asr = _FakeStreamingAsrAdapter(request_id="volc-default")

        with mock.patch.object(realtime_api.settings, "asr_provider", "volcengine"), mock.patch.object(
            realtime_api, "create_realtime_asr_session", return_value=fake_asr
        ) as factory:
            asyncio.run(
                realtime_api.stream_opus_realtime_session(
                    websocket,
                    x_device_id="pc-stream",
                    x_audio_packetization="framed-v1",
                    x_audio_format="opus",
                    x_opus_sample_rate=16000,
                    x_opus_channels=1,
                    x_opus_frame_duration_ms=60,
                    x_original_pcm_bytes=len(pcm),
                )
            )

        factory.assert_called_once()
        self.assertEqual(factory.call_args.kwargs["provider"], "volcengine")
        self.assertEqual(websocket.sent_json[-1]["asr_provider"], "volcengine")
        self.assertEqual(websocket.sent_json[-1]["asr_provider_used"], "volcengine")

    def test_stream_opus_realtime_session_start_provider_overrides_env_provider(self) -> None:
        from src.api import realtime as realtime_api
        from src.providers.opus import encode_pcm_stream_to_framed_opus, opus_available

        if not opus_available():
            self.skipTest("libopus unavailable")

        pcm = b"\x00\x00" * 960
        inner_packets = list(
            encode_pcm_stream_to_framed_opus(
                [pcm],
                sample_rate=16000,
                channels=1,
                frame_duration_ms=60,
                bitrate=24000,
            )
        )
        websocket = _FakeWebSocket(
            [
                {
                    "type": "websocket.receive",
                    "text": json.dumps(
                        {"type": "start", "run_asr": True, "asr_provider": "dashscope"}
                    ),
                },
                {"type": "websocket.receive", "bytes": _outer_frame(0, inner_packets[0])},
                {"type": "websocket.receive", "text": json.dumps({"type": "end"})},
            ]
        )
        fake_asr = _FakeStreamingAsrAdapter(request_id="dash-override")

        with mock.patch.object(realtime_api.settings, "asr_provider", "volcengine"), mock.patch.object(
            realtime_api, "create_realtime_asr_session", return_value=fake_asr
        ) as factory:
            asyncio.run(
                realtime_api.stream_opus_realtime_session(
                    websocket,
                    x_device_id="pc-stream",
                    x_audio_packetization="framed-v1",
                    x_audio_format="opus",
                    x_opus_sample_rate=16000,
                    x_opus_channels=1,
                    x_opus_frame_duration_ms=60,
                    x_original_pcm_bytes=len(pcm),
                )
            )

        factory.assert_called_once()
        self.assertEqual(factory.call_args.kwargs["provider"], "dashscope")
        self.assertEqual(websocket.sent_json[-1]["asr_provider"], "dashscope")

    def test_stream_opus_realtime_session_selects_volcengine_provider(self) -> None:
        from src.api import realtime as realtime_api
        from src.providers.opus import encode_pcm_stream_to_framed_opus, opus_available

        if not opus_available():
            self.skipTest("libopus unavailable")

        pcm = b"\x00\x00" * 960
        inner_packets = list(
            encode_pcm_stream_to_framed_opus(
                [pcm],
                sample_rate=16000,
                channels=1,
                frame_duration_ms=60,
                bitrate=24000,
            )
        )
        websocket = _FakeWebSocket(
            [
                {
                    "type": "websocket.receive",
                    "text": json.dumps({"type": "start", "run_asr": True, "asr_provider": "volcengine"}),
                },
                {"type": "websocket.receive", "bytes": _outer_frame(0, inner_packets[0])},
                {"type": "websocket.receive", "text": json.dumps({"type": "end"})},
            ]
        )
        fake_asr = _FakeStreamingAsrAdapter(request_id="volc-log-id")

        with mock.patch.object(realtime_api, "create_realtime_asr_session", return_value=fake_asr) as factory:
            asyncio.run(
                realtime_api.stream_opus_realtime_session(
                    websocket,
                    x_device_id="pc-stream",
                    x_audio_packetization="framed-v1",
                    x_audio_format="opus",
                    x_opus_sample_rate=16000,
                    x_opus_channels=1,
                    x_opus_frame_duration_ms=60,
                    x_original_pcm_bytes=len(pcm),
                )
            )

        self.assertEqual(factory.call_args.kwargs["provider"], "volcengine")
        done_payload = websocket.sent_json[-1]
        self.assertEqual(done_payload["asr_provider"], "volcengine")
        self.assertEqual(done_payload["asr_log_id"], "volc-log-id")

    def test_stream_opus_realtime_session_reports_asr_failure(self) -> None:
        from src.api import realtime as realtime_api
        from src.providers.opus import encode_pcm_stream_to_framed_opus, opus_available

        if not opus_available():
            self.skipTest("libopus unavailable")

        pcm = b"\x00\x00" * 960
        inner_packets = list(
            encode_pcm_stream_to_framed_opus(
                [pcm],
                sample_rate=16000,
                channels=1,
                frame_duration_ms=60,
                bitrate=24000,
            )
        )
        websocket = _FakeWebSocket(
            [{"type": "websocket.receive", "text": json.dumps({"type": "start", "run_asr": True})}]
            + [{"type": "websocket.receive", "bytes": _outer_frame(0, inner_packets[0])}]
            + [{"type": "websocket.receive", "text": json.dumps({"type": "end"})}]
        )
        fake_asr = _FakeStreamingAsrAdapter(text=None, error_code="asr_request_failed")

        with mock.patch.object(realtime_api, "create_realtime_asr_session", return_value=fake_asr):
            asyncio.run(
                realtime_api.stream_opus_realtime_session(
                    websocket,
                    x_device_id="pc-stream",
                    x_audio_packetization="framed-v1",
                    x_audio_format="opus",
                    x_opus_sample_rate=16000,
                    x_opus_channels=1,
                    x_opus_frame_duration_ms=60,
                    x_original_pcm_bytes=len(pcm),
                )
            )

        self.assertEqual(websocket.sent_json[-1]["type"], "error")
        self.assertEqual(websocket.sent_json[-1]["error_code"], "asr_request_failed")
        self.assertEqual(websocket.close_code, 1011)

    def test_stream_opus_realtime_session_fallback_on_empty_text_continues_full_chain(self) -> None:
        from src.api import realtime as realtime_api
        from src.providers.opus import encode_pcm_stream_to_framed_opus, opus_available

        if not opus_available():
            self.skipTest("libopus unavailable")

        pcm = b"\x00\x00" * 1920
        inner_packets = list(
            encode_pcm_stream_to_framed_opus(
                [pcm],
                sample_rate=16000,
                channels=1,
                frame_duration_ms=60,
                bitrate=24000,
            )
        )
        websocket = _FakeWebSocket(
            [
                {
                    "type": "websocket.receive",
                    "text": json.dumps(
                        {
                            "type": "start",
                            "run_asr": True,
                            "run_full_chain": True,
                            "asr_provider": "volcengine",
                            "asr_fallback_provider": "dashscope",
                        }
                    ),
                }
            ]
            + [
                {"type": "websocket.receive", "bytes": _outer_frame(index, packet)}
                for index, packet in enumerate(inner_packets)
            ]
            + [{"type": "websocket.receive", "text": json.dumps({"type": "end"})}]
        )
        primary_asr = _FakeStreamingAsrAdapter(text=None, error_code="volcengine_asr_empty_text")
        fallback_asr = _FakeStreamingAsrAdapter(
            text="请解释阿弥陀佛是什么意思",
            request_id="dash-fallback",
        )

        with self.assertLogs("src.api.realtime", level="INFO") as logs:
            with mock.patch.object(
                realtime_api,
                "create_realtime_asr_session",
                side_effect=[primary_asr, fallback_asr],
            ) as factory, mock.patch.object(
                realtime_api, "start_realtime_session_from_question"
            ) as start_from_question:
                asyncio.run(
                    realtime_api.stream_opus_realtime_session(
                        websocket,
                        x_device_id="pc-stream",
                        x_audio_packetization="framed-v1",
                        x_audio_format="opus",
                        x_opus_sample_rate=16000,
                        x_opus_channels=1,
                        x_opus_frame_duration_ms=60,
                        x_original_pcm_bytes=len(pcm),
                    )
                )

        self.assertEqual(factory.call_count, 2)
        self.assertEqual(factory.call_args_list[0].kwargs["provider"], "volcengine")
        self.assertEqual(factory.call_args_list[1].kwargs["provider"], "dashscope")
        self.assertGreater(sum(len(chunk) for chunk in fallback_asr.pcm_chunks), 0)
        done_payload = websocket.sent_json[-1]
        self.assertEqual(done_payload["type"], "done")
        self.assertTrue(done_payload["session_started"])
        self.assertEqual(done_payload["asr_primary_provider"], "volcengine")
        self.assertEqual(done_payload["asr_fallback_provider"], "dashscope")
        self.assertEqual(done_payload["asr_provider_used"], "dashscope")
        self.assertTrue(done_payload["asr_fallback_used"])
        self.assertEqual(done_payload["asr_primary_error_code"], "volcengine_asr_empty_text")
        self.assertEqual(done_payload["asr_primary_provider_log_id"], "req-test")
        self.assertEqual(done_payload["fallback_reason"], "volcengine_asr_empty_text")
        self.assertIsInstance(done_payload["fallback_started_abs_ms"], int)
        self.assertIsInstance(done_payload["fallback_done_abs_ms"], int)
        self.assertEqual(done_payload["asr_log_id"], "dash-fallback")
        fallback_logs = "\n".join(logs.output)
        self.assertIn("event=v5_asr_fallback", fallback_logs)
        self.assertIn("session_id=pending", fallback_logs)
        self.assertIn("asr_primary_provider=volcengine", fallback_logs)
        self.assertIn("asr_primary_error_code=volcengine_asr_empty_text", fallback_logs)
        self.assertIn("asr_fallback_used=true", fallback_logs)
        self.assertIn("asr_provider_used=dashscope", fallback_logs)
        self.assertIn("asr_primary_provider_log_id=req-test", fallback_logs)
        self.assertIn("provider_log_id=dash-fallback", fallback_logs)
        start_from_question.assert_called_once()
        self.assertEqual(start_from_question.call_args.args[2], "请解释阿弥陀佛是什么意思")

    def test_stream_opus_realtime_session_reports_all_providers_failed_after_fallback(self) -> None:
        from src.api import realtime as realtime_api
        from src.providers.opus import encode_pcm_stream_to_framed_opus, opus_available

        if not opus_available():
            self.skipTest("libopus unavailable")

        pcm = b"\x00\x00" * 1920
        inner_packets = list(
            encode_pcm_stream_to_framed_opus(
                [pcm],
                sample_rate=16000,
                channels=1,
                frame_duration_ms=60,
                bitrate=24000,
            )
        )
        websocket = _FakeWebSocket(
            [
                {
                    "type": "websocket.receive",
                    "text": json.dumps(
                        {
                            "type": "start",
                            "run_asr": True,
                            "run_full_chain": True,
                            "asr_provider": "volcengine",
                            "asr_fallback_provider": "dashscope",
                        }
                    ),
                }
            ]
            + [
                {"type": "websocket.receive", "bytes": _outer_frame(index, packet)}
                for index, packet in enumerate(inner_packets)
            ]
            + [{"type": "websocket.receive", "text": json.dumps({"type": "end"})}]
        )
        primary_asr = _FakeStreamingAsrAdapter(text=None, error_code="volcengine_asr_empty_text")
        fallback_asr = _FakeStreamingAsrAdapter(text=None, error_code="asr_empty_text")

        with mock.patch.object(
            realtime_api,
            "create_realtime_asr_session",
            side_effect=[primary_asr, fallback_asr],
        ), mock.patch.object(realtime_api, "start_realtime_session_from_question") as start_from_question:
            asyncio.run(
                realtime_api.stream_opus_realtime_session(
                    websocket,
                    x_device_id="pc-stream",
                    x_audio_packetization="framed-v1",
                    x_audio_format="opus",
                    x_opus_sample_rate=16000,
                    x_opus_channels=1,
                    x_opus_frame_duration_ms=60,
                    x_original_pcm_bytes=len(pcm),
                )
            )

        self.assertEqual(websocket.sent_json[-1]["type"], "error")
        self.assertEqual(websocket.sent_json[-1]["error_code"], "asr_all_providers_failed")
        self.assertEqual(websocket.sent_json[-1]["asr_primary_error_code"], "volcengine_asr_empty_text")
        self.assertEqual(websocket.sent_json[-1]["provider_error_code"], "asr_empty_text")
        self.assertTrue(websocket.sent_json[-1]["asr_fallback_used"])
        self.assertEqual(websocket.close_code, 1011)
        start_from_question.assert_not_called()


class OpusUplinkSmokeScriptTests(unittest.TestCase):
    def test_load_wav_pcm_request_requires_16k_16bit_mono(self) -> None:
        module = _load_opus_uplink_script()
        wav_path = _write_test_wav(b"\x00\x00" * 160, channels=2)
        try:
            with self.assertRaisesRegex(ValueError, "expected 16kHz 16-bit mono WAV"):
                module.load_wav_pcm(wav_path)
        finally:
            Path(wav_path).unlink(missing_ok=True)

    def test_build_opus_uplink_request_uses_v5_headers_and_framed_body(self) -> None:
        module = _load_opus_uplink_script()
        from src.providers.opus import opus_available

        if not opus_available():
            self.skipTest("libopus unavailable")

        wav_path = _write_test_wav(b"\x00\x00" * 960)
        try:
            body, headers, metrics = module.build_opus_uplink_request(wav_path)
        finally:
            Path(wav_path).unlink(missing_ok=True)

        self.assertEqual(headers["content-type"], "application/octet-stream")
        self.assertEqual(headers["x-audio-packetization"], "framed-v1")
        self.assertEqual(headers["x-audio-format"], "opus")
        self.assertEqual(headers["x-opus-sample-rate"], "16000")
        self.assertEqual(headers["x-original-pcm-bytes"], "1920")
        self.assertGreater(len(body), 8)
        self.assertEqual(metrics["uplink_frame_count"], 1)
        self.assertGreater(metrics["uplink_opus_bytes"], 0)

    def test_build_stream_uplink_messages_uses_one_framed_message_per_opus_packet(self) -> None:
        module = _load_opus_uplink_stream_script()
        from src.providers.opus import opus_available

        if not opus_available():
            self.skipTest("libopus unavailable")

        wav_path = _write_test_wav(b"\x00\x00" * 1920)
        try:
            messages, metrics = module.build_stream_uplink_messages(wav_path, frame_ms=60)
        finally:
            Path(wav_path).unlink(missing_ok=True)

        self.assertEqual(metrics["uplink_frame_count"], len(messages))
        self.assertEqual(metrics["uplink_pcm_bytes"], 3840)
        self.assertEqual(metrics["reconstructed_audio_ms"], 120)
        self.assertGreater(metrics["uplink_opus_bytes"], 0)
        self.assertGreater(len(messages[0]), 8)

    def test_build_start_control_enables_asr_and_full_chain(self) -> None:
        module = _load_opus_uplink_stream_script()

        payload = module.build_start_control(run_asr=True, run_full_chain=True, asr_provider="volcengine")

        self.assertEqual(
            json.loads(payload),
            {"type": "start", "run_asr": True, "run_full_chain": True, "asr_provider": "volcengine"},
        )

    def test_build_start_control_includes_short_answer_mode_when_requested(self) -> None:
        module = _load_opus_uplink_stream_script()

        payload = module.build_start_control(
            run_asr=True,
            run_full_chain=True,
            asr_provider="volcengine",
            answer_mode="short",
        )

        self.assertEqual(json.loads(payload)["answer_mode"], "short")

    def test_build_start_control_omits_provider_for_server_env_default(self) -> None:
        module = _load_opus_uplink_stream_script()

        payload = module.build_start_control(run_asr=True, run_full_chain=True, asr_provider=None)

        self.assertNotIn("asr_provider", json.loads(payload))

    def test_build_start_control_includes_fallback_provider_when_requested(self) -> None:
        module = _load_opus_uplink_stream_script()

        payload = module.build_start_control(
            run_asr=True,
            run_full_chain=True,
            asr_provider="volcengine",
            asr_fallback_provider="dashscope",
        )

        self.assertEqual(json.loads(payload)["asr_fallback_provider"], "dashscope")


class V5StreamingLatencyEvalScriptTests(unittest.TestCase):
    def test_build_streaming_latency_record_normalizes_to_first_frame(self) -> None:
        module = _load_v5_streaming_latency_eval_script()

        done_payload = {
            "type": "done",
            "provider_start_abs_ms": 1,
            "provider_ready_abs_ms": 3,
            "provider_start_duration_ms": 2,
            "first_frame_server_abs_ms": 4,
            "first_pcm_decoded_abs_ms": 5,
            "first_pcm_sent_to_provider_abs_ms": 6,
            "first_provider_result_abs_ms": 2823,
            "first_pcm_to_asr_abs_ms": 4,
            "first_asr_partial_abs_ms": 2823,
            "asr_final_abs_ms": 5675,
            "done_abs_ms": 5923,
            "question_text": "情解释阿弥陀佛是什么意思？",
            "error_code": None,
            "session_id": "session-1",
            "realtime_asr_request_id": "request-1",
        }
        status_payload = {
            "session_id": "session-1",
            "status": "done",
            "answer_text": "阿弥陀佛是西方极乐世界教主。",
            "trace": {
                "retrieval_done_abs_ms": 6342,
                "first_llm_chunk_abs_ms": 8588,
                "first_tts_chunk_abs_ms": 10180,
                "first_audio_byte_abs_ms": 10180,
                "done_abs_ms": 13914,
                "audio_duration_ms": 14160,
            },
        }

        record = module.build_streaming_latency_record(
            term="阿弥陀佛",
            audio_path="/tmp/volc_asr_eval/amitabha.wav",
            done_payload=done_payload,
            status_payload=status_payload,
        )

        self.assertEqual(record["path_type"], "streaming")
        self.assertEqual(record["provider_start_abs_ms"], 0)
        self.assertEqual(record["provider_ready_abs_ms"], 0)
        self.assertEqual(record["provider_start_duration_ms"], 2)
        self.assertEqual(record["first_frame_server_abs_ms"], 0)
        self.assertEqual(record["first_pcm_decoded_abs_ms"], 1)
        self.assertEqual(record["first_pcm_sent_to_provider_abs_ms"], 2)
        self.assertEqual(record["first_provider_result_abs_ms"], 2819)
        self.assertEqual(record["first_pcm_to_asr_abs_ms"], 0)
        self.assertEqual(record["first_asr_partial_abs_ms"], 2819)
        self.assertEqual(record["asr_final_abs_ms"], 5671)
        self.assertEqual(record["retrieval_done_abs_ms"], 6338)
        self.assertEqual(record["first_audio_byte_abs_ms"], 10176)
        self.assertEqual(record["done_abs_ms"], 13910)
        self.assertTrue(record["term_hit"])
        self.assertEqual(record["answer_chars"], 14)
        self.assertEqual(record["session_id"], "session-1")
        self.assertEqual(record["log_id"], "request-1")

    def test_eval_parser_accepts_asr_provider(self) -> None:
        module = _load_v5_streaming_latency_eval_script()

        args = module.build_parser().parse_args(["--asr-provider", "volcengine"])

        self.assertEqual(args.asr_provider, "volcengine")

    def test_build_error_record_preserves_case_and_error(self) -> None:
        module = _load_v5_streaming_latency_eval_script()

        record = module.build_error_record(
            term="金刚经",
            audio_path="/tmp/volc_asr_eval/diamond_sutra.wav",
            path_type="streaming",
            error_code="smoke_failed",
            error_message="connection refused",
        )

        self.assertEqual(record["term"], "金刚经")
        self.assertEqual(record["path_type"], "streaming")
        self.assertEqual(record["error_code"], "smoke_failed")
        self.assertEqual(record["error_message"], "connection refused")


class V5AsrOnlyRepeatEvalScriptTests(unittest.TestCase):
    def test_parser_accepts_repeat_provider_and_realtime_options(self) -> None:
        module = _load_v5_asr_only_repeat_eval_script()

        args = module.build_parser().parse_args(
            [
                "--providers",
                "dashscope,volcengine",
                "--repeats",
                "5",
                "--frame-ms",
                "60",
                "--no-realtime",
            ]
        )

        self.assertEqual(module.providers_from_args(args), ["dashscope", "volcengine"])
        self.assertEqual(args.repeats, 5)
        self.assertEqual(args.frame_ms, 60)
        self.assertFalse(args.realtime)

    def test_parser_accepts_fallback_provider(self) -> None:
        module = _load_v5_asr_only_repeat_eval_script()

        args = module.build_parser().parse_args(["--asr-fallback-provider", "dashscope"])

        self.assertEqual(args.asr_fallback_provider, "dashscope")

    def test_run_asr_only_case_does_not_enable_full_chain(self) -> None:
        module = _load_v5_asr_only_repeat_eval_script()
        calls: list[dict] = []

        def _fake_run_stream_smoke(*_args, **kwargs):
            calls.append(kwargs)
            return {
                "type": "done",
                "asr_provider": "dashscope",
                "question_text": "请解释阿弥陀佛是什么意思？",
                "first_frame_server_abs_ms": 4,
                "provider_start_duration_ms": 70,
                "first_pcm_sent_to_provider_abs_ms": 72,
                "first_provider_result_abs_ms": 2800,
                "first_asr_partial_abs_ms": 2800,
                "asr_final_abs_ms": 5200,
                "provider_log_id": "req-1",
                "error_code": None,
            }

        with mock.patch.object(module, "run_stream_smoke", side_effect=_fake_run_stream_smoke):
            record = module.run_asr_only_case(
                term="阿弥陀佛",
                audio_path=Path("/tmp/volc_asr_eval/amitabha.wav"),
                repeat_index=2,
                provider="dashscope",
                base_url="http://127.0.0.1:8010",
                frame_ms=60,
                realtime=True,
                timeout=30.0,
            )

        self.assertEqual(calls[0]["run_asr"], True)
        self.assertEqual(calls[0]["run_full_chain"], False)
        self.assertEqual(calls[0]["asr_provider"], "dashscope")
        self.assertEqual(calls[0]["asr_fallback_provider"], None)
        self.assertEqual(record["repeat_index"], 2)
        self.assertTrue(record["term_hit"])
        self.assertEqual(record["question_text"], "请解释阿弥陀佛是什么意思？")
        self.assertEqual(record["asr_final_abs_ms"], 5200)
        self.assertEqual(record["provider_log_id"], "req-1")

    def test_run_asr_only_case_records_error_and_continues_shape(self) -> None:
        module = _load_v5_asr_only_repeat_eval_script()

        with mock.patch.object(module, "run_stream_smoke", side_effect=RuntimeError("connection refused")):
            record = module.run_asr_only_case(
                term="金刚经",
                audio_path=Path("/tmp/volc_asr_eval/diamond_sutra.wav"),
                repeat_index=1,
                provider="volcengine",
                base_url="http://127.0.0.1:8010",
                frame_ms=60,
                realtime=True,
                timeout=30.0,
            )

        self.assertEqual(record["provider"], "volcengine")
        self.assertEqual(record["term"], "金刚经")
        self.assertFalse(record["term_hit"])
        self.assertEqual(record["error_code"], "smoke_failed")
        self.assertIn("connection refused", record["error_message"])

    def test_write_markdown_includes_mean_median_and_p95_summary(self) -> None:
        module = _load_v5_asr_only_repeat_eval_script()
        records = [
            {
                "provider": "dashscope",
                "term": "阿弥陀佛",
                "repeat_index": 1,
                "question_text": "请解释阿弥陀佛是什么意思？",
                "recognized_text": "请解释阿弥陀佛是什么意思？",
                "term_hit": True,
                "asr_final_abs_ms": 5000,
                "provider_start_duration_ms": 70,
                "first_provider_result_abs_ms": 2800,
                "error_code": None,
            },
            {
                "provider": "dashscope",
                "term": "阿弥陀佛",
                "repeat_index": 2,
                "question_text": "情解释阿弥陀佛是什么意思？",
                "recognized_text": "情解释阿弥陀佛是什么意思？",
                "term_hit": True,
                "asr_final_abs_ms": 6000,
                "provider_start_duration_ms": 80,
                "first_provider_result_abs_ms": 2900,
                "error_code": None,
            },
            {
                "provider": "volcengine",
                "term": "阿弥陀佛",
                "repeat_index": 1,
                "question_text": "请解释阿弥陀佛是什么意思？",
                "recognized_text": "请解释阿弥陀佛是什么意思？",
                "term_hit": True,
                "asr_final_abs_ms": 4300,
                "provider_start_duration_ms": 1800,
                "first_provider_result_abs_ms": 3900,
                "error_code": None,
            },
        ]
        output_path = Path(tempfile.mkstemp(suffix=".md")[1])
        try:
            module.write_markdown(records, output_path)
            content = output_path.read_text(encoding="utf-8")
        finally:
            output_path.unlink(missing_ok=True)

        self.assertIn("mean_asr_final_abs_ms", content)
        self.assertIn("median_asr_final_abs_ms", content)
        self.assertIn("p95_asr_final_abs_ms", content)
        self.assertIn("hit_count / repeats", content)
        self.assertIn("unique recognized_texts", content)


class V5FullChainRepeatEvalScriptTests(unittest.TestCase):
    def test_parser_accepts_answer_mode_and_repeat_options(self) -> None:
        module = _load_v5_full_chain_repeat_eval_script()

        args = module.build_parser().parse_args(
            [
                "--providers",
                "dashscope,volcengine",
                "--repeats",
                "3",
                "--answer-mode",
                "short",
                "--no-realtime",
            ]
        )

        self.assertEqual(module.providers_from_args(args), ["dashscope", "volcengine"])
        self.assertEqual(args.repeats, 3)
        self.assertEqual(args.answer_mode, "short")
        self.assertFalse(args.realtime)

    def test_parser_accepts_fallback_provider(self) -> None:
        module = _load_v5_full_chain_repeat_eval_script()

        args = module.build_parser().parse_args(["--asr-fallback-provider", "dashscope"])

        self.assertEqual(args.asr_fallback_provider, "dashscope")

    def test_run_full_chain_case_enables_full_chain_and_short_mode(self) -> None:
        module = _load_v5_full_chain_repeat_eval_script()
        calls: list[dict] = []

        def _fake_run_stream_smoke(*_args, **kwargs):
            calls.append(kwargs)
            return {
                "type": "done",
                "asr_provider": "volcengine",
                "question_text": "请解释阿弥陀佛是什么意思？",
                "asr_final_abs_ms": 4300,
                "first_provider_result_abs_ms": 3900,
                "provider_start_duration_ms": 1500,
                "provider_log_id": "volc-log",
                "session_id": "session-1",
                "done_abs_ms": 5000,
                "error_code": None,
                "session_status": {
                    "session_id": "session-1",
                    "question_text": "请解释阿弥陀佛是什么意思？",
                    "answer_text": "阿弥陀佛是无量光寿。念佛是归向净土的核心方便。",
                    "error_code": None,
                    "trace": {
                        "retrieval_done_abs_ms": 5200,
                        "first_llm_chunk_abs_ms": 6500,
                        "first_tts_chunk_abs_ms": 7600,
                        "first_audio_byte_abs_ms": 7600,
                        "done_abs_ms": 10800,
                        "audio_duration_ms": 5200,
                    },
                },
            }

        with mock.patch.object(module, "run_stream_smoke", side_effect=_fake_run_stream_smoke):
            record = module.run_full_chain_case(
                term="阿弥陀佛",
                audio_path=Path("/tmp/volc_asr_eval/amitabha.wav"),
                repeat_index=1,
                provider="volcengine",
                base_url="http://127.0.0.1:8010",
                frame_ms=60,
                realtime=True,
                timeout=30.0,
                status_timeout=20.0,
                poll_interval=0.3,
                max_polls=120,
                answer_mode="short",
            )

        self.assertEqual(calls[0]["run_asr"], True)
        self.assertEqual(calls[0]["run_full_chain"], True)
        self.assertEqual(calls[0]["asr_provider"], "volcengine")
        self.assertEqual(calls[0]["asr_fallback_provider"], None)
        self.assertEqual(calls[0]["answer_mode"], "short")
        self.assertTrue(record["term_hit"])
        self.assertEqual(record["answer_mode"], "short")
        self.assertEqual(record["first_audio_byte_abs_ms"], 7600)
        self.assertEqual(record["done_abs_ms"], 10800)
        self.assertGreater(record["answer_chars"], 0)

    def test_run_full_chain_case_records_error_and_continues_shape(self) -> None:
        module = _load_v5_full_chain_repeat_eval_script()

        with mock.patch.object(module, "run_stream_smoke", side_effect=RuntimeError("connection refused")):
            record = module.run_full_chain_case(
                term="慧远",
                audio_path=Path("/tmp/volc_asr_eval/huiyuan.wav"),
                repeat_index=2,
                provider="dashscope",
                base_url="http://127.0.0.1:8010",
                frame_ms=60,
                realtime=True,
                timeout=30.0,
                status_timeout=20.0,
                poll_interval=0.3,
                max_polls=120,
                answer_mode="short",
            )

        self.assertEqual(record["provider"], "dashscope")
        self.assertEqual(record["term"], "慧远")
        self.assertEqual(record["repeat_index"], 2)
        self.assertEqual(record["error_code"], "smoke_failed")
        self.assertIn("connection refused", record["error_message"])

    def test_write_markdown_includes_first_audio_done_and_output_length_summary(self) -> None:
        module = _load_v5_full_chain_repeat_eval_script()
        records = [
            {
                "provider": "dashscope",
                "term": "阿弥陀佛",
                "repeat_index": 1,
                "question_text": "情解释阿弥陀佛是什么意思？",
                "recognized_text": "情解释阿弥陀佛是什么意思？",
                "term_hit": True,
                "asr_final_abs_ms": 5000,
                "first_audio_byte_abs_ms": 9000,
                "done_abs_ms": 13000,
                "answer_chars": 31,
                "audio_duration_ms": 5200,
                "error_code": None,
            },
            {
                "provider": "volcengine",
                "term": "阿弥陀佛",
                "repeat_index": 1,
                "question_text": "请解释阿弥陀佛是什么意思？",
                "recognized_text": "请解释阿弥陀佛是什么意思？",
                "term_hit": True,
                "asr_final_abs_ms": 4300,
                "first_audio_byte_abs_ms": 8200,
                "done_abs_ms": 12100,
                "answer_chars": 30,
                "audio_duration_ms": 5100,
                "error_code": None,
            },
        ]
        output_path = Path(tempfile.mkstemp(suffix=".md")[1])
        try:
            module.write_markdown(records, output_path)
            content = output_path.read_text(encoding="utf-8")
        finally:
            output_path.unlink(missing_ok=True)

        self.assertIn("mean_first_audio_byte_abs_ms", content)
        self.assertIn("median_first_audio_byte_abs_ms", content)
        self.assertIn("p95_done_abs_ms", content)
        self.assertIn("mean_answer_chars", content)
        self.assertIn("mean_audio_duration_ms", content)


class V5RealVoiceEvalScriptTests(unittest.TestCase):
    def test_parser_defaults_to_real_voice_tmp_dir_and_short_mode(self) -> None:
        module = _load_v5_real_voice_eval_script()

        args = module.build_parser().parse_args([])

        self.assertEqual(args.audio_dir, "/tmp/v5_real_voice_eval")
        self.assertEqual(args.answer_mode, "short")
        self.assertEqual(args.providers, "dashscope,volcengine")

    def test_discover_cases_accepts_numbered_real_voice_files(self) -> None:
        module = _load_v5_real_voice_eval_script()
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            (tmp_dir / "amitabha_01.wav").write_bytes(b"wav")
            (tmp_dir / "amitabha_02.wav").write_bytes(b"wav")
            (tmp_dir / "huiyuan_01.wav").write_bytes(b"wav")

            cases = module.discover_real_voice_cases(tmp_dir)
        finally:
            for path in tmp_dir.glob("*"):
                path.unlink(missing_ok=True)
            tmp_dir.rmdir()

        self.assertEqual(
            [(case["term"], case["speaker_index"], case["audio_path"].name) for case in cases],
            [
                ("阿弥陀佛", 1, "amitabha_01.wav"),
                ("阿弥陀佛", 2, "amitabha_02.wav"),
                ("慧远", 1, "huiyuan_01.wav"),
            ],
        )
