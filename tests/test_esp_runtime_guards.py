from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ESP_MAIN = ROOT / "esp_idf_demo" / "main"


class EspRuntimeGuardTests(unittest.TestCase):
    def test_trigger_polling_is_not_gated_by_idle_state(self) -> None:
        main_c = (ESP_MAIN / "main.c").read_text(encoding="utf-8")

        poll_index = main_c.index("trigger_input_poll(&trigger, &event)")
        idle_gate_index = main_c.index("s_app_state == APP_STATE_IDLE", poll_index)

        self.assertLess(poll_index, idle_gate_index)
        self.assertIn("Trigger ignored", main_c)

    def test_audio_stream_task_uses_explicit_done_flag(self) -> None:
        audio_out_c = (ESP_MAIN / "audio_out.c").read_text(encoding="utf-8")

        self.assertIn("stream_task_done", audio_out_c)
        self.assertNotIn("eTaskGetState(stream_task)", audio_out_c)

    def test_audio_stream_task_flushes_partial_tail_on_stream_stop(self) -> None:
        audio_out_c = (ESP_MAIN / "audio_out.c").read_text(encoding="utf-8")

        self.assertIn("audio_jitter_level_locked() == 0;", audio_out_c)
        self.assertNotIn("audio_jitter_level_locked() == 0 &&\n                              scratch_len == 0", audio_out_c)
        self.assertIn("if (scratch_len > 0)", audio_out_c)


if __name__ == "__main__":
    unittest.main()
