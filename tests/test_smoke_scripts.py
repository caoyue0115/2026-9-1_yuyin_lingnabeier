from __future__ import annotations

import importlib.util
import sys
import unittest
import wave
from pathlib import Path

from tests._stubs import install_dependency_stubs

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

install_dependency_stubs()


def _load_script(name: str):
    script_path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"tests.{name}", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


smoke_submit = _load_script("smoke_submit")
smoke_poll = _load_script("smoke_poll")
esp_simulator = _load_script("esp_simulator")
create_asr_vocabulary = _load_script("create_asr_vocabulary")
create_realtime_tts_voice = _load_script("create_realtime_tts_voice")


class SmokeScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.audio_path = ROOT / "data" / "incoming" / "smoke-test.wav"
        self.audio_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(self.audio_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16000)
            wav_file.writeframes(b"\x00\x00" * 16)

    def tearDown(self) -> None:
        self.audio_path.unlink(missing_ok=True)

    def test_smoke_submit_uses_real_wav_when_path_provided(self) -> None:
        body, headers = smoke_submit.load_audio_request(str(self.audio_path))

        self.assertEqual(body, b"\x00\x00" * 16)
        self.assertEqual(headers["x-sample-rate"], "16000")
        self.assertEqual(headers["x-sample-width"], "16")
        self.assertEqual(headers["x-channels"], "1")

    def test_smoke_poll_expects_success_when_audio_path_is_present(self) -> None:
        self.assertTrue(smoke_poll.should_expect_success(str(self.audio_path), None))
        self.assertFalse(smoke_poll.should_expect_success(None, None))

    def test_esp_simulator_loads_pcm_request_from_wav(self) -> None:
        body, headers = esp_simulator.load_pcm_request(str(self.audio_path))

        self.assertEqual(body, b"\x00\x00" * 16)
        self.assertEqual(headers["content-type"], "application/octet-stream")
        self.assertEqual(headers["x-sample-rate"], "16000")
        self.assertEqual(headers["x-sample-width"], "16")
        self.assertEqual(headers["x-channels"], "1")

    def test_esp_simulator_downloads_audio_to_requested_directory(self) -> None:
        class _Response:
            content = b"RIFF"

            def raise_for_status(self) -> None:
                return None

        output_dir = ROOT / "data" / "output" / "sim-downloads"
        output_dir.mkdir(parents=True, exist_ok=True)
        target_path = output_dir / "reply.wav"
        target_path.unlink(missing_ok=True)

        original_get = esp_simulator.httpx.get
        esp_simulator.httpx.get = lambda *args, **kwargs: _Response()
        try:
            saved = esp_simulator.download_audio(
                "http://127.0.0.1/api/v2/audio/reply.wav",
                output_dir=str(output_dir),
            )
        finally:
            esp_simulator.httpx.get = original_get

        self.assertEqual(saved, target_path.resolve())
        self.assertEqual(saved.read_bytes(), b"RIFF")
        target_path.unlink(missing_ok=True)
        output_dir.rmdir()

    def test_create_asr_vocabulary_loads_hotwords_json(self) -> None:
        hotwords = create_asr_vocabulary.load_hotwords(
            str(ROOT / "config" / "asr_hotwords.buddhism.json")
        )

        self.assertGreaterEqual(len(hotwords), 5)
        self.assertEqual(hotwords[0]["lang"], "zh")
        self.assertIn("weight", hotwords[0])

    def test_create_asr_vocabulary_builds_prefix_summary(self) -> None:
        summary = create_asr_vocabulary.build_summary(
            vocabulary_id="vocab-buddha-001",
            target_model="paraformer-realtime-v2",
            hotwords=[{"text": "无相", "weight": 4, "lang": "zh"}],
        )

        self.assertEqual(summary["vocabulary_id"], "vocab-buddha-001")
        self.assertEqual(summary["target_model"], "paraformer-realtime-v2")
        self.assertEqual(summary["count"], 1)
        self.assertEqual(summary["sample_terms"], ["无相"])

    def test_create_realtime_tts_voice_encodes_local_wav_as_data_uri(self) -> None:
        data_uri = create_realtime_tts_voice.encode_audio_data_uri(str(self.audio_path))

        self.assertTrue(data_uri.startswith("data:audio/x-wav;base64,"))

    def test_create_realtime_tts_voice_builds_summary_from_sample(self) -> None:
        summary = create_realtime_tts_voice.build_summary(
            voice_id="voice-123",
            target_model="qwen3-tts-vc-realtime-2026-01-15",
            sample_path=str(self.audio_path),
            prefix="rulaivcrt",
        )

        self.assertEqual(summary["voice_id"], "voice-123")
        self.assertEqual(summary["target_model"], "qwen3-tts-vc-realtime-2026-01-15")
        self.assertEqual(summary["prefix"], "rulaivcrt")
        self.assertEqual(summary["audio_info"]["sample_rate"], 16000)
        self.assertEqual(summary["audio_info"]["channels"], 1)

    def test_create_realtime_tts_voice_builds_official_payload(self) -> None:
        payload = create_realtime_tts_voice.build_create_voice_payload(
            str(self.audio_path),
            target_model="qwen3-tts-vc-realtime-2026-01-15",
            prefix="rulaivcrt",
        )

        self.assertEqual(payload["model"], "qwen-voice-enrollment")
        self.assertEqual(payload["input"]["action"], "create")
        self.assertEqual(payload["input"]["target_model"], "qwen3-tts-vc-realtime-2026-01-15")
        self.assertEqual(payload["input"]["preferred_name"], "rulaivcrt")
        self.assertTrue(payload["input"]["audio"]["data"].startswith("data:audio/x-wav;base64,"))


if __name__ == "__main__":
    unittest.main()
