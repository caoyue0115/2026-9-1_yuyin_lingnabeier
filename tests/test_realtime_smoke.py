from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
import wave
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "realtime_smoke.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("realtime_smoke", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["realtime_smoke"] = module
    spec.loader.exec_module(module)
    return module


def _write_test_wav(pcm_bytes: bytes) -> str:
    fd, path = tempfile.mkstemp(suffix=".wav")
    Path(path).unlink(missing_ok=True)
    with wave.open(path, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(pcm_bytes)
    return path


class RealtimeSmokeScriptTests(unittest.TestCase):
    def test_stream_audio_headers_request_opus_and_pcm(self) -> None:
        module = _load_script_module()

        self.assertEqual(
            module.build_stream_request_headers(),
            {"X-Accept-Audio-Format": "opus,pcm"},
        )

    def test_resolve_audio_stream_url_uses_base_url_origin(self) -> None:
        module = _load_script_module()

        resolved = module.resolve_audio_stream_url(
            "http://<CURRENT_BASE_URL>/api/v3/realtime/sessions/session-1/audio"
        )

        parsed = urlparse(resolved)
        self.assertEqual(f"{parsed.scheme}://{parsed.netloc}", module.BASE_URL)
        self.assertEqual(parsed.path, "/api/v3/realtime/sessions/session-1/audio")

    def test_smoke_main_prints_submit_status_and_audio_metrics(self) -> None:
        module = _load_script_module()
        wav_path = _write_test_wav(b"\x01\x00\x02\x00")

        class _StreamResponse:
            status_code = 200
            headers = {
                "X-Audio-Sample-Rate": "16000",
                "X-Audio-Sample-Width": "16",
                "X-Audio-Channels": "1",
                "X-Audio-Endian": "little",
            }

            def raise_for_status(self) -> None:
                return None

            def iter_bytes(self):
                yield b"\x01\x00\x02\x00"
                yield b"\x03\x00\x04\x00"

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        try:
            stream_calls: list[dict] = []

            with mock.patch.object(
                module,
                "submit_session",
                return_value={
                    "session_id": "session-1",
                    "status": "accepted",
                    "audio_stream_url": "http://testserver/api/v3/realtime/sessions/session-1/audio",
                },
            ), mock.patch.object(
                module,
                "poll_session_until_terminal",
                return_value={
                    "session_id": "session-1",
                    "status": "done",
                    "step": "done",
                    "final_reason": "completed_answer",
                    "error_message": None,
                    "trace": {
                        "asr_ms": 100,
                        "retrieval_ms": 20,
                        "first_llm_chunk_ms": 300,
                        "first_tts_chunk_ms": 600,
                        "first_audio_byte_ms": 650,
                        "done_ms": 1200,
                    },
                    "error_code": None,
                },
            ), mock.patch.object(
                module.httpx,
                "stream",
                side_effect=lambda *args, **kwargs: stream_calls.append(kwargs) or _StreamResponse(),
                create=True,
            ):
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    with mock.patch.object(sys, "argv", ["realtime_smoke.py", wav_path]):
                        module.main()

            lines = [json.loads(line) for line in stdout.getvalue().strip().splitlines()]
            self.assertEqual(lines[0]["event"], "submit")
            self.assertEqual(lines[1]["event"], "status")
            self.assertEqual(lines[2]["event"], "audio")
            self.assertEqual(lines[2]["first_chunk_bytes"], 4)
            self.assertEqual(lines[2]["chunk_count"], 2)
            self.assertEqual(lines[2]["total_audio_bytes"], 8)
            self.assertEqual(lines[2]["byte_rate"], 32000)
            self.assertEqual(lines[2]["audio_format"], "pcm")
            self.assertEqual(lines[2]["audio_packetization"], "legacy")
            self.assertEqual(lines[2]["stream_mode"], "after_done")
            self.assertIn("production_ratio", lines[2])
            self.assertIn("virtual_player", lines[2])
            self.assertEqual(lines[2]["virtual_player"]["underrun_count"], 0)
            self.assertEqual(lines[2]["audio_headers"]["sample_rate"], "16000")
            self.assertEqual(stream_calls[0]["headers"], {"X-Accept-Audio-Format": "opus,pcm"})
        finally:
            Path(wav_path).unlink(missing_ok=True)

    def test_stream_audio_metrics_parses_framed_v1_pcm_packets(self) -> None:
        module = _load_script_module()

        def _frame(seq: int, payload: bytes) -> bytes:
            return seq.to_bytes(4, "big") + len(payload).to_bytes(4, "big") + payload

        class _StreamResponse:
            status_code = 200
            headers = {
                "X-Audio-Format": "pcm",
                "X-Audio-Packetization": "framed-v1",
                "X-Audio-Sample-Rate": "16000",
                "X-Audio-Sample-Width": "16",
                "X-Audio-Channels": "1",
                "X-Audio-Endian": "little",
            }

            def raise_for_status(self) -> None:
                return None

            def iter_bytes(self):
                yield _frame(0, b"\x01\x00\x02\x00")
                yield _frame(1, b"\x03\x00\x04\x00")

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        with mock.patch.object(
            module.httpx,
            "stream",
            return_value=_StreamResponse(),
            create=True,
        ):
            metrics = module.stream_audio_metrics("http://testserver/api/v3/realtime/sessions/session-1/audio")

        self.assertEqual(metrics["audio_format"], "pcm")
        self.assertEqual(metrics["audio_packetization"], "framed-v1")
        self.assertEqual(metrics["packet_count"], 2)
        self.assertEqual(metrics["seq_gap_count"], 0)
        self.assertEqual(metrics["total_audio_bytes"], 8)

    def test_smoke_main_can_stream_immediately_before_terminal_status(self) -> None:
        module = _load_script_module()
        wav_path = _write_test_wav(b"\x01\x00\x02\x00")

        try:
            with mock.patch.object(
                module,
                "submit_session",
                return_value={
                    "session_id": "session-1",
                    "status": "accepted",
                    "audio_stream_url": "http://testserver/api/v3/realtime/sessions/session-1/audio",
                },
            ), mock.patch.object(
                module,
                "stream_audio_metrics",
                return_value={
                    "http_status": 200,
                    "first_chunk_bytes": 4,
                    "chunk_count": 1,
                    "total_audio_bytes": 4,
                    "byte_rate": 32000,
                    "audio_duration_ms": 0,
                    "stream_elapsed_ms": 1,
                    "production_ratio": 0.0,
                    "max_inter_chunk_gap_ms": 0,
                    "avg_inter_chunk_gap_ms": 0,
                    "virtual_player": {"underrun_count": 0},
                },
            ) as stream_audio_metrics, mock.patch.object(
                module,
                "poll_session_until_terminal",
                return_value={
                    "session_id": "session-1",
                    "status": "done",
                    "step": "done",
                    "final_reason": "completed_answer",
                    "trace": {},
                    "error_code": None,
                    "error_message": None,
                },
            ) as poll_session_until_terminal:
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    with mock.patch.object(
                        sys,
                        "argv",
                        ["realtime_smoke.py", wav_path, "--stream-mode", "immediate"],
                    ):
                        module.main()

            lines = [json.loads(line) for line in stdout.getvalue().strip().splitlines()]
            self.assertEqual([line["event"] for line in lines], ["submit", "audio", "status"])
            self.assertEqual(lines[1]["stream_mode"], "immediate")
            stream_audio_metrics.assert_called_once()
            poll_session_until_terminal.assert_called_once()
        finally:
            Path(wav_path).unlink(missing_ok=True)

    def test_smoke_main_skips_audio_when_session_failed(self) -> None:
        module = _load_script_module()
        wav_path = _write_test_wav(b"\x01\x00\x02\x00")

        try:
            with mock.patch.object(
                module,
                "submit_session",
                return_value={
                    "session_id": "session-1",
                    "status": "accepted",
                    "audio_stream_url": "http://testserver/api/v3/realtime/sessions/session-1/audio",
                },
            ), mock.patch.object(
                module,
                "poll_session_until_terminal",
                return_value={
                    "session_id": "session-1",
                    "status": "failed",
                    "step": "failed",
                    "final_reason": "failed",
                    "trace": {"asr_ms": 210},
                    "error_code": "asr_request_failed",
                    "error_message": "DashScope unavailable",
                },
            ), mock.patch.object(
                module,
                "stream_audio_metrics",
            ) as stream_audio_metrics:
                stdout = io.StringIO()
                with self.assertRaises(SystemExit):
                    with redirect_stdout(stdout):
                        with mock.patch.object(sys, "argv", ["realtime_smoke.py", wav_path]):
                            module.main()

            lines = [json.loads(line) for line in stdout.getvalue().strip().splitlines()]
            self.assertEqual(lines[0]["event"], "submit")
            self.assertEqual(lines[1]["event"], "status")
            self.assertEqual(lines[2]["event"], "audio_skipped")
            self.assertEqual(lines[2]["reason"], "session_failed")
            stream_audio_metrics.assert_not_called()
            self.assertEqual(lines[1]["error_message"], "DashScope unavailable")
        finally:
            Path(wav_path).unlink(missing_ok=True)

    def test_virtual_player_counts_underruns_when_arrivals_are_sparse(self) -> None:
        module = _load_script_module()

        stats = module._virtual_player_stats(
            [(0.0, 8192), (1.0, 1024)],
            byte_rate=32000,
            prebuffer_bytes=8192,
        )

        self.assertEqual(stats["playback_start_ms"], 0)
        self.assertGreaterEqual(stats["underrun_count"], 1)
        self.assertGreater(stats["underrun_ms"], 0)


if __name__ == "__main__":
    unittest.main()
