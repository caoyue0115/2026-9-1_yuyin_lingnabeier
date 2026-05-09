from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import tempfile
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
    def __init__(self, *, text: str | None = "请解释阿弥陀佛是什么意思", error_code: str | None = None) -> None:
        self.text = text
        self.error_code = error_code
        self.started = False
        self.pcm_chunks: list[bytes] = []

    def start(self) -> None:
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
            request_id="req-test",
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

        self.assertTrue(fake_asr.started)
        self.assertEqual(len(fake_asr.pcm_chunks), len(inner_packets))
        self.assertEqual(sum(len(chunk) for chunk in fake_asr.pcm_chunks), 3840)
        payload_types = [payload["type"] for payload in websocket.sent_json]
        self.assertIn("asr_final", payload_types)
        done_payload = websocket.sent_json[-1]
        self.assertEqual(done_payload["type"], "done")
        self.assertEqual(done_payload["question_text"], "请解释阿弥陀佛是什么意思")
        self.assertEqual(done_payload["asr_final_ms"], 123)
        self.assertFalse(done_payload["session_started"])

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

        payload = module.build_start_control(run_asr=True, run_full_chain=True)

        self.assertEqual(
            json.loads(payload),
            {"type": "start", "run_asr": True, "run_full_chain": True},
        )
