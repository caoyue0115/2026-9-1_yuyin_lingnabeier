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

    def test_trigger_polling_is_not_gated_by_idle_state(self) -> None:
        main_c = (ESP_MAIN / "main.c").read_text(encoding="utf-8")

        poll_index = main_c.index("trigger_input_poll(&trigger, &event)")
        idle_gate_index = main_c.index("s_app_state == APP_STATE_IDLE", poll_index)

        self.assertLess(poll_index, idle_gate_index)
        self.assertIn("Trigger ignored", main_c)

    def test_audio_stream_task_is_reaped_only_after_it_suspends(self) -> None:
        audio_out_c = (ESP_MAIN / "audio_out.c").read_text(encoding="utf-8")
        task = audio_out_c.split("static void audio_stream_task", 1)[1].split(
            "esp_err_t audio_out_open_pcm_stream", 1
        )[0]
        close = audio_out_c.split(
            "esp_err_t audio_out_close_pcm_stream_with_metrics", 1
        )[1].split("esp_err_t audio_out_close_pcm_stream(void)", 1)[0]

        self.assertIn("stream_task_done", audio_out_c)
        self.assertIn("vTaskSuspend(NULL)", task)
        self.assertNotIn("vTaskDelete(NULL)", task)
        self.assertIn("eTaskGetState(stream_task) != eSuspended", close)
        self.assertEqual(close.count("vTaskDelete(stream_task)"), 1)
        self.assertNotIn("forcing task delete", close)

    def test_audio_stream_task_flushes_partial_tail_on_stream_stop(self) -> None:
        audio_out_c = (ESP_MAIN / "audio_out.c").read_text(encoding="utf-8")

        self.assertIn("audio_jitter_level_locked() <= scratch_len;", audio_out_c)
        self.assertNotIn("audio_jitter_level_locked() == 0;", audio_out_c)
        self.assertIn("if (scratch_len > 0)", audio_out_c)

    def test_audio_jitter_buffer_applies_lossless_backpressure(self) -> None:
        audio_out_c = (ESP_MAIN / "audio_out.c").read_text(encoding="utf-8")
        buffered_write = audio_out_c.split(
            "esp_err_t audio_out_write_pcm_chunk_buffered", 1
        )[1].split("esp_err_t audio_out_close_pcm_stream_with_metrics", 1)[0]

        self.assertIn("xRingbufferSend", buffered_write)
        self.assertIn("DEMO_AUDIO_PLAY_WRITE_TIMEOUT_MS", buffered_write)
        self.assertIn("last_progress_us", buffered_write)
        self.assertNotIn("portMAX_DELAY", buffered_write)

    def test_audio_close_timeout_is_progress_based_and_returns(self) -> None:
        audio_out_c = (ESP_MAIN / "audio_out.c").read_text(encoding="utf-8")
        close = audio_out_c.split(
            "esp_err_t audio_out_close_pcm_stream_with_metrics", 1
        )[1].split("esp_err_t audio_out_close_pcm_stream(void)", 1)[0]

        self.assertIn("last_progress_us", close)
        self.assertIn("return ESP_ERR_TIMEOUT;", close)
        self.assertNotIn("continuing safe wait", close)

    def test_stalled_audio_task_blocks_resource_reuse_and_deinit(self) -> None:
        audio_out_c = (ESP_MAIN / "audio_out.c").read_text(encoding="utf-8")
        open_stream = audio_out_c.split(
            "esp_err_t audio_out_open_pcm_stream", 1
        )[1].split("esp_err_t audio_out_write_pcm_chunk", 1)[0]
        deinit = audio_out_c.split("void audio_out_deinit(void)", 1)[1]

        self.assertIn("audio_out_finish_existing_stream", open_stream)
        self.assertLess(
            open_stream.index("audio_out_finish_existing_stream"),
            open_stream.index("audio_install_output_locked"),
        )
        self.assertIn("audio_out_finish_existing_stream", deinit)
        self.assertLess(
            deinit.index("audio_out_finish_existing_stream"),
            deinit.index("audio_out_deinit_locked"),
        )

    def test_audio_jitter_reader_releases_small_chunks_frequently(self) -> None:
        audio_out_c = (ESP_MAIN / "audio_out.c").read_text(encoding="utf-8")
        task = audio_out_c.split("static void audio_stream_task", 1)[1].split(
            "esp_err_t audio_out_open_pcm_stream", 1
        )[0]

        self.assertIn("xRingbufferReceiveUpTo", task)
        self.assertIn("DEMO_REALTIME_AUDIO_JITTER_READ_BYTES", task)
        self.assertNotIn(
            "xRingbufferReceive(s_audio_out_state.jitter_ringbuf",
            task,
        )

    def test_v7_playback_and_persistent_conversation_interfaces_exist(self) -> None:
        playback_h = (ESP_MAIN / "playback_session.h").read_text(encoding="utf-8")
        playback_c = (ESP_MAIN / "playback_session.c").read_text(encoding="utf-8")
        conversation_h = (ESP_MAIN / "cloud_conversation.h").read_text(encoding="utf-8")
        conversation_c = (ESP_MAIN / "cloud_conversation.c").read_text(encoding="utf-8")
        cloud_h = (ESP_MAIN / "cloud_client.h").read_text(encoding="utf-8")
        cloud_c = (ESP_MAIN / "cloud_client.c").read_text(encoding="utf-8")
        cmake = (ESP_MAIN / "CMakeLists.txt").read_text(encoding="utf-8")

        for declaration in (
            "typedef struct playback_session playback_session_t;",
            "playback_session_start(const char *url, playback_session_t **out)",
            "playback_session_cancel(playback_session_t *session, int reason)",
            "playback_session_detach(playback_session_t **session)",
            "playback_session_join(playback_session_t **session,\n                                TickType_t inactivity_timeout,\n                                esp_err_t *playback_result)",
        ):
            self.assertIn(declaration, playback_h)
        self.assertIn("volatile bool cancel_requested", playback_c)
        self.assertIn("cloud_client_stream_realtime_audio_cancellable", playback_c)
        self.assertIn("audio_out_close_pcm_stream", playback_c)

        for declaration in (
            "typedef struct cloud_conversation cloud_conversation_t;",
            "cloud_conversation_open(cloud_conversation_t **out)",
            "cloud_conversation_start_turn(cloud_conversation_t *conversation, uint8_t turn_index, const char *turn_id)",
            "cloud_conversation_finish_turn(cloud_conversation_t *conversation, cloud_realtime_session_t *result)",
            "cloud_conversation_cancel_turn(cloud_conversation_t *conversation, const char *turn_id)",
            "cloud_conversation_close(cloud_conversation_t *conversation, const char *reason)",
        ):
            self.assertIn(declaration, conversation_h)
        self.assertIn("api/v6/realtime/conversation/opus-stream", conversation_c)
        self.assertIn("conversation_start", conversation_c)
        self.assertIn("turn_start", conversation_c)
        self.assertIn("turn_end", conversation_c)
        self.assertIn("turn_cancel", conversation_c)
        self.assertIn("conversation_end", conversation_c)
        self.assertIn("sequence = 0", conversation_c)
        self.assertIn("turn_id", conversation_c)
        self.assertIn("turn_index", conversation_c)

        self.assertIn("cloud_client_stream_realtime_audio_cancellable", cloud_h)
        self.assertIn("cancel_requested", cloud_c)
        self.assertIn("cloud_create_stream_task(cloud_decode_task", cloud_c)
        self.assertIn("cloud_create_stream_task(cloud_playback_task", cloud_c)
        self.assertIn("xTaskCreateWithCaps", cloud_c)
        self.assertIn("vTaskDeleteWithCaps", cloud_c)
        self.assertIn("MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT", cloud_c)
        self.assertIn('"playback_session.c"', cmake)
        self.assertIn('"cloud_conversation.c"', cmake)

    def test_playback_owner_is_reaped_before_completion_event_is_deleted(self) -> None:
        playback_c = (ESP_MAIN / "playback_session.c").read_text(encoding="utf-8")
        owner = playback_c.split("static void playback_session_owner", 1)[1].split(
            "esp_err_t playback_session_start", 1
        )[0]
        join = playback_c.split("esp_err_t playback_session_join", 1)[1]

        self.assertIn("completion_published", playback_c)
        self.assertIn("xEventGroupSetBits", owner)
        self.assertIn("__atomic_store_n", owner)
        self.assertIn("vTaskSuspend(NULL)", owner)
        self.assertNotIn("vTaskDelete(NULL)", owner)
        self.assertIn("eTaskGetState(task) != eSuspended", join)
        self.assertIn("vTaskDeleteWithCaps(task)", join)
        self.assertLess(join.index("vTaskDeleteWithCaps(task)"), join.index("vEventGroupDelete"))
        self.assertIn("xTaskCreateWithCaps", playback_c)
        self.assertIn("MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT", playback_c)

    def test_answer_playback_is_not_cancelled_by_an_absolute_duration_limit(self) -> None:
        playback_c = (ESP_MAIN / "playback_session.c").read_text(encoding="utf-8")
        main_c = (ESP_MAIN / "main.c").read_text(encoding="utf-8")
        join = playback_c.split("esp_err_t playback_session_join", 1)[1]
        playback_block = main_c.split(
            "playback_session_t *playback = NULL;", 1
        )[1].split("const int64_t playback_done_ms", 1)[0]

        self.assertIn("esp_err_t *playback_result", join)
        self.assertIn("*playback_result = result", join)
        self.assertIn("return ESP_OK;", join)
        self.assertIn("esp_err_t join_ret = playback_session_join", main_c)
        self.assertIn("last_progress_us", join)
        self.assertIn("playback_session_join(&playback,", playback_block)
        self.assertIn(
            "pdMS_TO_TICKS(DEMO_REALTIME_AUDIO_TASK_JOIN_TIMEOUT_MS)",
            playback_block,
        )
        self.assertNotIn("DEMO_REALTIME_SESSION_TIMEOUT_MS", playback_block)
        self.assertIn("playback_session_cancel(playback, ESP_ERR_TIMEOUT)", playback_block)
        self.assertIn("playback_session_detach(&playback)", playback_block)
        self.assertIn("detach_ret", playback_block)
        self.assertNotIn("esp_restart()", playback_block)
        self.assertIn("esp_restart()", playback_c)
        self.assertIn("xTaskCreateStatic", playback_c)
        self.assertIn("xQueueCreateStatic", playback_c)
        self.assertIn("xQueueReceive", playback_c)
        reaper = playback_c.split("static void playback_session_reaper", 1)[1].split(
            "esp_err_t playback_session_detach", 1
        )[0]
        self.assertNotIn("vTaskDelete(NULL)", reaper)
        self.assertIn("#define PLAYBACK_REAPER_STACK_BYTES 4096", playback_c)
        self.assertIn(
            "__atomic_store_n(&session->last_progress_us, esp_timer_get_time(), __ATOMIC_RELEASE)",
            playback_c,
        )

    def test_cloud_conversation_publishes_callback_state_atomically(self) -> None:
        conversation_c = (ESP_MAIN / "cloud_conversation.c").read_text(encoding="utf-8")

        self.assertIn("__atomic_store_n(flag, true, __ATOMIC_RELEASE)", conversation_c)
        self.assertIn("__atomic_load_n(flag, __ATOMIC_ACQUIRE)", conversation_c)
        self.assertNotIn("volatile bool connected", conversation_c)

    def test_realtime_audio_log_does_not_include_bearer_url(self) -> None:
        cloud_c = (ESP_MAIN / "cloud_client.c").read_text(encoding="utf-8")
        stream = cloud_c.split(
            "esp_err_t cloud_client_stream_realtime_audio_cancellable", 1
        )[1]

        log_setup = stream.split("esp_http_client_set_header", 1)[1].split(
            "cloud_log_heap_snapshot", 1
        )[0]
        self.assertNotIn("url=%s", log_setup)
        self.assertNotIn("audio_stream_url,", log_setup)

    def test_prompt_wait_propagates_playback_result(self) -> None:
        arbiter_c = (ESP_MAIN / "prompt_arbiter.c").read_text(encoding="utf-8")
        owner = arbiter_c.split("static void prompt_arbiter_owner_task", 1)[1].split(
            "esp_err_t prompt_arbiter_wait_key", 1
        )[0]
        wait_key = arbiter_c.split("esp_err_t prompt_arbiter_wait_key", 1)[1].split(
            "esp_err_t prompt_arbiter_wait_idle", 1
        )[0]

        self.assertIn("s_last_result = ret", owner)
        self.assertIn("completed ? completed_result : ESP_OK", wait_key)

    def test_followup_window_enters_listening_without_replaying_fixed_bell(self) -> None:
        main_c = (ESP_MAIN / "main.c").read_text(encoding="utf-8")
        followup_block = main_c.split(
            "conversation_transition_t played = conversation_controller_handle", 1
        )[1].split("if (played.state == CONVERSATION_STATE_ENDING)", 1)[0]

        self.assertIn(
            "played.action == CONVERSATION_ACTION_PLAY_FOLLOWUP_CUE",
            followup_block,
        )
        self.assertNotIn("PROMPT_FOLLOWUP_CUE", followup_block)
        self.assertNotIn('"conversation:followup-cue:', followup_block)
        self.assertIn("CONVERSATION_EVENT_PROMPT_DONE", followup_block)
        self.assertIn("CONVERSATION_ACTION_LISTEN_FOLLOWUP", followup_block)
        self.assertNotIn("PROMPT_SPEAK", followup_block)

    def test_followup_listener_rejects_bell_tail_and_keeps_full_five_seconds(self) -> None:
        config_h = (ESP_MAIN / "config.h").read_text(encoding="utf-8")
        audio_in_h = (ESP_MAIN / "audio_in.h").read_text(encoding="utf-8")
        audio_in_c = (ESP_MAIN / "audio_in.c").read_text(encoding="utf-8")
        main_c = (ESP_MAIN / "main.c").read_text(encoding="utf-8")

        self.assertIn("#define DEMO_FOLLOWUP_VAD_START_THRESHOLD 800", config_h)
        self.assertIn("uint32_t start_threshold", audio_in_h)
        self.assertIn(
            "timeout_at_us = armed_at_us + (int64_t)DEMO_WAIT_FOR_SPEECH_TIMEOUT_MS * 1000",
            audio_in_c,
        )
        self.assertIn("chunk_level >= start_threshold", audio_in_c)
        self.assertIn(
            "controller.state == CONVERSATION_STATE_FOLLOWUP_WINDOW",
            main_c,
        )
        self.assertIn("DEMO_FOLLOWUP_VAD_START_THRESHOLD", main_c)

    def test_v6_websocket_json_parser_ignores_control_frames(self) -> None:
        conversation_c = (ESP_MAIN / "cloud_conversation.c").read_text(encoding="utf-8")
        event_handler = conversation_c.split("static void v6_ws_event", 1)[1].split(
            "static esp_err_t v6_wait_flag", 1
        )[0]

        opcode_guard = "data->op_code != 0x01 && data->op_code != 0x00"
        self.assertIn(opcode_guard, event_handler)
        self.assertLess(
            event_handler.index(opcode_guard),
            event_handler.index("if (data->data_ptr == NULL"),
        )

    def test_v7_four_turn_controller_is_integrated(self) -> None:
        header = (ESP_MAIN / "conversation_controller.h").read_text(encoding="utf-8")
        source = (ESP_MAIN / "conversation_controller.c").read_text(encoding="utf-8")
        main_c = (ESP_MAIN / "main.c").read_text(encoding="utf-8")
        config = (ESP_MAIN / "config.h").read_text(encoding="utf-8")
        cmake = (ESP_MAIN / "CMakeLists.txt").read_text(encoding="utf-8")

        for state in (
            "CONVERSATION_STATE_IDLE",
            "CONVERSATION_STATE_PROMPTING",
            "CONVERSATION_STATE_RECORDING",
            "CONVERSATION_STATE_WAITING_RESULT",
            "CONVERSATION_STATE_PLAYING",
            "CONVERSATION_STATE_FOLLOWUP_WINDOW",
            "CONVERSATION_STATE_REPROMPT",
            "CONVERSATION_STATE_ENDING",
            "CONVERSATION_STATE_FAILED",
        ):
            self.assertIn(state, header)
        self.assertIn("conversation_controller_handle", header)
        self.assertIn("CONVERSATION_FOLLOWUP_START_TIMEOUT_MS", config)
        self.assertIn("CONVERSATION_SPEECH_TAIL_MS", config)
        self.assertIn("CONVERSATION_FINAL_DONE_DELAY_MS", config)
        self.assertIn("#if DEMO_V6_CONVERSATION_ENABLED", config)
        self.assertIn("#define DEMO_WAIT_FOR_SPEECH_TIMEOUT_MS 3000", config)
        self.assertIn("conversation_controller_handle", main_c)
        self.assertIn("cloud_conversation_open", main_c)
        self.assertIn("cloud_conversation_send_pcm", main_c)
        self.assertIn("playback_session_start", main_c)
        self.assertNotIn("PROMPT_CONVERSATION_DONE", main_c)
        self.assertIn("app_wait_until_ms", main_c)
        self.assertIn("prompt_arbiter_wait_key(key, 15000)", main_c)
        self.assertIn("playback_session_join(&playback,", main_c)
        self.assertIn("CONVERSATION_EVENT_PLAYBACK_DONE", main_c)
        self.assertIn("playback_done_ms", main_c)
        self.assertIn('"conversation_controller.c"', cmake)
        self.assertNotIn("vTaskDelay", source)


if __name__ == "__main__":
    unittest.main()
