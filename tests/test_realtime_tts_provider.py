from __future__ import annotations

import base64
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

from tests._stubs import install_dependency_stubs

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

install_dependency_stubs()


class RealtimeTtsProviderTests(unittest.TestCase):
    def test_warmup_realtime_tts_session_connects_before_streaming(self) -> None:
        from src.providers import realtime_tts

        class _FakeClient:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def connect(self) -> None:
                self.calls.append("connect")

            def update_session(self, **kwargs) -> None:
                self.calls.append("update_session")

            def close(self) -> None:
                self.calls.append("close")

        client = _FakeClient()

        with mock.patch.object(realtime_tts, "realtime_tts_health", return_value=True), mock.patch.object(
            realtime_tts.settings, "realtime_tts_voice", "voice-1"
        ), mock.patch.object(
            realtime_tts.settings, "realtime_tts_model", "model-1"
        ), mock.patch.object(
            realtime_tts,
            "AudioFormat",
            mock.Mock(PCM_24000HZ_MONO_16BIT="pcm24k"),
        ), mock.patch.object(
            realtime_tts, "_build_client", return_value=client
        ):
            session = realtime_tts.warmup_realtime_tts_session()
            session.close()

        self.assertEqual(client.calls, ["connect", "update_session", "close"])

    def test_realtime_tts_health_requires_dedicated_model_and_voice(self) -> None:
        from src.providers import realtime_tts

        with mock.patch.object(realtime_tts.settings, "dashscope_api_key", "key"), mock.patch.object(
            realtime_tts.settings, "realtime_tts_model", "qwen3-tts-vc-realtime-2026-01-15"
        ), mock.patch.object(realtime_tts.settings, "realtime_tts_voice", ""):
            self.assertFalse(realtime_tts.realtime_tts_health())

        with mock.patch.object(realtime_tts.settings, "dashscope_api_key", "key"), mock.patch.object(
            realtime_tts.settings, "realtime_tts_model", "qwen3-tts-vc-realtime-2026-01-15"
        ), mock.patch.object(
            realtime_tts.settings, "realtime_tts_voice", "voice-1"
        ):
            self.assertTrue(realtime_tts.realtime_tts_health())

    def test_decode_realtime_audio_delta_returns_pcm_bytes(self) -> None:
        from src.providers.realtime_tts import decode_realtime_audio_delta

        chunk = decode_realtime_audio_delta(
            {
                "type": "response.audio.delta",
                "delta": base64.b64encode(b"\x01\x00\x02\x00").decode("ascii"),
            }
        )

        self.assertEqual(chunk, b"\x01\x00\x02\x00")

    def test_normalize_realtime_pcm_chunk_downsamples_24k_to_16k(self) -> None:
        from src.providers.realtime_tts import normalize_realtime_pcm_chunk

        pcm_24k = b"\x00\x00\x10\x00\x20\x00\x30\x00\x40\x00\x50\x00"

        normalized = normalize_realtime_pcm_chunk(
            pcm_24k,
            input_sample_rate=24000,
            input_sample_width_bits=16,
            input_channels=1,
            output_sample_rate=16000,
            output_sample_width_bits=16,
            output_channels=1,
        )

        self.assertTrue(normalized)
        self.assertLess(len(normalized), len(pcm_24k))
        self.assertEqual(len(normalized) % 2, 0)

    def test_realtime_tail_silence_uses_output_pcm_format(self) -> None:
        from src.providers import realtime_tts

        with mock.patch.object(realtime_tts.settings, "realtime_tts_tail_silence_ms", 500), mock.patch.object(
            realtime_tts.settings, "realtime_audio_sample_rate", 16000
        ), mock.patch.object(
            realtime_tts.settings, "realtime_audio_sample_width_bits", 16
        ), mock.patch.object(
            realtime_tts.settings, "realtime_audio_channels", 1
        ):
            silence = realtime_tts.build_realtime_tail_silence()

        self.assertEqual(len(silence), 16_000)
        self.assertEqual(silence, bytes(16_000))

    def test_stream_realtime_tts_chunks_yields_audio_before_text_iterable_finishes(self) -> None:
        from src.providers import realtime_tts

        audio_seen = threading.Event()

        def _text_chunks():
            yield "第一段"
            self.assertTrue(audio_seen.wait(timeout=0.2))
            yield "第二段"

        class _FakeClient:
            def __init__(self, callback) -> None:
                self.callback = callback
                self.calls: list[str] = []

            def connect(self) -> None:
                self.calls.append("connect")

            def update_session(self, **kwargs) -> None:
                self.calls.append("update_session")

            def append_text(self, text: str) -> None:
                self.calls.append(f"append:{text}")
                if text == "第一段":
                    self.callback.events.put(
                        {
                            "type": "response.audio.delta",
                            "delta": base64.b64encode(b"\x01\x00\x02\x00").decode("ascii"),
                        }
                    )

            def finish(self) -> None:
                self.calls.append("finish")
                self.callback.events.put({"type": "response.done"})

            def close(self) -> None:
                self.calls.append("close")

        clients: list[_FakeClient] = []

        def _build_client(callback):
            client = _FakeClient(callback)
            clients.append(client)
            return client

        with mock.patch.object(realtime_tts, "realtime_tts_health", return_value=True), mock.patch.object(
            realtime_tts.settings, "realtime_tts_voice", "voice-1"
        ), mock.patch.object(
            realtime_tts.settings, "realtime_tts_model", "model-1"
        ), mock.patch.object(
            realtime_tts,
            "AudioFormat",
            mock.Mock(PCM_24000HZ_MONO_16BIT="pcm24k"),
        ), mock.patch.object(
            realtime_tts, "_build_client", side_effect=_build_client
        ), mock.patch.object(
            realtime_tts,
            "normalize_realtime_pcm_chunk",
            side_effect=lambda chunk, **_: chunk,
        ):
            stream = realtime_tts.stream_realtime_tts_chunks(_text_chunks())
            first_chunk = next(stream)
            audio_seen.set()
            remaining = list(stream)

        self.assertEqual(first_chunk, b"\x01\x00\x02\x00")
        self.assertEqual(remaining, [bytes(16_000)])
        self.assertEqual(
            clients[0].calls,
            ["connect", "update_session", "append:第一段", "append:第二段", "finish", "close"],
        )


if __name__ == "__main__":
    unittest.main()
