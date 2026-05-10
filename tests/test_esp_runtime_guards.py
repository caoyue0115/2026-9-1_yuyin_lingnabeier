from __future__ import annotations

import unittest
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
ESP_MAIN = ROOT / "esp_idf_demo" / "main"


class EspRuntimeGuardTests(unittest.TestCase):
    def test_v5_opus_uplink_legacy_audio_fallback_is_debug_only(self) -> None:
        config_h = (ESP_MAIN / "config.h").read_text(encoding="utf-8")
        main_c = (ESP_MAIN / "main.c").read_text(encoding="utf-8")
        design_doc = (
            ROOT / "docs" / "superpowers" / "specs" / "2026-05-10-v5-esp32-opus-uplink-design.md"
        ).read_text(encoding="utf-8")

        fallback_default = re.search(
            r"#define\s+V5_OPUS_UPLINK_FALLBACK_LEGACY_AUDIO\s+(\d+)",
            config_h,
        )
        self.assertIsNotNone(fallback_default)
        self.assertEqual(fallback_default.group(1), "0")

        self.assertIn("V5_OPUS_UPLINK_BEHAVIOR_FALLBACK_ENABLED", config_h)
        self.assertIn("v5_uplink_failed", main_c)
        self.assertIn("fallback_behavior=local_prompt", main_c)
        self.assertIn("legacy_audio_fallback=false", main_c)
        self.assertIn("legacy_audio_fallback=true", main_c)
        self.assertNotIn("默认启用 v5 WS 上行并保留旧路径 fallback", design_doc)
        self.assertIn("L3", design_doc)

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
