from __future__ import annotations

import os
import sys
import threading
import time
import unittest
from http import HTTPStatus
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests._stubs import install_dependency_stubs

install_dependency_stubs()

from src.providers import asr


class _FakeSuccessResult:
    status_code = HTTPStatus.OK

    def get_sentence(self) -> str:
        return "观自在菩萨"


class _FakeFallbackResult:
    status_code = HTTPStatus.OK

    def __init__(self) -> None:
        self.output = {"sentences": [{"text": "色即是空"}]}


class _FakeFailureResult:
    status_code = HTTPStatus.BAD_REQUEST
    message = "bad request"


class _FakeRecognition:
    last_kwargs: dict | None = None
    last_audio_path: str | None = None
    result = _FakeSuccessResult()

    def __init__(self, **kwargs) -> None:
        type(self).last_kwargs = kwargs

    def call(self, audio_path: str):
        type(self).last_audio_path = audio_path
        return type(self).result


class _FakeSlowRecognition(_FakeRecognition):
    def call(self, audio_path: str):
        time.sleep(0.05)
        return super().call(audio_path)


class TranscribeWavTests(unittest.TestCase):
    def setUp(self) -> None:
        self.audio_path = ROOT / "data" / "incoming" / "unit-test.wav"
        self.audio_path.parent.mkdir(parents=True, exist_ok=True)
        self.audio_path.write_bytes(b"RIFF")

    def tearDown(self) -> None:
        self.audio_path.unlink(missing_ok=True)

    def test_asr_health_requires_sdk_import_availability(self) -> None:
        with mock.patch.object(asr.settings, "dashscope_api_key", "key"), mock.patch.object(
            asr.settings, "asr_model", "paraformer-realtime-v2"
        ), mock.patch.object(asr.settings, "asr_provider", "dashscope"), mock.patch.object(
            asr, "_load_recognition_class", side_effect=ImportError("dashscope missing")
        ):
            self.assertFalse(asr.asr_health())

    def test_asr_health_accepts_volcengine_streaming_credentials(self) -> None:
        with mock.patch.object(asr.settings, "asr_provider", "volcengine"), mock.patch.dict(
            os.environ,
            {
                "VOLCENGINE_SPEECH_APP_ID": "app-id",
                "VOLCENGINE_SPEECH_ACCESS_TOKEN": "access-token",
                "VOLCENGINE_ASR_RESOURCE_ID": "resource-id",
            },
            clear=False,
        ), mock.patch.object(asr, "_load_recognition_class", side_effect=AssertionError("dashscope not used")):
            self.assertTrue(asr.asr_health())

    def test_transcribe_wav_uses_dashscope_recognition_and_returns_sentence(self) -> None:
        _FakeRecognition.result = _FakeSuccessResult()
        with mock.patch.object(asr, "_is_asr_configured", return_value=True), mock.patch.object(
            asr, "_load_recognition_class", return_value=_FakeRecognition
        ), mock.patch.object(asr, "_configure_dashscope_sdk") as configure_sdk:
            text, error_code = asr.transcribe_wav(self.audio_path)

        self.assertEqual(text, "观自在菩萨")
        self.assertIsNone(error_code)
        self.assertEqual(_FakeRecognition.last_audio_path, str(self.audio_path))
        self.assertEqual(
            _FakeRecognition.last_kwargs,
            {
                "model": "paraformer-realtime-v2",
                "format": "wav",
                "sample_rate": 16000,
                "language_hints": ["zh"],
                "callback": None,
            },
        )
        configure_sdk.assert_called_once()

    def test_transcribe_wav_passes_vocabulary_id_when_configured(self) -> None:
        _FakeRecognition.result = _FakeSuccessResult()
        with mock.patch.object(asr, "_is_asr_configured", return_value=True), mock.patch.object(
            asr, "_load_recognition_class", return_value=_FakeRecognition
        ), mock.patch.object(asr, "_configure_dashscope_sdk"), mock.patch.object(
            asr.settings, "asr_vocabulary_id", "vocab-buddha-123"
        ):
            text, error_code = asr.transcribe_wav(self.audio_path)

        self.assertEqual(text, "观自在菩萨")
        self.assertIsNone(error_code)
        self.assertEqual(_FakeRecognition.last_kwargs["vocabulary_id"], "vocab-buddha-123")

    def test_transcribe_wav_falls_back_to_nested_output_parsing(self) -> None:
        _FakeRecognition.result = _FakeFallbackResult()
        with mock.patch.object(asr, "_is_asr_configured", return_value=True), mock.patch.object(
            asr, "_load_recognition_class", return_value=_FakeRecognition
        ), mock.patch.object(asr, "_configure_dashscope_sdk"):
            text, error_code = asr.transcribe_wav(self.audio_path)

        self.assertEqual(text, "色即是空")
        self.assertIsNone(error_code)

    def test_transcribe_wav_maps_non_ok_status_to_asr_http_code(self) -> None:
        _FakeRecognition.result = _FakeFailureResult()
        with mock.patch.object(asr, "_is_asr_configured", return_value=True), mock.patch.object(
            asr, "_load_recognition_class", return_value=_FakeRecognition
        ), mock.patch.object(asr, "_configure_dashscope_sdk"):
            text, error_code = asr.transcribe_wav(self.audio_path)

        self.assertIsNone(text)
        self.assertEqual(error_code, "asr_http_400")

    def test_transcribe_wav_maps_slow_sdk_call_to_asr_timeout(self) -> None:
        _FakeSlowRecognition.result = _FakeSuccessResult()
        with mock.patch.object(asr, "_is_asr_configured", return_value=True), mock.patch.object(
            asr, "_load_recognition_class", return_value=_FakeSlowRecognition
        ), mock.patch.object(asr, "_configure_dashscope_sdk"), mock.patch.object(
            asr.settings, "asr_timeout_seconds", 0.01
        ):
            text, error_code = asr.transcribe_wav(self.audio_path)

        self.assertIsNone(text)
        self.assertEqual(error_code, "asr_timeout")

    def test_transcribe_wav_result_preserves_sdk_message(self) -> None:
        _FakeRecognition.result = _FakeFailureResult()
        with mock.patch.object(asr, "_is_asr_configured", return_value=True), mock.patch.object(
            asr, "_load_recognition_class", return_value=_FakeRecognition
        ), mock.patch.object(asr, "_configure_dashscope_sdk"):
            result = asr.transcribe_wav_result(self.audio_path)

        self.assertEqual(result.error_code, "asr_http_400")
        self.assertEqual(result.error_message, "bad request")

    def test_run_with_timeout_skips_signal_guard_outside_main_thread(self) -> None:
        recognition = _FakeRecognition()
        result_holder: dict[str, object] = {}

        def _target() -> None:
            result_holder["result"] = asr._run_with_timeout(recognition, str(self.audio_path))

        with mock.patch.object(asr, "_is_main_thread", return_value=False), mock.patch.object(
            asr.signal, "signal"
        ) as signal_fn, mock.patch.object(
            asr.signal, "setitimer"
        ) as setitimer_fn:
            thread = threading.Thread(target=_target)
            thread.start()
            thread.join()

        self.assertIsInstance(result_holder["result"], _FakeSuccessResult)
        signal_fn.assert_not_called()
        setitimer_fn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
