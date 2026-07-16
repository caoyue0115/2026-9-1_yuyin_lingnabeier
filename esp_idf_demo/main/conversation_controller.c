#include "conversation_controller.h"

#include <stddef.h>
#include <string.h>

static conversation_transition_t make_transition(conversation_controller_t *controller,
                                                 conversation_action_t action)
{
    conversation_transition_t result = {
        .state = controller->state,
        .action = action,
        .turn_index = controller->turn_index,
        .attempt_serial = controller->attempt_serial,
        .deadline_ms = controller->deadline_ms,
    };
    return result;
}

void conversation_controller_init(conversation_controller_t *controller)
{
    if (controller != NULL) {
        memset(controller, 0, sizeof(*controller));
        controller->state = CONVERSATION_STATE_IDLE;
    }
}

conversation_transition_t conversation_controller_handle(conversation_controller_t *controller,
                                                         conversation_event_t event,
                                                         int64_t now_ms)
{
    if (controller == NULL) {
        conversation_transition_t invalid = {0};
        return invalid;
    }
    if (event == CONVERSATION_EVENT_TECHNICAL_ERROR) {
        controller->state = CONVERSATION_STATE_FAILED;
        controller->deadline_ms = 0;
        return make_transition(controller, CONVERSATION_ACTION_PLAY_TECHNICAL_ERROR);
    }

    switch (controller->state) {
    case CONVERSATION_STATE_IDLE:
        if (event == CONVERSATION_EVENT_BEGIN) {
            controller->state = CONVERSATION_STATE_PROMPTING;
            return make_transition(controller, CONVERSATION_ACTION_OPEN_AND_PROMPT);
        }
        break;
    case CONVERSATION_STATE_PROMPTING:
    case CONVERSATION_STATE_REPROMPT:
        if (event == CONVERSATION_EVENT_PROMPT_DONE) {
            controller->state = CONVERSATION_STATE_RECORDING;
            controller->deadline_ms = now_ms + CONVERSATION_FOLLOWUP_START_TIMEOUT_MS;
            return make_transition(controller, CONVERSATION_ACTION_START_RECORDING);
        }
        break;
    case CONVERSATION_STATE_RECORDING:
        if (event == CONVERSATION_EVENT_RECORDING_DONE) {
            controller->state = CONVERSATION_STATE_WAITING_RESULT;
            controller->deadline_ms = 0;
            controller->attempt_serial++;
            return make_transition(controller, CONVERSATION_ACTION_SUBMIT_TURN);
        }
        if (event == CONVERSATION_EVENT_SPEECH_TIMEOUT) {
            if (!controller->reprompt_used) {
                controller->reprompt_used = true;
                controller->state = CONVERSATION_STATE_REPROMPT;
                return make_transition(controller, CONVERSATION_ACTION_PLAY_REPROMPT);
            }
            controller->state = CONVERSATION_STATE_ENDING;
            controller->done_prompt_issued = true;
            return make_transition(controller, CONVERSATION_ACTION_PLAY_DONE);
        }
        break;
    case CONVERSATION_STATE_WAITING_RESULT:
        if (event == CONVERSATION_EVENT_TURN_RESULT) {
            if (controller->turn_index > controller->followup_count) {
                controller->followup_count = controller->turn_index;
            }
            controller->state = CONVERSATION_STATE_PLAYING;
            return make_transition(controller, CONVERSATION_ACTION_PLAY_ANSWER);
        }
        if (event == CONVERSATION_EVENT_ASR_EMPTY) {
            if (!controller->reprompt_used) {
                controller->reprompt_used = true;
                controller->state = CONVERSATION_STATE_REPROMPT;
                return make_transition(controller, CONVERSATION_ACTION_PLAY_REPROMPT);
            }
            controller->state = CONVERSATION_STATE_ENDING;
            controller->done_prompt_issued = true;
            return make_transition(controller, CONVERSATION_ACTION_PLAY_DONE);
        }
        break;
    case CONVERSATION_STATE_PLAYING:
        if (event == CONVERSATION_EVENT_PLAYBACK_DONE) {
            if (controller->followup_count >= 3) {
                controller->state = CONVERSATION_STATE_ENDING;
                controller->deadline_ms = now_ms + CONVERSATION_FINAL_DONE_DELAY_MS;
                return make_transition(controller, CONVERSATION_ACTION_NONE);
            }
            controller->state = CONVERSATION_STATE_FOLLOWUP_WINDOW;
            controller->deadline_ms = now_ms + CONVERSATION_FOLLOWUP_START_TIMEOUT_MS;
            return make_transition(controller, CONVERSATION_ACTION_LISTEN_FOLLOWUP);
        }
        break;
    case CONVERSATION_STATE_FOLLOWUP_WINDOW:
        if (event == CONVERSATION_EVENT_SPEECH_STARTED) {
            controller->turn_index = controller->followup_count + 1;
            controller->reprompt_used = false;
            controller->state = CONVERSATION_STATE_RECORDING;
            controller->deadline_ms = now_ms + CONVERSATION_SPEECH_TAIL_MS;
            return make_transition(controller, CONVERSATION_ACTION_START_RECORDING);
        }
        if (event == CONVERSATION_EVENT_SPEECH_TIMEOUT ||
            (event == CONVERSATION_EVENT_TIMER && now_ms >= controller->deadline_ms)) {
            controller->state = CONVERSATION_STATE_ENDING;
            controller->done_prompt_issued = true;
            return make_transition(controller, CONVERSATION_ACTION_PLAY_DONE);
        }
        break;
    case CONVERSATION_STATE_ENDING:
        if (event == CONVERSATION_EVENT_TIMER && !controller->done_prompt_issued &&
            now_ms >= controller->deadline_ms) {
            controller->done_prompt_issued = true;
            return make_transition(controller, CONVERSATION_ACTION_PLAY_DONE);
        }
        if (event == CONVERSATION_EVENT_PROMPT_DONE) {
            controller->state = CONVERSATION_STATE_IDLE;
            return make_transition(controller, CONVERSATION_ACTION_CLOSE);
        }
        break;
    case CONVERSATION_STATE_FAILED:
        if (event == CONVERSATION_EVENT_PROMPT_DONE) {
            controller->state = CONVERSATION_STATE_IDLE;
            return make_transition(controller, CONVERSATION_ACTION_CLOSE);
        }
        break;
    default:
        break;
    }
    return make_transition(controller, CONVERSATION_ACTION_NONE);
}
