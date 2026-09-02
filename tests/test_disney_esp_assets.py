from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ESP_DIR = ROOT / "esp_idf_demo"
ESP_MAIN = ROOT / "esp_idf_demo" / "main"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_voice_wake_is_the_only_conversation_trigger() -> None:
    config = _read(ESP_MAIN / "config.h")
    trigger = _read(ESP_MAIN / "trigger_input.c")
    assert "#define DEMO_TRIGGER_SOURCE DEMO_TRIGGER_SOURCE_WAKE_WORD" in config
    assert '#define DEMO_WAKE_WORD_TEXT "小明同学"' in config
    assert "trigger->initialized = true;" in trigger
    assert "trigger->configured_source == TRIGGER_EVENT_WAKE_WORD" in trigger


def test_default_build_reuses_validated_vocat_lowcost_profile() -> None:
    cmake = _read(ESP_DIR / "CMakeLists.txt")
    assert 'set(SDKCONFIG_DEFAULTS "sdkconfig.defaults;sdkconfig.defaults.vocat_lowcost_16m8m")' in cmake


def test_display_timeout_contract_is_30_and_60_seconds() -> None:
    config = _read(ESP_MAIN / "config.h")
    display = _read(ESP_MAIN / "display_state.c")
    assert "#define DEMO_DISPLAY_DIM_AFTER_MS 30000" in config
    assert "#define DEMO_DISPLAY_OFF_AFTER_MS 60000" in config
    assert "if (s_power_state == DISPLAY_POWER_OFF)" in display
    assert "display_wake source=touch" in display


def _jpeg_dimensions(jpeg: bytes) -> tuple[int, int]:
    cursor = 2
    while cursor + 8 <= len(jpeg):
        if jpeg[cursor] != 0xFF:
            cursor += 1
            continue
        marker = jpeg[cursor + 1]
        cursor += 2
        if marker in {0xD8, 0xD9}:
            continue
        segment_size = int.from_bytes(jpeg[cursor : cursor + 2], "big")
        if marker in {0xC0, 0xC1, 0xC2}:
            height = int.from_bytes(jpeg[cursor + 3 : cursor + 5], "big")
            width = int.from_bytes(jpeg[cursor + 5 : cursor + 7], "big")
            return width, height
        cursor += segment_size
    raise AssertionError("JPEG dimensions not found")


def _assert_silent_mjpeg_asset(name: str, expected_frames: int, max_bytes: int) -> None:
    asset = ESP_DIR / "spiffs" / name
    data = asset.read_bytes()
    assert data[:4] == b"RIFF"
    assert data[8:12] == b"AVI "
    assert b"MJPG" in data
    assert b"auds" not in data
    assert len(data) <= max_bytes
    assert data.count(b"\xff\xd8") == expected_frames
    assert data.count(b"\xff\xd9") == expected_frames
    first_start = data.index(b"\xff\xd8")
    first_end = data.index(b"\xff\xd9", first_start) + 2
    assert _jpeg_dimensions(data[first_start:first_end]) == (360, 360)


def test_state_ui_uses_circle_safe_silent_mjpeg_avis() -> None:
    config = _read(ESP_MAIN / "config.h")
    display = _read(ESP_MAIN / "display_state.c")
    decoder = _read(ESP_MAIN / "idle_video.c")
    cmake = _read(ESP_MAIN / "CMakeLists.txt")
    manifest = _read(ESP_MAIN / "idf_component.yml")

    _assert_silent_mjpeg_asset("idle_judy.avi", expected_frames=42, max_bytes=256 * 1024)
    _assert_silent_mjpeg_asset("listening_thinking.avi", expected_frames=28, max_bytes=192 * 1024)
    _assert_silent_mjpeg_asset("speaking_judy.avi", expected_frames=32, max_bytes=192 * 1024)

    assert '#define DEMO_IDLE_VIDEO_ENABLED 1' in config
    assert '#define DEMO_IDLE_VIDEO_PATH "/spiffs/idle_judy.avi"' in config
    assert '#define DEMO_LISTENING_THINKING_VIDEO_PATH "/spiffs/listening_thinking.avi"' in config
    assert '#define DEMO_SPEAKING_VIDEO_PATH "/spiffs/speaking_judy.avi"' in config
    assert "case DISPLAY_UI_LISTENING:\n    case DISPLAY_UI_THINKING:" in display
    assert "return DISPLAY_VIDEO_LISTENING_THINKING;" in display
    assert "case DISPLAY_UI_SPEAKING:" in display
    assert "return DISPLAY_VIDEO_SPEAKING;" in display
    assert "lv_image_set_src(s_state_image" in display
    assert "esp_jpeg_decode" in decoder
    assert "xTaskCreateWithCaps(display_state_video_task" in display
    assert "MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT" in display
    assert "heap_caps_calloc" in decoder
    assert "MALLOC_CAP_INTERNAL" not in decoder
    assert "fopen(path, \"rb\")" in decoder
    assert "fseek(video->file" in decoder
    assert "fread(buffer" in decoder
    assert "avi_data" not in decoder
    assert "idle_video_decoder_create" in decoder
    assert "idle_video_decoder_t *s_video_decoder" in display
    assert "static uint8_t *s_video_frame_buffers[2]" in display
    assert '"idle_video.c"' in cmake
    assert "espressif/esp_jpeg" in manifest
    assert 'version: "4.2.0"' in manifest
    assert 'version: "1.1.1~1"' in manifest
    assert 'version: "2.8.0~1"' in manifest


def test_display_uses_bounded_single_dma_buffer() -> None:
    config = _read(ESP_MAIN / "config.h")
    display = _read(ESP_MAIN / "display_state.c")
    assert "#define DEMO_DISPLAY_BUFFER_HEIGHT 40" in config
    assert "#define DEMO_DISPLAY_DOUBLE_BUFFER 0" in config
    assert "bsp_display_start_with_config(&display_cfg)" in display


def test_websocket_task_stack_uses_psram_for_repeat_conversations() -> None:
    websocket = _read(
        ESP_DIR
        / "components"
        / "espressif__esp_websocket_client"
        / "esp_websocket_client.c"
    )
    assert "xTaskCreatePinnedToCoreWithCaps" in websocket
    assert "MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT" in websocket
    assert "vTaskDeleteWithCaps(NULL)" in websocket
    assert "CONFIG_FREERTOS_TASK_CREATE_ALLOW_EXT_MEM" in websocket


def test_touch_is_not_routed_to_the_voice_pipeline() -> None:
    main = _read(ESP_MAIN / "main.c")
    display = _read(ESP_MAIN / "display_state.c")
    assert "display_state_notify_wake_word();" in main
    assert "lv_indev_add_event_cb(touch, display_touch_event" in display
    assert "app_start_pipeline_task" not in display


def test_runtime_uses_disney_brand_and_neutral_prompt_assets() -> None:
    network = _read(ESP_MAIN / "app_network.cc")
    conversation = _read(ESP_MAIN / "cloud_conversation.c")
    cmake = _read(ESP_MAIN / "CMakeLists.txt")
    assert 'ssid_prefix = "DisneyDemo"' in network
    assert '"DisneyDemo-%08lx-%08lx"' in conversation
    assert "network_required_1.pcm" not in cmake
    assert "conversation_done_1.pcm" not in cmake


def test_config_ap_owns_sta_netif_for_dhcp_and_serializes_transitions() -> None:
    config_ap = _read(
        ESP_DIR / "components" / "esp-wifi-connect" / "wifi_configuration_ap.cc"
    )
    config_header = _read(
        ESP_DIR
        / "components"
        / "esp-wifi-connect"
        / "include"
        / "wifi_configuration_ap.h"
    )
    manager = _read(
        ESP_DIR / "components" / "esp-wifi-connect" / "wifi_manager.cc"
    )

    assert "station_netif_ = esp_netif_create_default_wifi_sta();" in config_ap
    assert "esp_netif_destroy_default_wifi(station_netif_);" in config_ap
    assert "esp_netif_t* station_netif_ = nullptr;" in config_header
    assert "auto transition = transition_gate_.Acquire();" in manager
