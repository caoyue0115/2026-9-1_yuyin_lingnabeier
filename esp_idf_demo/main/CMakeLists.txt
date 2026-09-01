idf_component_register(SRCS "main.c" "display_state.c" "trigger_input.c" "audio_in.c" "cloud_client.c" "audio_out.c" "board_audio.c" "app_network.cc" "wifi_credential_store.cc" "wifi_connection_policy.cc" "prompt_arbiter.c" "playback_session.c" "cloud_conversation.c" "conversation_controller.c" "wake_word_service.c"
                       INCLUDE_DIRS "."
                       REQUIRES esp_http_client json driver esp_timer esp_event esp_netif esp_wifi nvs_flash
                                esp_vocat espressif__esp_lcd_touch esp_websocket_client spiffs
                                esp_app_format app_update esp-wifi-connect espressif__esp-sr)

target_add_binary_data(${COMPONENT_LIB} "../spiffs/intro_1.pcm" BINARY)
target_add_binary_data(${COMPONENT_LIB} "../spiffs/followup_bell_1.pcm" BINARY)
target_add_binary_data(${COMPONENT_LIB} "../spiffs/speak_1.pcm" BINARY)
target_add_binary_data(${COMPONENT_LIB} "../spiffs/followup_1.pcm" BINARY)

file(MAKE_DIRECTORY "${CMAKE_CURRENT_LIST_DIR}/../spiffs")
spiffs_create_partition_image(storage ../spiffs FLASH_IN_PROJECT)
