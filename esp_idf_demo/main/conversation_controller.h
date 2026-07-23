#pragma once

#include <stdbool.h>
#include <stdint.h>

#ifndef CONVERSATION_FOLLOWUP_START_TIMEOUT_MS
#define CONVERSATION_FOLLOWUP_START_TIMEOUT_MS 5000
#endif
#ifndef CONVERSATION_SPEECH_TAIL_MS
#define CONVERSATION_SPEECH_TAIL_MS 700
#endif
#ifndef CONVERSATION_FINAL_DONE_DELAY_MS
#define CONVERSATION_FINAL_DONE_DELAY_MS 1000
#endif

typedef enum {
    CONVERSATION_STATE_IDLE = 0,
    CONVERSATION_STATE_PROMPTING,
    CONVERSATION_STATE_RECORDING,
    CONVERSATION_STATE_WAITING_RESULT,
    CONVERSATION_STATE_PLAYING,
    CONVERSATION_STATE_FOLLOWUP_CUE,
    CONVERSATION_STATE_FOLLOWUP_WINDOW,
    CONVERSATION_STATE_REPROMPT,
    CONVERSATION_STATE_ENDING,
    CONVERSATION_STATE_FAILED,
} conversation_state_t;

typedef enum {
    CONVERSATION_EVENT_BEGIN = 0,
    CONVERSATION_EVENT_PROMPT_DONE,
    CONVERSATION_EVENT_SPEECH_STARTED,
    CONVERSATION_EVENT_SPEECH_TIMEOUT,
    CONVERSATION_EVENT_RECORDING_DONE,
    CONVERSATION_EVENT_TURN_RESULT,
    CONVERSATION_EVENT_ASR_EMPTY,
    CONVERSATION_EVENT_PLAYBACK_DONE,
    CONVERSATION_EVENT_TECHNICAL_ERROR,
    CONVERSATION_EVENT_TIMER,
} conversation_event_t;

typedef enum {
    CONVERSATION_ACTION_NONE = 0,
    CONVERSATION_ACTION_OPEN_AND_PROMPT,
    CONVERSATION_ACTION_START_RECORDING,
    CONVERSATION_ACTION_SUBMIT_TURN,
    CONVERSATION_ACTION_PLAY_ANSWER,
    CONVERSATION_ACTION_PLAY_FOLLOWUP_CUE,
    CONVERSATION_ACTION_LISTEN_FOLLOWUP,
    CONVERSATION_ACTION_PLAY_REPROMPT,
    CONVERSATION_ACTION_PLAY_DONE,
    CONVERSATION_ACTION_PLAY_TECHNICAL_ERROR,
    CONVERSATION_ACTION_CLOSE,
} conversation_action_t;

typedef struct {
    conversation_state_t state;
    uint8_t turn_index;
    uint8_t followup_count;
    uint16_t attempt_serial;
    bool reprompt_used;
    bool done_prompt_issued;
    int64_t deadline_ms;
} conversation_controller_t;

typedef struct {
    conversation_state_t state;
    conversation_action_t action;
    uint8_t turn_index;
    uint16_t attempt_serial;
    int64_t deadline_ms;
} conversation_transition_t;

void conversation_controller_init(conversation_controller_t *controller);
conversation_transition_t conversation_controller_handle(conversation_controller_t *controller,
                                                         conversation_event_t event,
                                                         int64_t now_ms);
