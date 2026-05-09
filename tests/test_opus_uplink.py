from __future__ import annotations

import asyncio
import importlib.util
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


class OpusUplinkProviderTests(unittest.TestCase):
    def test_parse_framed_v1_packets_rejects_truncated_packet(self) -> None:
        from src.providers.opus import OpusError, parse_framed_v1_packets

        with self.assertRaisesRegex(OpusError, "framed_packet_truncated"):
            parse_framed_v1_packets(b"\x00\x00\x00\x00\x00\x00\x00\x04ab")

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
