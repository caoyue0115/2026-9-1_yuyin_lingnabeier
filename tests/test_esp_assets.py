from __future__ import annotations

import unittest
from pathlib import Path
from array import array
import hashlib
import re
import subprocess
import sys
import tarfile
import tempfile


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
        self.assertIn("model,data,,,1M", normalized)
        self.assertNotIn("factory,app,factory", normalized)

    def test_vocat_lowcost_16m8m_profile_is_explicit_and_keeps_safety_defaults(self) -> None:
        profile_path = ESP_DIR / "sdkconfig.defaults.vocat_lowcost_16m8m"
        config = (ESP_DIR / "main" / "config.h").read_text(encoding="utf-8")
        partitions = (ESP_DIR / "partitions.csv").read_text(encoding="utf-8").replace(" ", "")

        self.assertTrue(profile_path.exists())
        profile = profile_path.read_text(encoding="utf-8")

        for required in (
            "CONFIG_ESPTOOLPY_FLASHSIZE_16MB=y",
            "CONFIG_SPIRAM=y",
            "CONFIG_SPIRAM_MODE_OCT=y",
            "CONFIG_SPIRAM_TYPE_AUTO=y",
            "CONFIG_SPIRAM_SPEED_80M=y",
            "CONFIG_SPIRAM_USE_MALLOC=y",
            "CONFIG_FREERTOS_TASK_CREATE_ALLOW_EXT_MEM=y",
            "CONFIG_SPIRAM_ALLOW_STACK_EXTERNAL_MEMORY=y",
            'CONFIG_PARTITION_TABLE_CUSTOM_FILENAME="partitions.csv"',
        ):
            self.assertIn(required, profile)

        for forbidden in (
            "DEMO_WIFI_PASSWORD",
            "DEMO_WIFI_SSID",
            "DEMO_SERVER_BASE_URL",
            "DEMO_DEVICE_ID",
            "DEMO_OTA_BOOT_SWITCH_ENABLED 1",
            "DEMO_OTA_ROLLBACK_VALIDATION_ENABLED 1",
        ):
            self.assertNotIn(forbidden, profile)

        self.assertEqual("0", _read_macro_value(config, "DEMO_OTA_BOOT_SWITCH_ENABLED"))
        self.assertEqual("0", _read_macro_value(config, "DEMO_OTA_ROLLBACK_VALIDATION_ENABLED"))
        self.assertIn("ota_0,app,ota_0,0x20000,3M", partitions)
        self.assertIn("ota_1,app,ota_1,,3M", partitions)
        self.assertIn("storage,data,spiffs,,4M", partitions)
        self.assertIn("model,data,,,1M", partitions)

    def test_vocat_lowcost_16m8m_defaults_to_v1_0_audio_binding(self) -> None:
        profile = (ESP_DIR / "sdkconfig.defaults.vocat_lowcost_16m8m").read_text(encoding="utf-8")
        config = (ESP_DIR / "main" / "config.h").read_text(encoding="utf-8")
        main_cmake = (ESP_DIR / "main" / "CMakeLists.txt").read_text(encoding="utf-8")
        main_source = (ESP_DIR / "main" / "main.c").read_text(encoding="utf-8")
        audio_in_source = (ESP_DIR / "main" / "audio_in.c").read_text(encoding="utf-8")
        audio_out_source = (ESP_DIR / "main" / "audio_out.c").read_text(encoding="utf-8")
        board_audio_header = (ESP_DIR / "main" / "board_audio.h").read_text(encoding="utf-8")
        board_audio_source = (ESP_DIR / "main" / "board_audio.c").read_text(encoding="utf-8")

        self.assertIn("CONFIG_DEMO_TARGET_PROFILE_VOCAT_LOWCOST_16M8M=y", profile)
        self.assertIn("CONFIG_DEMO_AUDIO_PCB_ESP_VOCAT_V1_0=y", profile)
        self.assertNotIn("CONFIG_DEMO_AUDIO_PCB_ESP_VOCAT_V1_2=y", profile)

        self.assertIn("DEMO_BOARD_PROFILE_ESP_VOCAT_V1_0_AUDIO", config)
        self.assertIn("DEMO_TARGET_PROFILE \"vocat_lowcost_16m8m\"", config)
        self.assertIn("DEMO_BOARD_REVISION \"v1.0\"", config)
        self.assertIn("DEMO_BOARD_AUDIO_PCB_REVISION \"v1.0\"", config)
        self.assertIn("#define DEMO_AUDIO_I2S_DIN_GPIO GPIO_NUM_15", config)
        self.assertIn("#define DEMO_AUDIO_PA_GPIO GPIO_NUM_4", config)
        self.assertIn("#define DEMO_AUDIO_GPIO48_ENABLE 0", config)

        self.assertIn('"board_audio.c"', main_cmake)
        self.assertIn("board_audio_init", board_audio_header)
        self.assertIn("board_audio_codec_speaker_init", board_audio_header)
        self.assertIn("board_audio_codec_microphone_init", board_audio_header)
        self.assertIn(".din = DEMO_AUDIO_I2S_DIN_GPIO", board_audio_source)
        self.assertIn(".pa_pin = DEMO_AUDIO_PA_GPIO", board_audio_source)
        self.assertIn("#if DEMO_AUDIO_GPIO48_ENABLE", board_audio_source)
        self.assertIn("audio_gpio48_enable=0", board_audio_source)

        self.assertIn("board_audio_init(NULL)", audio_in_source)
        self.assertIn("board_audio_codec_microphone_init", audio_in_source)
        self.assertNotIn("bsp_audio_codec_microphone_init", audio_in_source)
        self.assertIn("board_audio_init(NULL)", audio_out_source)
        self.assertIn("board_audio_codec_speaker_init", audio_out_source)
        self.assertNotIn("bsp_audio_codec_speaker_init", audio_out_source)

        for marker in (
            "board_rev=",
            "target_profile=",
            "audio_pcb_rev=",
            "audio_i2s_din_gpio=",
            "audio_pa_gpio=",
            "audio_gpio48_enable=",
        ):
            self.assertIn(marker, main_source)

        self.assertEqual("0", _read_macro_value(config, "DEMO_OTA_BOOT_SWITCH_ENABLED"))
        self.assertEqual("0", _read_macro_value(config, "DEMO_OTA_ROLLBACK_VALIDATION_ENABLED"))

    def test_lowcost_default_trigger_is_gpio7_button_with_touch_override_available(self) -> None:
        config = (ESP_DIR / "main" / "config.h").read_text(encoding="utf-8")

        self.assertIn("#define DEMO_TRIGGER_SOURCE DEMO_TRIGGER_SOURCE_BUTTON_AND_WAKE_WORD", config)
        self.assertIn("#ifndef DEMO_BUTTON_GPIO", config)
        self.assertIn("#define DEMO_BUTTON_GPIO         GPIO_NUM_7", config)
        self.assertIn("#ifndef DEMO_WIFI_RECONFIG_GPIO", config)
        self.assertIn("#define DEMO_WIFI_RECONFIG_GPIO  GPIO_NUM_0", config)
        self.assertIn("#ifndef DEMO_TRIGGER_SOURCE", config)
        self.assertIn("DEMO_TRIGGER_SOURCE_TOUCH", config)
        self.assertIn("DEMO_TRIGGER_SOURCE_BUTTON", config)
        self.assertNotIn("#define DEMO_BUTTON_GPIO         GPIO_NUM_6", config)

    def test_realtime_lowcost_observability_markers_are_present_without_release_boundary_changes(self) -> None:
        config = (ESP_DIR / "main" / "config.h").read_text(encoding="utf-8")
        partitions = (ESP_DIR / "partitions.csv").read_text(encoding="utf-8").replace(" ", "")
        audio_source = (ESP_DIR / "main" / "audio_out.c").read_text(encoding="utf-8")
        cloud_header = (ESP_DIR / "main" / "cloud_client.h").read_text(encoding="utf-8")
        cloud_source = (ESP_DIR / "main" / "cloud_client.c").read_text(encoding="utf-8")
        main_source = (ESP_DIR / "main" / "main.c").read_text(encoding="utf-8")
        combined = "\n".join((audio_source, cloud_header, cloud_source, main_source))

        for marker in (
            "realtime_heap stage=",
            "free_spiram",
            "largest_spiram",
            "cloud_decode_stack",
            "cloud_playback_stack",
            "audio_stream_stack",
            "receive_queue_pending_bytes_peak",
            "pcm_queue_pending_bytes_peak",
        ):
            self.assertIn(marker, combined)

        self.assertEqual("0", _read_macro_value(config, "DEMO_OTA_BOOT_SWITCH_ENABLED"))
        self.assertEqual("0", _read_macro_value(config, "DEMO_OTA_ROLLBACK_VALIDATION_ENABLED"))
        self.assertIn("ota_0,app,ota_0,0x20000,3M", partitions)
        self.assertIn("ota_1,app,ota_1,,3M", partitions)
        self.assertIn("storage,data,spiffs,,4M", partitions)
        self.assertIn("model,data,,,1M", partitions)

        release_logic_sources = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                ROOT / "scripts" / "build_esp_p3c_canary_artifact.sh",
                ROOT / "scripts" / "build_esp_p3d_canary_artifact.sh",
                ROOT / "scripts" / "ota_release_create.py",
                ROOT / "scripts" / "ota_release_closeout.py",
                ROOT / "scripts" / "package_esp_compile_only.py",
                ROOT / "src" / "api" / "ota.py",
                ROOT / "src" / "storage" / "db.py",
            )
        )
        self.assertNotIn("miaoban-v1p2-003", release_logic_sources)

    def test_intro_audio_asset_is_small_pcm_resource(self) -> None:
        intro = ESP_DIR / "spiffs" / "intro_1.pcm"

        self.assertTrue(intro.exists())
        self.assertGreater(intro.stat().st_size, 0)
        self.assertLessEqual(intro.stat().st_size, 64 * 1024)

    def test_boot_sound_audio_asset_is_small_pcm_resource(self) -> None:
        boot_sound = ESP_DIR / "spiffs" / "boot_amitabha_1.pcm"

        self.assertTrue(boot_sound.exists())
        self.assertGreater(boot_sound.stat().st_size, 0)
        self.assertLessEqual(boot_sound.stat().st_size, 64 * 1024)
        self.assertEqual(64_000, boot_sound.stat().st_size)
        boot_sound_bytes = boot_sound.read_bytes()
        self.assertEqual(0, len(boot_sound_bytes) % 2)
        self.assertNotEqual(b"RIFF", boot_sound_bytes[:4])

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

    def test_compile_only_packager_injects_hardware_entrypoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_root = tmp_path / "source"
            esp_source = source_root / "esp_idf_demo"
            (esp_source / "main").mkdir(parents=True)
            (esp_source / "spiffs").mkdir()
            (esp_source / "build").mkdir()
            (esp_source / "managed_components").mkdir()
            (esp_source / "main" / "main.c").write_text("int main(void) { return 0; }\n", encoding="utf-8")
            (esp_source / "CMakeLists.txt").write_text("project(esp_idf_demo)\n", encoding="utf-8")
            (esp_source / "build" / "stale.txt").write_text("no\n", encoding="utf-8")
            (esp_source / "managed_components" / "stale.txt").write_text("no\n", encoding="utf-8")
            (esp_source / ".env").write_text("SECRET=1\n", encoding="utf-8")

            output = tmp_path / "esp_compile_only_v37_p3d_002_20260520.tar.gz"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "package_esp_compile_only.py"),
                    "--source",
                    str(source_root),
                    "--output",
                    str(output),
                    "--project-version",
                    "v37-p3d-canary",
                    "--device-id",
                    "miaoban-v1p2-002",
                    "--default-port",
                    "COM3",
                ],
                check=True,
                text=True,
                capture_output=True,
            )

            self.assertIn("sha256=", result.stdout)
            with tarfile.open(output, "r:gz") as archive:
                names = set(archive.getnames())
                ps1 = archive.extractfile("esp_idf_demo/build_flash_p3d_002.ps1")
                cmd = archive.extractfile("esp_idf_demo/build_flash_p3d_002.cmd")
                build_info = archive.extractfile("esp_idf_demo/BUILD_INFO.txt")
                assert ps1 is not None
                assert cmd is not None
                assert build_info is not None
                ps1_text = ps1.read().decode("utf-8")
                cmd_text = cmd.read().decode("utf-8")
                build_info_text = build_info.read().decode("utf-8")

            self.assertIn("esp_idf_demo/main/main.c", names)
            self.assertIn("esp_idf_demo/build_flash_p3d_002.sh", names)
            self.assertIn("esp_idf_demo/build_flash_p3d_002.ps1", names)
            self.assertIn("esp_idf_demo/build_flash_p3d_002.cmd", names)
            self.assertIn("esp_idf_demo/BUILD_INFO.txt", names)
            self.assertNotIn("esp_idf_demo/build/stale.txt", names)
            self.assertNotIn("esp_idf_demo/managed_components/stale.txt", names)
            self.assertNotIn("esp_idf_demo/.env", names)
            self.assertIn('$ProjectVer = "v37-p3d-canary"', ps1_text)
            self.assertIn("function Invoke-Idf", ps1_text)
            self.assertIn("python $idfCommand.Source @args", ps1_text)
            self.assertIn('Invoke-Idf -D "PROJECT_VER=$ProjectVer" build', ps1_text)
            self.assertIn('throw "idf.py failed with exit code $LASTEXITCODE"', ps1_text)
            self.assertIn("Wrong project_version", ps1_text)
            self.assertIn("build_flash_p3d_002.ps1", cmd_text)
            self.assertIn("App version:      v37-p3d-canary", build_info_text)
            self.assertIn("app_version=v37-p3d-canary", build_info_text)

    def test_compile_only_packager_preserves_managed_component_checksum_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_root = tmp_path / "source"
            esp_source = source_root / "esp_idf_demo"
            cjson_dir = esp_source / "managed_components" / "espressif__cjson" / "cJSON"
            lvgl_dir = (
                esp_source
                / "managed_components"
                / "lvgl__lvgl"
                / "tests"
                / "test_images"
                / "stride_align64"
                / "LZ4"
            )
            cjson_dir.mkdir(parents=True)
            lvgl_dir.mkdir(parents=True)
            (esp_source / "main").mkdir(parents=True)
            (esp_source / "main" / "main.c").write_text("int main(void) { return 0; }\n", encoding="utf-8")
            (esp_source / "CMakeLists.txt").write_text("project(esp_idf_demo)\n", encoding="utf-8")
            (cjson_dir / ".git").write_text("gitdir: ../.git/modules/cJSON\n", encoding="utf-8")
            (lvgl_dir / "test_A1.bin").write_bytes(b"checksum fixture")

            output = tmp_path / "esp_compile_only_with_managed.tar.gz"
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "package_esp_compile_only.py"),
                    "--source",
                    str(source_root),
                    "--output",
                    str(output),
                    "--project-version",
                    "v37-p3d-canary",
                    "--include-managed-components",
                ],
                check=True,
                text=True,
                capture_output=True,
            )

            with tarfile.open(output, "r:gz") as archive:
                names = set(archive.getnames())

            self.assertIn("esp_idf_demo/managed_components/espressif__cjson/cJSON/.git", names)
            self.assertIn(
                "esp_idf_demo/managed_components/lvgl__lvgl/tests/test_images/stride_align64/LZ4/test_A1.bin",
                names,
            )

    def test_realtime_intro_config_is_explicit(self) -> None:
        config = (ESP_DIR / "main" / "config.h").read_text(encoding="utf-8")

        self.assertIn("DEMO_REALTIME_INTRO_ENABLED", config)
        self.assertEqual("0", _read_macro_value(config, "DEMO_REALTIME_INTRO_ENABLED"))
        self.assertIn("DEMO_REALTIME_INTRO_PATH", config)
        self.assertIn("DEMO_REALTIME_INTRO_AUDIO_PARALLEL_ENABLED", config)
        self.assertIn("DEMO_REALTIME_AUDIO_PARALLEL_TASK_STACK_SIZE", config)
        self.assertIn("DEMO_REALTIME_AUDIO_GATE_WAIT_TIMEOUT_MS", config)

    def test_boot_sound_config_is_explicit_and_enabled_by_default(self) -> None:
        config = (ESP_DIR / "main" / "config.h").read_text(encoding="utf-8")

        self.assertIn("DEMO_BOOT_SOUND_ENABLED", config)
        self.assertEqual("1", _read_macro_value(config, "DEMO_BOOT_SOUND_ENABLED"))
        self.assertIn("DEMO_BOOT_SOUND_EMBEDDED_ENABLED", config)
        self.assertEqual("1", _read_macro_value(config, "DEMO_BOOT_SOUND_EMBEDDED_ENABLED"))
        self.assertIn("DEMO_BOOT_SOUND_PATH", config)
        self.assertEqual('"/spiffs/intro_1.pcm"', _read_macro_value(config, "DEMO_BOOT_SOUND_PATH"))
        self.assertIn("DEMO_BOOT_SOUND_MAX_BYTES", config)
        self.assertEqual("(64 * 1024)", _read_macro_value(config, "DEMO_BOOT_SOUND_MAX_BYTES"))

    def test_boot_sound_is_embedded_for_app_only_ota(self) -> None:
        main_cmake = (ESP_DIR / "main" / "CMakeLists.txt").read_text(encoding="utf-8")
        audio_header = (ESP_DIR / "main" / "audio_out.h").read_text(encoding="utf-8")
        audio_source = (ESP_DIR / "main" / "audio_out.c").read_text(encoding="utf-8")
        main_source = (ESP_DIR / "main" / "main.c").read_text(encoding="utf-8")
        prompt_source = (ESP_DIR / "main" / "prompt_arbiter.c").read_text(encoding="utf-8")

        self.assertIn('target_add_binary_data(${COMPONENT_LIB} "../spiffs/boot_amitabha_1.pcm" BINARY)', main_cmake)
        self.assertIn("audio_out_play_pcm_buffer", audio_header)
        self.assertIn("audio_out_play_pcm_buffer", audio_source)
        self.assertIn("_binary_intro_1_pcm_start", main_source)
        self.assertIn("_binary_intro_1_pcm_end", main_source)
        self.assertIn("_binary_boot_amitabha_1_pcm_start", prompt_source)
        self.assertIn("audio_out_play_pcm_buffer(boot_sound_start", main_source)
        self.assertNotIn("audio_out_play_pcm_file(DEMO_BOOT_SOUND_PATH", main_source)

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

        self.assertIn("static bool app_needs_spiffs_audio(void)", main_source)
        self.assertIn("DEMO_REALTIME_INTRO_ENABLED && DEMO_REALTIME_INTRO_PATH[0] != '\\0'", main_source)
        self.assertIn("DEMO_RECORD_PROMPT_ENABLED && DEMO_RECORD_PROMPT_PATH[0] != '\\0'", main_source)
        self.assertIn("if (app_needs_spiffs_audio()) {\n        (void)app_mount_spiffs();", main_source)
        self.assertNotIn("if (DEMO_REALTIME_INTRO_ENABLED) {\n        (void)app_mount_spiffs();", main_source)

    def test_spiffs_mount_includes_retry_prompts_without_boot_sound(self) -> None:
        main_source = (ESP_DIR / "main" / "main.c").read_text(encoding="utf-8")

        self.assertIn("static bool app_needs_spiffs_audio(void)", main_source)
        self.assertIn("DEMO_RECORD_RETRY_REARM_PROMPT_PATH[0] != '\\0'", main_source)
        self.assertIn("DEMO_RECORD_RETRY_TIMEOUT_PROMPT_PATH[0] != '\\0'", main_source)
        self.assertIn("DEMO_RECORD_RETRY_ERROR_PROMPT_PATH[0] != '\\0'", main_source)
        self.assertIn("if (app_needs_spiffs_audio()) {\n        (void)app_mount_spiffs();", main_source)
        self.assertNotIn("if (DEMO_BOOT_SOUND_ENABLED ||", main_source)

    def test_boot_sound_playback_is_embedded_early_and_nonfatal(self) -> None:
        main_source = (ESP_DIR / "main" / "main.c").read_text(encoding="utf-8")

        self.assertIn("if (app_needs_spiffs_audio()) {\n        (void)app_mount_spiffs();", main_source)
        self.assertIn("static void app_play_boot_sound(void)", main_source)
        self.assertIn("stage=boot_sound event=start", main_source)
        self.assertIn("stage=boot_sound event=done", main_source)
        self.assertIn("stage=boot_sound event=failed", main_source)
        self.assertIn("audio_out_play_pcm_buffer(boot_sound_start", main_source)
        self.assertNotIn("audio_out_play_pcm_file(DEMO_BOOT_SOUND_PATH", main_source)

        boot_sound_call = main_source.index("app_play_boot_sound();")
        validate_config = main_source.index("app_validate_runtime_config()")
        network_start = main_source.index("app_network_start()")
        self.assertLess(boot_sound_call, validate_config)
        self.assertLess(boot_sound_call, network_start)

    def test_wifi_board_lite_uses_esp_wifi_connect_hotspot_provisioning(self) -> None:
        manifest = (ESP_DIR / "main" / "idf_component.yml").read_text(encoding="utf-8")
        cmake = (ESP_DIR / "main" / "CMakeLists.txt").read_text(encoding="utf-8")
        network_header = (ESP_DIR / "main" / "app_network.h").read_text(encoding="utf-8")
        network_source = (ESP_DIR / "main" / "app_network.cc").read_text(encoding="utf-8")
        main_source = (ESP_DIR / "main" / "main.c").read_text(encoding="utf-8")

        self.assertNotIn("78/esp-wifi-connect", manifest)
        self.assertTrue((ESP_DIR / "components" / "esp-wifi-connect").is_dir())
        self.assertIn('"app_network.cc"', cmake)
        self.assertTrue((ESP_DIR / "main" / "app_network.h").exists())

        for symbol in (
            "app_network_start",
            "app_network_is_connected",
            "app_network_enter_config_mode",
            "app_network_reconfigure_blocking",
            "app_network_get_ssid",
        ):
            self.assertIn(symbol, network_header)
            self.assertIn(symbol, network_source)

        self.assertIn('extern "C"', network_header)
        self.assertIn("WifiManager::GetInstance()", network_source)
        self.assertIn("WifiCredentialStore::GetInstance()", network_source)
        self.assertNotIn("SsidManager::GetInstance()", network_source)
        self.assertIn("StartStation()", network_source)
        self.assertIn("StartConfigAp()", network_source)
        self.assertIn('ssid_prefix = "GreenMotive"', network_source)
        self.assertIn("wifi_saved_credentials_found", network_source)
        self.assertIn("wifi_no_saved_credentials", network_source)
        self.assertIn("wifi_config_mode_enter", network_source)
        self.assertIn("wifi_config_ap_ssid", network_source)
        self.assertIn("wifi_config_url=http://192.168.4.1", network_source)
        self.assertIn("wifi_config_mode_exit", network_source)

        self.assertIn("app_network_start()", main_source)
        self.assertIn("app_network_is_connected()", main_source)
        self.assertNotIn("DEMO_WIFI_SSID is empty", main_source)
        self.assertNotIn("Wi-Fi initialization failed; stopping demo", main_source)

    def test_wifi_credentials_are_versioned_bounded_and_owned_by_the_app(self) -> None:
        component = ESP_DIR / "components" / "esp-wifi-connect"
        upstream = (component / "UPSTREAM.md").read_text(encoding="utf-8")
        manifest = (ESP_DIR / "main" / "idf_component.yml").read_text(encoding="utf-8")
        header = (ESP_DIR / "main" / "wifi_credential_store.h").read_text(encoding="utf-8")
        source = (ESP_DIR / "main" / "wifi_credential_store.cc").read_text(encoding="utf-8")
        manager = (component / "ssid_manager.cc").read_text(encoding="utf-8")

        self.assertIn("78/esp-wifi-connect", upstream)
        self.assertIn("3.1.4", upstream)
        self.assertIn("096f3db8146eebc784d5b7dda61af361e405bf9f72771561c78779daedbdbfb7", upstream)
        self.assertNotIn("78/esp-wifi-connect", manifest)
        self.assertIn("MAX_WIFI_CREDENTIALS = 5", header)
        for symbol in ("LoadAndMigrate", "List", "Upsert", "MarkSuccessful"):
            self.assertIn(symbol, header)
            self.assertIn(symbol, source)

        self.assertIn('nvs_open("wifi", NVS_READONLY', source)
        self.assertNotIn('nvs_open("wifi", NVS_READWRITE', source)
        self.assertIn("WriteSlot", source)
        self.assertIn("ReadSlot", source)
        self.assertIn("SetActiveSlot", source)
        self.assertLess(source.index("WriteSlot(inactive_slot"), source.index("ReadSlot(inactive_slot"))
        self.assertLess(source.index("ReadSlot(inactive_slot"), source.index("SetActiveSlot(inactive_slot"))
        self.assertNotIn("nvs_open", manager)
        self.assertIn("SetChangeCallback", manager)

    def test_v7_wifi_and_prompt_policy_contract(self) -> None:
        config = (ESP_DIR / "main" / "config.h").read_text(encoding="utf-8")
        network = (ESP_DIR / "main" / "app_network.cc").read_text(encoding="utf-8")
        policy = (ESP_DIR / "main" / "wifi_connection_policy.cc").read_text(encoding="utf-8")
        prompt_header = (ESP_DIR / "main" / "prompt_arbiter.h").read_text(encoding="utf-8")
        prompt_source = (ESP_DIR / "main" / "prompt_arbiter.c").read_text(encoding="utf-8")
        cmake = (ESP_DIR / "main" / "CMakeLists.txt").read_text(encoding="utf-8")

        self.assertIn("DEMO_WIFI_BOOT_DEADLINE_MS 8000", config)
        self.assertIn("DEMO_WIFI_CANDIDATE_TIMEOUT_MS 3000", config)
        self.assertIn("DEMO_WIFI_RUNTIME_PROMPT_MS 12000", config)
        self.assertIn("DEMO_WIFI_RUNTIME_RETRY_MS {15000, 30000, 60000}", config)
        self.assertIn("DEMO_WIFI_RECONFIG_TIMEOUT_MS (5 * 60 * 1000)", config)
        self.assertIn("DEMO_WIFI_SMARTCONFIG_ENABLED 0", config)
        self.assertIn('config.ssid_prefix = "GreenMotive"', network)
        self.assertIn("wifi_policy_rank_scan", policy)
        self.assertIn("wifi_policy_candidate_deadline", policy)
        self.assertIn("wifi_policy_next_rescan_deadline", policy)
        self.assertIn("esp_wifi_disconnect", network)
        self.assertIn("prompt_arbiter_submit(PROMPT_NETWORK_REQUIRED", network)
        self.assertNotIn("audio_out_play", network)

        for declaration in (
            "PROMPT_BOOT_BELL = 10",
            "PROMPT_NETWORK_CONNECTED = 20",
            "PROMPT_CONVERSATION_DONE = 30",
            "PROMPT_SPEAK = 40",
            "PROMPT_NETWORK_REQUIRED = 50",
            "PROMPT_TECHNICAL_ERROR = 60",
            "prompt_arbiter_submit",
            "prompt_arbiter_wait_key",
            "prompt_arbiter_set_conversation_active",
        ):
            self.assertIn(declaration, prompt_header)
        self.assertIn("prompt_arbiter_owner_task", prompt_source)
        self.assertIn("s_playing_key", prompt_source)
        self.assertIn("prompt_arbiter_network_prompt_is_relevant", prompt_source)
        self.assertIn(
            "case PROMPT_TECHNICAL_ERROR:\n"
            "        start = prompt_conversation_done_start;\n"
            "        end = prompt_conversation_done_end;",
            prompt_source,
        )
        for asset in (
            "network_required_1.pcm",
            "conversation_done_1.pcm",
            "intro_1.pcm",
            "boot_amitabha_1.pcm",
        ):
            self.assertIn(f'../spiffs/{asset}', cmake)

    def test_v7_embedded_prompt_assets_have_locked_pcm_hashes(self) -> None:
        expected = {
            "intro_1.pcm": (48_000, "b9cbe3581350a0a168b57d3c2b6c887099ae11c4b070fb741368cc5eb78cb424"),
            "network_required_1.pcm": (61_440, "672cf8483a72cb39b60fbe385725ff1a06b81d63ae0da7e818b3821268c53cd8"),
            "conversation_done_1.pcm": (46_080, "135a2c19a79f4cb9b89b7d962e439a4609ca2be275195ce45f19edbd4973aef0"),
        }
        for name, (size, digest) in expected.items():
            payload = (ESP_DIR / "spiffs" / name).read_bytes()
            self.assertEqual(size, len(payload))
            self.assertGreater(len(payload), 0)
            self.assertEqual(0, len(payload) % 2)
            self.assertNotEqual(b"RIFF", payload[:4])
            self.assertEqual(digest, hashlib.sha256(payload).hexdigest())

    def test_v7_wifi_review_regressions_are_guarded(self) -> None:
        component = ESP_DIR / "components" / "esp-wifi-connect"
        station = (component / "wifi_station.cc").read_text(encoding="utf-8")
        manager = (component / "wifi_manager.cc").read_text(encoding="utf-8")
        portal = (component / "wifi_configuration_ap.cc").read_text(encoding="utf-8")
        ssid_header = (component / "include" / "ssid_manager.h").read_text(encoding="utf-8")
        credential_store = (ESP_DIR / "main" / "wifi_credential_store.cc").read_text(encoding="utf-8")
        network = (ESP_DIR / "main" / "app_network.cc").read_text(encoding="utf-8")
        main_source = (ESP_DIR / "main" / "main.c").read_text(encoding="utf-8")

        self.assertIn("wifi_policy_rank_scan", station)
        self.assertIn("wifi_policy_next_rescan_deadline", station)
        self.assertIn("on_no_candidates_", station)
        self.assertNotIn("strcpy((char *)wifi_config.sta", station)
        self.assertNotIn("strlcpy((char *)wifi_config.sta", portal)
        self.assertNotIn("WIFI_EVENT_STA_CONNECTED) {\n        xEventGroupSetBits", portal)
        self.assertNotIn("Password: %s", portal)
        self.assertIn("bool Save(", (component / "include" / "wifi_configuration_ap.h").read_text(encoding="utf-8"))
        self.assertIn("std::function<bool(", ssid_header)
        self.assertIn("const auto previous = credentials_", credential_store)
        self.assertIn("APP_NETWORK_NO_CANDIDATES_BIT", network)
        self.assertEqual(1, network.count('xTaskCreate(app_network_runtime_outage_task'))
        self.assertIn("portMUX_TYPE s_outage_lock", network)
        self.assertIn("prompt_arbiter_set_conversation_active", main_source)
        self.assertIn("_binary_intro_1_pcm_start", main_source)

        for method in ("StartStation", "StopStation", "StartConfigAp", "StopConfigAp"):
            body = manager.split(f"void WifiManager::{method}()", 1)[1].split("\n}", 1)[0]
            self.assertIn("lock.unlock()", body)

    def test_v7_voice_prompts_are_audible_and_not_clipped(self) -> None:
        minimum_sizes = {
            "network_required_1.pcm": 20_000,
            "conversation_done_1.pcm": 12_000,
        }
        for name, minimum_size in minimum_sizes.items():
            payload = (ESP_DIR / "spiffs" / name).read_bytes()
            samples = array("h")
            samples.frombytes(payload)
            peak = max(abs(value) for value in samples)
            self.assertGreaterEqual(len(payload), minimum_size)
            self.assertGreaterEqual(peak, 7_000)
            self.assertLess(peak, 30_000)

    def test_wifi_board_lite_raises_event_task_stack_for_esp_wifi_connect_callbacks(self) -> None:
        sdkconfig_defaults = (ESP_DIR / "sdkconfig.defaults.vocat_lowcost_16m8m").read_text(encoding="utf-8")
        package_script = (ROOT / "scripts" / "package_esp_compile_only.py").read_text(encoding="utf-8")

        self.assertIn("CONFIG_ESP_SYSTEM_EVENT_TASK_STACK_SIZE=4096", sdkconfig_defaults)
        self.assertIn("CONFIG_ESP_SYSTEM_EVENT_TASK_STACK_SIZE=4096", package_script)

    def test_wifi_board_lite_keeps_short_press_trigger_and_passwords_out_of_source(self) -> None:
        config = (ESP_DIR / "main" / "config.h").read_text(encoding="utf-8")
        trigger_source = (ESP_DIR / "main" / "trigger_input.c").read_text(encoding="utf-8")
        trigger_header = (ESP_DIR / "main" / "trigger_input.h").read_text(encoding="utf-8")
        network_source = (ESP_DIR / "main" / "app_network.cc").read_text(encoding="utf-8")
        network_header = (ESP_DIR / "main" / "app_network.h").read_text(encoding="utf-8")
        main_source = (ESP_DIR / "main" / "main.c").read_text(encoding="utf-8")
        project_sources = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                ESP_DIR / "main" / "config.h",
                ESP_DIR / "main" / "main.c",
                ESP_DIR / "main" / "app_network.h",
                ESP_DIR / "main" / "app_network.cc",
            )
        )

        self.assertIn("#define DEMO_TRIGGER_SOURCE DEMO_TRIGGER_SOURCE_BUTTON_AND_WAKE_WORD", config)
        self.assertIn("#define DEMO_BUTTON_GPIO         GPIO_NUM_7", config)
        self.assertIn("#define DEMO_WIFI_RECONFIG_GPIO  GPIO_NUM_0", config)
        self.assertIn("#define DEMO_WIFI_RECONFIG_LONG_PRESS_MS 5000", config)
        self.assertIn("TRIGGER_EVENT_WIFI_RECONFIG", trigger_header)
        self.assertIn("button_press_in_progress", trigger_header)
        self.assertIn("wifi_reconfig_press_in_progress", trigger_header)
        self.assertIn("wifi_reconfig_long_press_reported", trigger_header)
        self.assertIn("Button trigger event", trigger_source)
        self.assertIn("boot_key_long_press_wifi_reconfig", trigger_source)
        self.assertIn("DEMO_WIFI_RECONFIG_GPIO", trigger_source)
        self.assertIn("pdMS_TO_TICKS(DEMO_WIFI_RECONFIG_LONG_PRESS_MS)", trigger_source)
        self.assertIn("wifi_reconfig_long_press_reported = true", trigger_source)
        self.assertNotIn("Button long press Wi-Fi reconfig event", trigger_source)
        self.assertIn("app_network_reconfigure_blocking", network_header)
        self.assertIn("app_network_reconfigure_blocking", network_source)
        self.assertIn("APP_NETWORK_CONFIG_EXIT_BIT", network_source)
        self.assertIn("wifi_reconfig_requested", main_source)
        self.assertIn("app_network_reconfigure_blocking()", main_source)
        self.assertIn("DEMO_WIFI_PASSWORD[0] != '\\0'", network_source)

        for forbidden in (
            "wifi_password=",
            "password=%s",
            "DEMO_WIFI_PASSWORD \"",
            "DEMO_WIFI_PASSWORD       \"1",
            "DEMO_WIFI_PASSWORD       \"p",
            ):
            self.assertNotIn(forbidden, project_sources)

    def test_wakenet_spike_combines_xiaoming_wake_word_with_gpio7_button(self) -> None:
        manifest = (ESP_DIR / "main" / "idf_component.yml").read_text(encoding="utf-8")
        cmake = (ESP_DIR / "main" / "CMakeLists.txt").read_text(encoding="utf-8")
        config = (ESP_DIR / "main" / "config.h").read_text(encoding="utf-8")
        trigger_header = (ESP_DIR / "main" / "trigger_input.h").read_text(encoding="utf-8")
        trigger_source = (ESP_DIR / "main" / "trigger_input.c").read_text(encoding="utf-8")
        wake_header = (ESP_DIR / "main" / "wake_word_service.h").read_text(encoding="utf-8")
        wake_source = (ESP_DIR / "main" / "wake_word_service.c").read_text(encoding="utf-8")
        main_source = (ESP_DIR / "main" / "main.c").read_text(encoding="utf-8")
        lowcost_profile = (ESP_DIR / "sdkconfig.defaults.vocat_lowcost_16m8m").read_text(encoding="utf-8")
        partitions = (ESP_DIR / "partitions.csv").read_text(encoding="utf-8").replace(" ", "")

        self.assertIn("espressif/esp-sr", manifest)
        self.assertIn('"wake_word_service.c"', cmake)
        self.assertIn("espressif__esp-sr", cmake)

        self.assertIn("DEMO_TRIGGER_SOURCE_BUTTON_AND_WAKE_WORD", config)
        self.assertIn("#define DEMO_TRIGGER_SOURCE DEMO_TRIGGER_SOURCE_BUTTON_AND_WAKE_WORD", config)
        self.assertIn("#define DEMO_BUTTON_GPIO         GPIO_NUM_7", config)
        self.assertIn("#define DEMO_WIFI_RECONFIG_GPIO  GPIO_NUM_0", config)
        self.assertIn("#define DEMO_WAKE_WORD_ENABLED 1", config)
        self.assertIn('#define DEMO_WAKE_WORD_MODEL_NAME "wn9_xiaomingtongxue_tts2"', config)
        self.assertIn("CONFIG_SR_WN_WN9_XIAOMINGTONGXUE_TTS2=y", lowcost_profile)

        self.assertIn("Button trigger event", trigger_source)
        self.assertIn("GPIO7 voice/wake trigger", trigger_source)
        self.assertIn("GPIO0 boot key Wi-Fi reconfig long press", trigger_source)
        self.assertIn("wake_word_service_start", trigger_source)
        self.assertIn("wake_word_service_poll", trigger_source)
        self.assertIn("button fallback", trigger_source)
        self.assertIn("TRIGGER_EVENT_WAKE_WORD", trigger_header)
        self.assertIn("trigger_input_set_accepting", trigger_header)
        self.assertIn("wake_word_service_set_accepting", wake_header)

        for marker in (
            "wake_word_enabled",
            "wake_word_model",
            "wake_word_button_fallback",
        ):
            self.assertIn(marker, main_source)
        self.assertIn("wn9_xiaomingtongxue_tts2", wake_header)
        self.assertIn("wn9_xiaomingtongxue_tts2", wake_source)
        self.assertIn("esp_srmodel_init(\"model\")", wake_source)
        self.assertIn("wake_word_service_stop", wake_source)
        self.assertIn("wake_word_detected", wake_source)

        self.assertIn("ota_0,app,ota_0,0x20000,3M", partitions)
        self.assertIn("ota_1,app,ota_1,,3M", partitions)
        self.assertIn("storage,data,spiffs,,4M", partitions)
        self.assertIn("model,data,,,1M", partitions)
        self.assertIn("CONFIG_MODEL_IN_FLASH=y", lowcost_profile)

        untouched_release_and_server_paths = (
            ROOT / "src" / "api" / "realtime.py",
            ROOT / "src" / "providers" / "realtime_asr.py",
            ROOT / "src" / "settings.py",
            ROOT / "scripts" / "ota_release_create.py",
            ROOT / "scripts" / "build_esp_p3d_canary_artifact.sh",
        )
        for path in untouched_release_and_server_paths:
            self.assertNotIn("wn9_xiaomingtongxue_tts2", path.read_text(encoding="utf-8"))

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

    def test_app_main_only_starts_runtime_task_and_deletes_itself(self) -> None:
        config = (ESP_DIR / "main" / "config.h").read_text(encoding="utf-8")
        main_source = (ESP_DIR / "main" / "main.c").read_text(encoding="utf-8")
        app_main_source = main_source.split("void app_main(void)", 1)[1]
        app_main_body = app_main_source.split("static void app_runtime_task", 1)[0]

        self.assertIn("DEMO_APP_RUNTIME_TASK_STACK_SIZE", config)
        self.assertIn("app_runtime_task", main_source)
        self.assertIn("xTaskCreate(app_runtime_task", app_main_body)
        self.assertIn("DEMO_APP_RUNTIME_TASK_STACK_SIZE", app_main_body)
        self.assertIn("vTaskDelete(NULL)", app_main_body)

        for forbidden in (
            "app_wifi_connect(",
            "app_mount_spiffs(",
            "app_poll_ota_manifest_dry_run_if_due(",
            "trigger_input_poll(",
            "cloud_client_submit_ota_report(",
            "while (true)",
        ):
            self.assertNotIn(forbidden, app_main_body)

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

    def test_ota_p3d_app_validation_runs_in_dedicated_task(self) -> None:
        main_source = (ESP_DIR / "main" / "main.c").read_text(encoding="utf-8")
        app_main_source = main_source.split("void app_main(void)", 1)[1]

        self.assertIn("app_ota_rollback_validation_task", main_source)
        self.assertIn("xTaskCreate(app_ota_rollback_validation_task", main_source)
        self.assertNotIn("cloud_client_submit_ota_report", app_main_source)
        self.assertNotIn("app_submit_ota_app_validated_report", app_main_source)

    def test_ota_p3d_business_hang_edge_case_has_timeout_without_mark_valid(self) -> None:
        main_source = (ESP_DIR / "main" / "main.c").read_text(encoding="utf-8")

        self.assertIn("app_ota_rollback_validation_timeout_task", main_source)
        self.assertIn("stage=ota_app_validation event=timeout", main_source)
        self.assertIn("app_validation_timeout", main_source)
        self.assertIn("DEMO_OTA_ROLLBACK_VALIDATION_TIMEOUT_MS", main_source)
        self.assertIn("esp_restart()", main_source)
        timeout_pos = main_source.index("stage=ota_app_validation event=timeout")
        mark_valid_pos = main_source.index("esp_ota_mark_app_valid_cancel_rollback")
        self.assertLess(mark_valid_pos, timeout_pos)

    def test_ota_pending_watchdog_starts_before_blocking_network_startup(self) -> None:
        main_source = (ESP_DIR / "main" / "main.c").read_text(encoding="utf-8")
        runtime = main_source.rsplit("static void app_runtime_task(void *arg)", 1)[1]
        prepare_pos = runtime.index("app_ota_rollback_prepare_before_network()")
        network_pos = runtime.index("app_network_start()")

        self.assertLess(prepare_pos, network_pos)
        self.assertIn("app_ota_p3c_load_pending", main_source)
        self.assertIn("xTaskCreate(app_ota_rollback_validation_timeout_task", main_source)
        self.assertIn("s_ota_credential_migration_ready", main_source)
        self.assertIn("s_ota_audio_ready", main_source)
        self.assertIn("audio_in_probe()", main_source)
        self.assertIn("app_network_is_connected()", main_source)
        business_ready = main_source.split(
            "static void app_ota_rollback_note_business_ready", 1
        )[1].split("static void app_ota_rollback_validation_task", 1)[0]
        self.assertNotIn("s_ota_post_reboot_report_done", business_ready)
        self.assertLess(
            runtime.index("s_ota_credential_migration_ready = true"),
            runtime.index("s_ota_audio_ready = true"),
        )

    def test_ota_validation_report_failure_cannot_rearm_local_rollback(self) -> None:
        main_source = (ESP_DIR / "main" / "main.c").read_text(encoding="utf-8")
        validation = main_source.rsplit(
            "static void app_ota_rollback_validation_task(void *arg)", 1
        )[1].split("static void app_ota_rollback_validation_timeout_task", 1)[0]

        mark_pos = validation.index("esp_ota_mark_app_valid_cancel_rollback()")
        clear_local_pos = validation.index("s_ota_rollback_validation_pending = false")
        clear_pending_pos = validation.index("app_ota_p3c_clear_pending()")
        report_pos = validation.index("app_submit_ota_app_validated_report")
        self.assertLess(mark_pos, clear_local_pos)
        self.assertLess(clear_local_pos, report_pos)
        self.assertLess(clear_pending_pos, report_pos)

        timeout = main_source.rsplit(
            "static void app_ota_rollback_validation_timeout_task(void *arg)", 1
        )[1].split("#endif", 1)[0]
        self.assertIn("if (s_ota_rollback_validation_pending)", timeout)
        self.assertNotIn("!s_ota_rollback_business_ready", timeout)

    def test_ota_p3d_persists_breadcrumb_and_reports_rollback_recovered(self) -> None:
        main_source = (ESP_DIR / "main" / "main.c").read_text(encoding="utf-8")
        cloud_header = (ESP_DIR / "main" / "cloud_client.h").read_text(encoding="utf-8")
        cloud_source = (ESP_DIR / "main" / "cloud_client.c").read_text(encoding="utf-8")

        self.assertIn("APP_OTA_P3C_KEY_LAST_STAGE", main_source)
        self.assertIn("app_ota_p3c_store_last_stage", main_source)
        self.assertIn("boot_switch_reboot_scheduled", main_source)
        self.assertIn("post_reboot_confirm_reported", main_source)
        self.assertIn("app_validation_waiting", main_source)
        self.assertIn("stage=ota_rollback event=recovered", main_source)
        self.assertIn("previous_partition", cloud_header)
        self.assertIn("last_stage", cloud_header)
        self.assertIn('"previous_partition"', cloud_source)
        self.assertIn('"last_stage"', cloud_source)

    def test_p3d_canary_build_script_enables_rollback_without_password(self) -> None:
        script = (ROOT / "scripts" / "build_esp_p3d_canary_artifact.sh").read_text(encoding="utf-8")

        self.assertIn("PROJECT_VER=${PROJECT_VER:-v37-p3d-canary}", script)
        self.assertIn("DEMO_OTA_BOOT_SWITCH_ENABLED 1", script)
        self.assertIn("DEMO_OTA_ROLLBACK_VALIDATION_ENABLED 1", script)
        self.assertIn("CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y", script)
        self.assertIn("# CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE is not set", script)
        self.assertIn("SDKCONFIG=", script)
        self.assertIn("rollback config was not enabled", script)
        self.assertIn("CANARY_DEVICE_ID=${CANARY_DEVICE_ID:-miaoban-v1p2-002}", script)
        self.assertIn("CANARY_TRIGGER_SOURCE=\"${CANARY_TRIGGER_SOURCE:-button}\"", script)
        self.assertIn("CANARY_BUTTON_GPIO=\"${CANARY_BUTTON_GPIO:-7}\"", script)
        self.assertIn("BUTTON_AND_WAKE_WORD", script)
        self.assertIn("DEMO_TRIGGER_SOURCE DEMO_TRIGGER_SOURCE_${CANARY_TRIGGER_SOURCE_UPPER}", script)
        self.assertIn("DEMO_BUTTON_GPIO         GPIO_NUM_${CANARY_BUTTON_GPIO}", script)
        self.assertNotIn("DEMO_WIFI_PASSWORD", script)

    def test_ota_canary_app_only_scripts_keep_embedded_boot_sound_enabled(self) -> None:
        for script_path in (
            ROOT / "scripts" / "build_esp_p3c_canary_artifact.sh",
            ROOT / "scripts" / "build_esp_p3d_canary_artifact.sh",
        ):
            script = script_path.read_text(encoding="utf-8")

            self.assertNotIn("OTA canary app artifact does not update SPIFFS", script)
            self.assertNotIn("DEMO_BOOT_SOUND_ENABLED 0", script)

    def test_boot_sound_plan_uses_reproducible_secret_scan(self) -> None:
        plan = (
            ROOT / "docs" / "superpowers" / "plans" / "2026-07-09-v6-boot-amitabha-sound.md"
        ).read_text(encoding="utf-8")

        self.assertNotIn("gitleaks detect --source . --no-git --redact --verbose", plan)
        self.assertIn("gitleaks dir esp_idf_demo/main/config.h", plan)
        self.assertIn("pre-existing", plan)

    def test_compile_only_package_injects_p3d_canary_config_without_password(self) -> None:
        script = (ROOT / "scripts" / "package_esp_compile_only.py").read_text(encoding="utf-8")

        self.assertIn('--wifi-ssid", default="GMT-G60"', script)
        self.assertIn('--server-base-url", default="http://106.54.240.51"', script)
        self.assertIn("DEMO_WIFI_SSID", script)
        self.assertIn("DEMO_SERVER_BASE_URL", script)
        self.assertIn("DEMO_DEVICE_ID", script)
        self.assertIn("DEMO_OTA_BOOT_SWITCH_ENABLED 1", script)
        self.assertIn("DEMO_OTA_ROLLBACK_VALIDATION_ENABLED 1", script)
        self.assertIn("CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y", script)
        self.assertIn('"button_and_wake_word": "BUTTON_AND_WAKE_WORD"', script)
        self.assertIn("--trigger-source", script)
        self.assertIn("--include-managed-components", script)
        self.assertNotIn("DEMO_WIFI_PASSWORD", script)

    def test_empty_wifi_config_enters_hotspot_provisioning_instead_of_stopping(self) -> None:
        main_source = (ESP_DIR / "main" / "main.c").read_text(encoding="utf-8")
        network_source = (ESP_DIR / "main" / "app_network.cc").read_text(encoding="utf-8")

        self.assertNotIn("DEMO_WIFI_SSID is empty", main_source)
        self.assertNotIn("Wi-Fi initialization failed; stopping demo", main_source)
        self.assertIn("wifi_no_saved_credentials", network_source)
        self.assertIn("app_network_enter_config_mode", network_source)
        self.assertIn("StartConfigAp()", network_source)


if __name__ == "__main__":
    unittest.main()
