from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ESP_DIR = ROOT / "esp_idf_demo"


class EspAssetTests(unittest.TestCase):
    def test_partition_table_allocates_ab_ota_app_slots_and_spiffs_storage(self) -> None:
        partitions = (ESP_DIR / "partitions.csv").read_text(encoding="utf-8")
        normalized = partitions.replace(" ", "")

        self.assertIn("nvs,data,nvs,0x9000,0x6000", normalized)
        self.assertIn("otadata,data,ota,0xF000,0x2000", normalized)
        self.assertIn("phy_init,data,phy,0x11000,0x1000", normalized)
        self.assertIn("ota_0,app,ota_0,0x20000,3M", normalized)
        self.assertIn("ota_1,app,ota_1,,3M", normalized)
        self.assertIn("storage,data,spiffs,,4M", normalized)
        self.assertNotIn("factory,app,factory", normalized)

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
        self.assertIn("#define DEMO_REALTIME_AUDIO_JITTER_PREBUFFER_BYTES 81920", config)
        self.assertIn("#define DEMO_REALTIME_AUDIO_ENCODED_QUEUE_LENGTH 80", config)
        self.assertIn("#define DEMO_REALTIME_AUDIO_PCM_QUEUE_LENGTH 60", config)
        self.assertIn("#define DEMO_REALTIME_AUDIO_QUEUE_SEND_TIMEOUT_MS 1000", config)

    def test_spiffs_image_build_creates_missing_asset_directory(self) -> None:
        cmake = (ESP_DIR / "main" / "CMakeLists.txt").read_text(encoding="utf-8")

        self.assertIn("file(MAKE_DIRECTORY", cmake)
        self.assertIn("../spiffs", cmake)
        self.assertIn("spiffs_create_partition_image(storage ../spiffs FLASH_IN_PROJECT)", cmake)

    def test_ota_p2_manifest_dry_run_is_present_without_partition_writes(self) -> None:
        config = (ESP_DIR / "main" / "config.h").read_text(encoding="utf-8")
        cloud_header = (ESP_DIR / "main" / "cloud_client.h").read_text(encoding="utf-8")
        cloud_source = (ESP_DIR / "main" / "cloud_client.c").read_text(encoding="utf-8")
        main_source = (ESP_DIR / "main" / "main.c").read_text(encoding="utf-8")
        combined = "\n".join((cloud_header, cloud_source, main_source))

        self.assertIn("DEMO_OTA_MANIFEST_DRY_RUN_ENABLED", config)
        self.assertIn("DEMO_OTA_MANIFEST_POLL_INTERVAL_MS", config)
        self.assertIn("DEMO_OTA_IDLE_AFTER_WS_DELAY_MS", config)
        self.assertIn("cloud_client_fetch_ota_manifest", cloud_header)
        self.assertIn("api/v5/ota/manifest", cloud_source)
        self.assertIn("ota_manifest_dry_run", main_source)
        self.assertIn("cloud_client_fetch_ota_manifest", main_source)
        self.assertNotIn("esp_ota_begin", combined)
        self.assertNotIn("esp_ota_write", combined)
        self.assertNotIn("esp_ota_set_boot_partition", combined)


if __name__ == "__main__":
    unittest.main()
