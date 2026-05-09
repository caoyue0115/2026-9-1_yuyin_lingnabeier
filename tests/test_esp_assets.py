from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ESP_DIR = ROOT / "esp_idf_demo"


class EspAssetTests(unittest.TestCase):
    def test_partition_table_allocates_app_and_spiffs_storage(self) -> None:
        partitions = (ESP_DIR / "partitions.csv").read_text(encoding="utf-8")

        self.assertIn("factory,app,factory,0x10000,2M", partitions.replace(" ", ""))
        self.assertIn("storage,data,spiffs,,4M", partitions.replace(" ", ""))

    def test_intro_audio_asset_is_small_pcm_resource(self) -> None:
        intro = ESP_DIR / "spiffs" / "intro_1.pcm"

        self.assertTrue(intro.exists())
        self.assertGreater(intro.stat().st_size, 0)
        self.assertLessEqual(intro.stat().st_size, 64 * 1024)

    def test_record_prompt_audio_asset_is_small_pcm_resource(self) -> None:
        prompt = ESP_DIR / "spiffs" / "record_prompt_1.pcm"

        self.assertTrue(prompt.exists())
        self.assertGreater(prompt.stat().st_size, 0)
        self.assertLessEqual(prompt.stat().st_size, 64 * 1024)

    def test_retry_prompt_audio_assets_are_small_pcm_resources(self) -> None:
        rearm_prompt = ESP_DIR / "spiffs" / "record_retry_rearm_1.pcm"
        timeout_prompt = ESP_DIR / "spiffs" / "record_retry_timeout_1.pcm"
        error_prompt = ESP_DIR / "spiffs" / "record_retry_error_1.pcm"

        for prompt in (rearm_prompt, timeout_prompt, error_prompt):
            self.assertTrue(prompt.exists())
            self.assertGreater(prompt.stat().st_size, 0)
            self.assertLessEqual(prompt.stat().st_size, 64 * 1024)

    def test_realtime_intro_config_is_explicit(self) -> None:
        config = (ESP_DIR / "main" / "config.h").read_text(encoding="utf-8")

        self.assertIn("DEMO_REALTIME_INTRO_ENABLED", config)
        self.assertIn("DEMO_REALTIME_INTRO_PATH", config)
        self.assertIn("DEMO_REALTIME_INTRO_AUDIO_PARALLEL_ENABLED", config)
        self.assertIn("DEMO_REALTIME_AUDIO_PARALLEL_TASK_STACK_SIZE", config)
        self.assertIn("DEMO_REALTIME_AUDIO_GATE_WAIT_TIMEOUT_MS", config)

    def test_record_prompt_config_is_explicit(self) -> None:
        config = (ESP_DIR / "main" / "config.h").read_text(encoding="utf-8")

        self.assertIn("DEMO_RECORD_PROMPT_ENABLED", config)
        self.assertIn("DEMO_RECORD_PROMPT_PATH", config)
        self.assertIn("DEMO_RECORD_RETRY_REARM_PROMPT_PATH", config)
        self.assertIn("DEMO_RECORD_RETRY_TIMEOUT_PROMPT_PATH", config)
        self.assertIn("DEMO_RECORD_RETRY_ERROR_PROMPT_PATH", config)
        self.assertIn("DEMO_WAITING_SPEECH_RETRY_COUNT", config)
        self.assertIn("DEMO_MIC_INIT_RETRY_COUNT", config)
        self.assertIn("DEMO_MIC_INIT_RETRY_DELAY_MS", config)

    def test_realtime_audio_defaults_leave_headroom_for_parallel_intro(self) -> None:
        config = (ESP_DIR / "main" / "config.h").read_text(encoding="utf-8")

        self.assertIn("#define DEMO_REALTIME_AUDIO_JITTER_BUFFER_BYTES 122880", config)
        self.assertIn("#define DEMO_REALTIME_AUDIO_JITTER_PREBUFFER_BYTES 61440", config)
        self.assertIn("#define DEMO_REALTIME_AUDIO_ENCODED_QUEUE_LENGTH 80", config)
        self.assertIn("#define DEMO_REALTIME_AUDIO_PCM_QUEUE_LENGTH 60", config)
        self.assertIn("#define DEMO_REALTIME_AUDIO_QUEUE_SEND_TIMEOUT_MS 1000", config)

    def test_spiffs_image_build_creates_missing_asset_directory(self) -> None:
        cmake = (ESP_DIR / "main" / "CMakeLists.txt").read_text(encoding="utf-8")

        self.assertIn("file(MAKE_DIRECTORY", cmake)
        self.assertIn("../spiffs", cmake)
        self.assertIn("spiffs_create_partition_image(storage ../spiffs FLASH_IN_PROJECT)", cmake)


if __name__ == "__main__":
    unittest.main()
