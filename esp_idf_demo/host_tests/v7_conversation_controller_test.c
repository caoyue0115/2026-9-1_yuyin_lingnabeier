#include "conversation_controller.h"

#include <assert.h>

static conversation_transition_t send(conversation_controller_t *controller,
                                      conversation_event_t event,
                                      int64_t now_ms)
{
    return conversation_controller_handle(controller, event, now_ms);
}

int main(void)
{
    conversation_controller_t controller;
    conversation_controller_init(&controller);
    assert(send(&controller, CONVERSATION_EVENT_BEGIN, 0).action == CONVERSATION_ACTION_OPEN_AND_PROMPT);
    assert(controller.state == CONVERSATION_STATE_PROMPTING);
    assert(send(&controller, CONVERSATION_EVENT_PROMPT_DONE, 100).deadline_ms == 5100);
    assert(controller.state == CONVERSATION_STATE_RECORDING);
    assert(send(&controller, CONVERSATION_EVENT_RECORDING_DONE, 900).action == CONVERSATION_ACTION_SUBMIT_TURN);
    assert(controller.attempt_serial == 1);
    assert(send(&controller, CONVERSATION_EVENT_TURN_RESULT, 1200).action == CONVERSATION_ACTION_PLAY_ANSWER);

    for (int followup = 1; followup <= 3; ++followup) {
        conversation_transition_t transition = send(&controller, CONVERSATION_EVENT_PLAYBACK_DONE, 2000 * followup);
        assert(controller.state == CONVERSATION_STATE_FOLLOWUP_CUE);
        assert(transition.action == CONVERSATION_ACTION_PLAY_FOLLOWUP_CUE);
        transition = send(&controller, CONVERSATION_EVENT_PROMPT_DONE, 2000 * followup + 100);
        assert(controller.state == CONVERSATION_STATE_FOLLOWUP_WINDOW);
        assert(transition.action == CONVERSATION_ACTION_LISTEN_FOLLOWUP);
        assert(transition.deadline_ms == 2000 * followup + 10100);
        send(&controller, CONVERSATION_EVENT_SPEECH_STARTED, 2000 * followup + 200);
        assert(controller.turn_index == followup);
        send(&controller, CONVERSATION_EVENT_RECORDING_DONE, 2000 * followup + 800);
        send(&controller, CONVERSATION_EVENT_TURN_RESULT, 2000 * followup + 1100);
        assert(controller.followup_count == followup);
    }
    conversation_transition_t final_answer = send(&controller, CONVERSATION_EVENT_PLAYBACK_DONE, 8000);
    assert(controller.state == CONVERSATION_STATE_ENDING);
    assert(final_answer.action == CONVERSATION_ACTION_NONE);
    assert(final_answer.deadline_ms == 9000);
    assert(send(&controller, CONVERSATION_EVENT_TIMER, 8999).action == CONVERSATION_ACTION_NONE);
    assert(send(&controller, CONVERSATION_EVENT_TIMER, 9000).action == CONVERSATION_ACTION_PLAY_DONE);

    conversation_controller_init(&controller);
    assert(controller.max_turns == CONVERSATION_DEFAULT_MAX_TURNS);
    conversation_controller_set_max_turns(&controller, CONVERSATION_GAME_MAX_TURNS);
    assert(controller.max_turns == CONVERSATION_GAME_MAX_TURNS);
    send(&controller, CONVERSATION_EVENT_BEGIN, 0);
    send(&controller, CONVERSATION_EVENT_PROMPT_DONE, 1);
    send(&controller, CONVERSATION_EVENT_RECORDING_DONE, 2);
    send(&controller, CONVERSATION_EVENT_TURN_RESULT, 3);
    for (int followup = 1; followup <= 9; ++followup) {
        conversation_transition_t transition =
            send(&controller, CONVERSATION_EVENT_PLAYBACK_DONE, 1000 * followup);
        assert(controller.state == CONVERSATION_STATE_FOLLOWUP_CUE);
        assert(transition.action == CONVERSATION_ACTION_PLAY_FOLLOWUP_CUE);
        send(&controller, CONVERSATION_EVENT_PROMPT_DONE, 1000 * followup + 1);
        send(&controller, CONVERSATION_EVENT_SPEECH_STARTED, 1000 * followup + 2);
        send(&controller, CONVERSATION_EVENT_RECORDING_DONE, 1000 * followup + 3);
        send(&controller, CONVERSATION_EVENT_TURN_RESULT, 1000 * followup + 4);
    }
    assert(controller.followup_count == 9);
    assert(send(&controller, CONVERSATION_EVENT_PLAYBACK_DONE, 10000).action ==
           CONVERSATION_ACTION_NONE);
    assert(controller.state == CONVERSATION_STATE_ENDING);
    conversation_controller_set_max_turns(&controller, 11);
    assert(controller.max_turns == CONVERSATION_DEFAULT_MAX_TURNS);

    conversation_controller_init(&controller);
    send(&controller, CONVERSATION_EVENT_BEGIN, 0);
    send(&controller, CONVERSATION_EVENT_PROMPT_DONE, 0);
    send(&controller, CONVERSATION_EVENT_RECORDING_DONE, 1);
    conversation_transition_t empty = send(&controller, CONVERSATION_EVENT_ASR_EMPTY, 2);
    assert(empty.action == CONVERSATION_ACTION_PLAY_REPROMPT);
    assert(controller.state == CONVERSATION_STATE_REPROMPT);
    assert(controller.turn_index == 0);
    send(&controller, CONVERSATION_EVENT_PROMPT_DONE, 3);
    send(&controller, CONVERSATION_EVENT_RECORDING_DONE, 4);
    assert(controller.attempt_serial == 2);
    assert(controller.turn_index == 0);
    assert(send(&controller, CONVERSATION_EVENT_ASR_EMPTY, 5).action == CONVERSATION_ACTION_PLAY_DONE);

    conversation_controller_init(&controller);
    send(&controller, CONVERSATION_EVENT_BEGIN, 0);
    send(&controller, CONVERSATION_EVENT_PROMPT_DONE, 0);
    send(&controller, CONVERSATION_EVENT_RECORDING_DONE, 1);
    send(&controller, CONVERSATION_EVENT_TURN_RESULT, 2);
    send(&controller, CONVERSATION_EVENT_PLAYBACK_DONE, 3);
    send(&controller, CONVERSATION_EVENT_PROMPT_DONE, 503);
    conversation_transition_t silence = send(&controller, CONVERSATION_EVENT_SPEECH_TIMEOUT, 10503);
    assert(silence.action == CONVERSATION_ACTION_NONE);
    assert(controller.state == CONVERSATION_STATE_ENDING);
    assert(silence.deadline_ms == 11503);
    assert(send(&controller, CONVERSATION_EVENT_TIMER, 11502).action == CONVERSATION_ACTION_NONE);
    assert(send(&controller, CONVERSATION_EVENT_TIMER, 11503).action == CONVERSATION_ACTION_PLAY_DONE);

    conversation_controller_init(&controller);
    send(&controller, CONVERSATION_EVENT_BEGIN, 0);
    assert(send(&controller, CONVERSATION_EVENT_TECHNICAL_ERROR, 1).action ==
           CONVERSATION_ACTION_PLAY_TECHNICAL_ERROR);
    assert(controller.state == CONVERSATION_STATE_FAILED);
    return 0;
}
