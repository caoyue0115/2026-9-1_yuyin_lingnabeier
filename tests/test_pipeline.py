from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests._stubs import install_dependency_stubs

install_dependency_stubs()

from src.workers import pipeline


class RunPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.row = {
            "task_id": "task-1",
            "input_wav_path": str(ROOT / "data" / "incoming" / "task-1.wav"),
        }

    def test_run_pipeline_marks_asr_failures_with_asr_error_code(self) -> None:
        with mock.patch.object(pipeline, "fetch_task", return_value=self.row), mock.patch.object(
            pipeline, "update_task_status"
        ), mock.patch.object(
            pipeline, "transcribe_wav_result", return_value=pipeline.ASRResult(None, "asr_http_400", "bad request")
        ), mock.patch.object(
            pipeline, "mark_task_failed"
        ) as mark_task_failed:
            pipeline.run_pipeline("task-1")

        mark_task_failed.assert_called_once()
        args = mark_task_failed.call_args.args
        self.assertEqual(args[0], "task-1")
        self.assertEqual(args[1], "asr")
        self.assertEqual(args[2], "asr_http_400")
        self.assertIn("bad request", args[3])
        self.assertIn("asr_ms", args[4])
        self.assertIn("total_ms", args[4])

    def test_run_pipeline_uses_transcribed_question_and_records_asr_ms(self) -> None:
        with mock.patch.object(pipeline, "fetch_task", return_value=self.row), mock.patch.object(
            pipeline, "update_task_status"
        ), mock.patch.object(
            pipeline, "transcribe_wav_result", return_value=pipeline.ASRResult("玲娜贝儿是谁", None, None)
        ) as transcribe_wav_result, mock.patch.object(
            pipeline, "retrieve_references", return_value=([], 0.0)
        ), mock.patch.object(
            pipeline, "synthesize_audio", return_value=(None, "tts_skipped")
        ), mock.patch.object(
            pipeline, "mark_task_done"
        ) as mark_task_done:
            pipeline.run_pipeline("task-1")

        transcribe_wav_result.assert_called_once_with(self.row["input_wav_path"])
        mark_task_done.assert_called_once()
        kwargs = mark_task_done.call_args.kwargs
        self.assertEqual(kwargs["question_text"], "玲娜贝儿是谁")
        self.assertIn("asr_ms", kwargs["trace"])


if __name__ == "__main__":
    unittest.main()
