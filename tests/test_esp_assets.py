from __future__ import annotations

import unittest
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
ESP_DIR = ROOT / "esp_idf_demo"


def _read_macro_value(source: str, name: str) -> str:
    match = re.search(rf"^\s*#define\s+{re.escape(name)}\s+(.+?)\s*$", source, re.MULTILINE)
    if match is None:
        raise AssertionError(f"missing macro {name}")
    return match.group(1)


def _strip_p3c_boot_switch_blocks(source: str) -> str:
    return re.sub(
        r"(?ms)^#if DEMO_OTA_BOOT_SWITCH_ENABLED\b.*?^#endif\s*/\*\s*DEMO_OTA_BOOT_SWITCH_ENABLED\s*\*/\s*$",
        "",
        source,
    )


def _p3c_boot_switch_blocks(source: str) -> list[str]:
    return re.findall(
        r"(?ms)^#if DEMO_OTA_BOOT_SWITCH_ENABLED\b.*?^#endif\s*/\*\s*DEMO_OTA_BOOT_SWITCH_ENABLED\s*\*/\s*$",
        source,
    )


def _strip_p3d_rollback_blocks(source: str) -> str:
    return re.sub(
        r"(?ms)^#if DEMO_OTA_ROLLBACK_VALIDATION_ENABLED\b.*?^#endif\s*$",
        "",
        source,
    )


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
        self.assertEqual("0", _read_macro_value(config, "DEMO_REALTIME_INTRO_ENABLED"))
        self.assertIn("DEMO_REALTIME_INTRO_PATH", config)
        self.assertIn("DEMO_REALTIME_INTRO_AUDIO_PARALLEL_ENABLED", config)
        self.assertIn("DEMO_REALTIME_AUDIO_PARALLEL_TASK_STACK_SIZE", config)
        self.assertIn("DEMO_REALTIME_AUDIO_GATE_WAIT_TIMEOUT_MS", config)

    def test_record_prompt_config_is_explicit(self) -> None:
        config = (ESP_DIR / "main" / "config.h").read_text(encoding="utf-8")

        self.assertIn("DEMO_RECORD_PROMPT_ENABLED", config)
        self.assertEqual("1", _read_macro_value(config, "DEMO_RECORD_PROMPT_ENABLED"))
        self.assertIn("DEMO_RECORD_PROMPT_PATH", config)
        self.assertIn("DEMO_RECORD_RETRY_REARM_PROMPT_PATH", config)
        self.assertIn("DEMO_RECORD_RETRY_TIMEOUT_PROMPT_PATH", config)
        self.assertIn("DEMO_RECORD_RETRY_ERROR_PROMPT_PATH", config)
        self.assertIn("DEMO_WAITING_SPEECH_RETRY_COUNT", config)
        self.assertIn("DEMO_MIC_INIT_RETRY_COUNT", config)
        self.assertIn("DEMO_MIC_INIT_RETRY_DELAY_MS", config)

    def test_spiffs_mount_is_kept_for_record_prompt_when_intro_is_disabled(self) -> None:
        main_source = (ESP_DIR / "main" / "main.c").read_text(encoding="utf-8")

        self.assertIn("DEMO_REALTIME_INTRO_ENABLED || DEMO_RECORD_PROMPT_ENABLED", main_source)
        self.assertNotIn("if (DEMO_REALTIME_INTRO_ENABLED) {\n        (void)app_mount_spiffs();", main_source)

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
        self.assertIn("DEMO_OTA_MANIFEST_TASK_STACK_SIZE", config)
        self.assertIn("cloud_client_fetch_ota_manifest", cloud_header)
        self.assertIn("api/v5/ota/manifest", cloud_source)
        self.assertIn("ota_manifest_dry_run", main_source)
        self.assertIn("cloud_client_fetch_ota_manifest", main_source)
        self.assertIn("app_ota_manifest_dry_run_task", main_source)
        self.assertIn("xTaskCreate(app_ota_manifest_dry_run_task", main_source)
        non_p3c_combined = _strip_p3c_boot_switch_blocks(combined)
        self.assertNotIn("esp_ota_set_boot_partition", non_p3c_combined)
        self.assertNotIn("esp_restart", non_p3c_combined)
        self.assertNotIn("esp_ota_mark_app_valid_cancel_rollback", _strip_p3d_rollback_blocks(combined))
        self.assertNotIn("esp_ota_mark_app_invalid_rollback_and_reboot", combined)

    def test_ota_p3a_download_verify_is_present_without_partition_writes(self) -> None:
        cloud_header = (ESP_DIR / "main" / "cloud_client.h").read_text(encoding="utf-8")
        cloud_source = (ESP_DIR / "main" / "cloud_client.c").read_text(encoding="utf-8")
        main_source = (ESP_DIR / "main" / "main.c").read_text(encoding="utf-8")
        combined = "\n".join((cloud_header, cloud_source, main_source))

        self.assertIn("cloud_ota_artifact_verify_t", cloud_header)
        self.assertIn("cloud_client_verify_ota_artifact", cloud_header)
        self.assertIn("mbedtls_sha256_context", cloud_source)
        self.assertIn("cloud_hex_encode_sha256", cloud_source)
        self.assertIn("stage=ota_artifact_verify event=start", main_source)
        self.assertIn("stage=ota_artifact_verify event=done", main_source)
        self.assertIn("stage=ota_artifact_verify event=failed", main_source)
        self.assertIn("cloud_client_submit_ota_report", cloud_header)
        self.assertIn("api/v5/ota/report", cloud_source)
        self.assertIn("stage=ota_report event=done", main_source)
        self.assertIn("stage=ota_report event=failed", main_source)
        self.assertIn("action=download_verify_only", main_source)
        non_p3c_combined = _strip_p3c_boot_switch_blocks(combined)
        self.assertNotIn("esp_ota_set_boot_partition", non_p3c_combined)
        self.assertNotIn("esp_restart", non_p3c_combined)
        self.assertNotIn("esp_ota_mark_app_valid_cancel_rollback", _strip_p3d_rollback_blocks(combined))
        self.assertNotIn("esp_ota_mark_app_invalid_rollback_and_reboot", combined)

    def test_ota_p3b_partition_write_is_present_without_boot_switch_or_reboot(self) -> None:
        cloud_header = (ESP_DIR / "main" / "cloud_client.h").read_text(encoding="utf-8")
        cloud_source = (ESP_DIR / "main" / "cloud_client.c").read_text(encoding="utf-8")
        main_source = (ESP_DIR / "main" / "main.c").read_text(encoding="utf-8")
        config = (ESP_DIR / "main" / "config.h").read_text(encoding="utf-8")
        combined = "\n".join((cloud_header, cloud_source, main_source))

        self.assertIn("DEMO_OTA_PARTITION_WRITE_ENABLED", config)
        self.assertIn("esp_ota_get_running_partition", main_source)
        self.assertIn("esp_ota_get_next_update_partition", main_source)
        self.assertIn("esp_ota_begin", main_source)
        self.assertIn("esp_ota_write", main_source)
        self.assertIn("esp_ota_end", main_source)
        self.assertIn("esp_ota_abort", main_source)
        self.assertIn("cloud_client_stream_ota_artifact", cloud_header)
        self.assertIn("cloud_client_stream_ota_artifact", cloud_source)
        self.assertIn("stage=ota_partition_write event=start", main_source)
        self.assertIn("stage=ota_partition_write event=done", main_source)
        self.assertIn("stage=ota_partition_write event=failed", main_source)
        self.assertIn("action=write_inactive_only", main_source)
        self.assertIn("no_boot_switch=1", main_source)
        self.assertIn("no_reboot=1", main_source)
        self.assertIn("running_partition", main_source)
        self.assertIn("update_partition", main_source)
        self.assertIn("report_stage=partition_write", main_source)
        self.assertIn("partition_label", cloud_header)
        self.assertIn("partition_subtype", cloud_header)
        self.assertIn("partition_address", cloud_header)
        self.assertIn("bytes_written", cloud_header)
        non_p3c_combined = _strip_p3c_boot_switch_blocks(combined)
        self.assertNotIn("esp_ota_set_boot_partition", non_p3c_combined)
        self.assertNotIn("esp_restart", non_p3c_combined)
        self.assertNotIn("esp_ota_mark_app_valid_cancel_rollback", _strip_p3d_rollback_blocks(combined))
        self.assertNotIn("esp_ota_mark_app_invalid_rollback_and_reboot", combined)

    def test_ota_p3c_boot_switch_is_default_off_and_gated(self) -> None:
        cloud_header = (ESP_DIR / "main" / "cloud_client.h").read_text(encoding="utf-8")
        cloud_source = (ESP_DIR / "main" / "cloud_client.c").read_text(encoding="utf-8")
        main_source = (ESP_DIR / "main" / "main.c").read_text(encoding="utf-8")
        config = (ESP_DIR / "main" / "config.h").read_text(encoding="utf-8")
        combined = "\n".join((cloud_header, cloud_source, main_source))

        self.assertIn("DEMO_OTA_BOOT_SWITCH_ENABLED", config)
        self.assertEqual("0", _read_macro_value(config, "DEMO_OTA_BOOT_SWITCH_ENABLED"))
        self.assertIn("ota_boot_switch_enabled", main_source)

        p3c_blocks = "\n".join(_p3c_boot_switch_blocks(main_source))
        self.assertIn("esp_ota_set_boot_partition", p3c_blocks)
        self.assertIn("esp_restart", p3c_blocks)
        self.assertNotIn("esp_ota_set_boot_partition", _strip_p3c_boot_switch_blocks(combined))
        self.assertNotIn("esp_restart", _strip_p3c_boot_switch_blocks(combined))

        self.assertNotIn("esp_ota_mark_app_valid_cancel_rollback", _strip_p3d_rollback_blocks(combined))
        self.assertNotIn("esp_ota_mark_app_invalid_rollback_and_reboot", combined)

    def test_ota_p3c_logs_and_report_fields_are_present(self) -> None:
        cloud_header = (ESP_DIR / "main" / "cloud_client.h").read_text(encoding="utf-8")
        cloud_source = (ESP_DIR / "main" / "cloud_client.c").read_text(encoding="utf-8")
        main_source = (ESP_DIR / "main" / "main.c").read_text(encoding="utf-8")
        api_source = (ROOT / "src" / "api" / "ota.py").read_text(encoding="utf-8")

        self.assertIn("action=download_verify_only", main_source)
        self.assertIn("action=write_inactive_only", main_source)
        self.assertIn("action=write_switch_reboot", main_source)
        self.assertIn("no_boot_switch=0", main_source)
        self.assertIn("reboot_scheduled=1", main_source)
        self.assertIn("boot_partition_before", main_source)
        self.assertIn("boot_partition_after_set", main_source)
        self.assertIn("stage=ota_boot_switch event=start", main_source)
        self.assertIn("stage=ota_boot_switch event=done", main_source)
        self.assertIn("stage=ota_boot_switch event=failed", main_source)
        self.assertIn("report_stage=boot_switch_scheduled", main_source)
        self.assertIn("stage=ota_post_reboot_confirm", main_source)
        self.assertIn("report_stage=post_reboot_confirm", main_source)

        for field in (
            "boot_partition_before",
            "boot_partition_after_set",
            "running_partition_after_reboot",
            "reboot_reason",
        ):
            self.assertIn(field, cloud_header)
            self.assertIn(field, cloud_source)
            self.assertIn(field, api_source)

    def test_ota_p3c_post_reboot_confirm_runs_in_dedicated_task(self) -> None:
        config = (ESP_DIR / "main" / "config.h").read_text(encoding="utf-8")
        main_source = (ESP_DIR / "main" / "main.c").read_text(encoding="utf-8")
        app_main_source = main_source.split("void app_main(void)", 1)[1]

        self.assertIn("DEMO_OTA_POST_REBOOT_TASK_STACK_SIZE", config)
        self.assertEqual("8192", _read_macro_value(config, "DEMO_OTA_POST_REBOOT_TASK_STACK_SIZE"))
        self.assertIn("app_ota_post_reboot_confirm_task", main_source)
        self.assertIn("xTaskCreate(app_ota_post_reboot_confirm_task", main_source)
        self.assertIn("DEMO_OTA_POST_REBOOT_TASK_STACK_SIZE", main_source)
        self.assertIn("vTaskDelete(NULL)", main_source)
        self.assertNotIn("app_ota_post_reboot_confirm_if_pending(", app_main_source)

    def test_ota_p3d_rollback_validation_is_default_off_and_gated(self) -> None:
        config = (ESP_DIR / "main" / "config.h").read_text(encoding="utf-8")
        main_source = (ESP_DIR / "main" / "main.c").read_text(encoding="utf-8")
        combined = "\n".join((config, main_source))

        self.assertIn("DEMO_OTA_ROLLBACK_VALIDATION_ENABLED", config)
        self.assertEqual("0", _read_macro_value(config, "DEMO_OTA_ROLLBACK_VALIDATION_ENABLED"))
        self.assertIn("DEMO_OTA_ROLLBACK_VALIDATION_TIMEOUT_MS", config)
        self.assertIn("#if DEMO_OTA_ROLLBACK_VALIDATION_ENABLED", main_source)
        self.assertIn("esp_ota_mark_app_valid_cancel_rollback", main_source)
        self.assertNotIn("esp_ota_mark_app_invalid_rollback_and_reboot", combined)

    def test_ota_p3d_marks_valid_only_after_business_ready(self) -> None:
        main_source = (ESP_DIR / "main" / "main.c").read_text(encoding="utf-8")

        post_confirm_pos = main_source.index("report_stage=post_reboot_confirm")
        business_ready_pos = main_source.index("app_ota_rollback_note_business_ready")
        mark_valid_pos = main_source.index("esp_ota_mark_app_valid_cancel_rollback")
        app_validated_report_pos = main_source.index("report_stage=app_validated")

        self.assertLess(post_confirm_pos, business_ready_pos)
        self.assertLess(business_ready_pos, mark_valid_pos)
        self.assertLess(mark_valid_pos, app_validated_report_pos)

    def test_ota_p3d_business_hang_edge_case_has_timeout_without_mark_valid(self) -> None:
        main_source = (ESP_DIR / "main" / "main.c").read_text(encoding="utf-8")

        self.assertIn("app_ota_rollback_validation_timeout_task", main_source)
        self.assertIn("stage=ota_app_validation event=timeout", main_source)
        self.assertIn("DEMO_OTA_ROLLBACK_VALIDATION_TIMEOUT_MS", main_source)
        self.assertIn("esp_restart()", main_source)
        timeout_pos = main_source.index("stage=ota_app_validation event=timeout")
        mark_valid_pos = main_source.index("esp_ota_mark_app_valid_cancel_rollback")
        self.assertLess(mark_valid_pos, timeout_pos)

    def test_wifi_password_empty_preserves_stored_station_config(self) -> None:
        main_source = (ESP_DIR / "main" / "main.c").read_text(encoding="utf-8")

        self.assertIn("DEMO_WIFI_PASSWORD[0] != '\\0'", main_source)
        self.assertIn("using stored Wi-Fi station credentials from NVS", main_source)
        self.assertIn("esp_wifi_set_config(WIFI_IF_STA, &wifi_cfg)", main_source)


if __name__ == "__main__":
    unittest.main()
