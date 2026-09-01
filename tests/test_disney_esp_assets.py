from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ESP_DIR = ROOT / "esp_idf_demo"
ESP_MAIN = ROOT / "esp_idf_demo" / "main"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_voice_wake_is_the_only_conversation_trigger() -> None:
    config = _read(ESP_MAIN / "config.h")
    assert "#define DEMO_TRIGGER_SOURCE DEMO_TRIGGER_SOURCE_WAKE_WORD" in config
    assert '#define DEMO_WAKE_WORD_TEXT "小明同学"' in config


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


def test_display_uses_bounded_single_dma_buffer() -> None:
    config = _read(ESP_MAIN / "config.h")
    display = _read(ESP_MAIN / "display_state.c")
    assert "#define DEMO_DISPLAY_BUFFER_HEIGHT 40" in config
    assert "#define DEMO_DISPLAY_DOUBLE_BUFFER 0" in config
    assert "bsp_display_start_with_config(&display_cfg)" in display


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
