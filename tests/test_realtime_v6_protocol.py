from __future__ import annotations

import pytest

from src.models.conversation_v6 import (
    MAX_CONNECTION_SECONDS,
    MAX_FRAME_BYTES,
    MAX_TURN_AUDIO_BYTES,
    MAX_TURNS,
    ProtocolError,
    TurnOutcome,
    TurnState,
    TurnStateMachine,
    conversation_done_event,
    conversation_ready_event,
    parse_client_control,
)


GOLDEN_PLAYED = [
    ("conversation_start", "conversation_ready"),
    ("turn_start", "ack"),
    ("binary:0", "ack:0"),
    ("turn_end", "asr_final"),
    ("asr_final", "turn_result"),
    ("turn_playback_complete", "turn_complete:played"),
    ("conversation_end", "conversation_done"),
]


def _turn_control(message_type: str, **extra: object) -> dict[str, object]:
    return {
        "type": message_type,
        "conversation_id": "conversation-1",
        "turn_id": "turn-1",
        "turn_index": 0,
        **extra,
    }


def test_client_controls_parse_with_required_correlation_fields() -> None:
    start = parse_client_control(
        {
            "type": "conversation_start",
            "client_conversation_id": "client-1",
            "device_id": "device-1",
            "audio_format": "opus",
            "protocol_version": "v6",
            "answer_mode": "streaming",
        }
    )
    assert start.client_conversation_id == "client-1"
    assert start.conversation_id is None

    for message_type in ("turn_start", "turn_end", "turn_cancel", "turn_playback_complete"):
        message = parse_client_control(_turn_control(message_type))
        assert message.conversation_id == "conversation-1"
        assert message.turn_id == "turn-1"
        assert message.turn_index == 0

    end = parse_client_control({"type": "conversation_end", "conversation_id": "conversation-1"})
    assert end.conversation_id == "conversation-1"


def test_controls_reject_missing_or_mismatched_correlation() -> None:
    with pytest.raises(ProtocolError):
        parse_client_control({"type": "turn_start", "turn_id": "turn-1", "turn_index": 0})

    fsm = TurnStateMachine(conversation_id="conversation-1", turn_id="turn-1", turn_index=0)
    fsm.validate_correlation(parse_client_control(_turn_control("turn_start")))

    with pytest.raises(ProtocolError):
        fsm.validate_correlation(
            parse_client_control(
                _turn_control("turn_end", conversation_id="other-conversation")
            )
        )
    with pytest.raises(ProtocolError):
        fsm.validate_correlation(parse_client_control(_turn_control("turn_end", turn_id="other-turn")))
    with pytest.raises(ProtocolError):
        fsm.validate_correlation(parse_client_control(_turn_control("turn_end", turn_index=1)))


def test_golden_played_trace_preserves_turn_correlation() -> None:
    fsm = TurnStateMachine(conversation_id="conversation-1", turn_id="turn-1", turn_index=0)

    ready = conversation_ready_event("client-1", "conversation-1")
    start_ack = fsm.on_turn_start()
    frame_ack = fsm.accept_frame(0, "digest-0")
    fsm.on_turn_end()
    asr_final = fsm.on_asr_final("question")
    result = fsm.on_turn_result(session_id="session-1", audio_stream_url="/audio")
    complete = fsm.on_turn_playback_complete()
    done = conversation_done_event("conversation-1")

    observed = [
        ("conversation_start", ready.type),
        ("turn_start", start_ack.type),
        ("binary:0", f"{frame_ack.type}:{frame_ack.highest_contiguous_sequence}"),
        ("turn_end", asr_final.type),
        ("asr_final", result.type),
        ("turn_playback_complete", f"{complete.type}:{complete.outcome}"),
        ("conversation_end", done.type),
    ]
    assert observed == GOLDEN_PLAYED

    for event in (start_ack, frame_ack, asr_final, result, complete):
        assert event.conversation_id == "conversation-1"
        assert event.turn_id == "turn-1"
        assert event.turn_index == 0

    assert fsm.state is TurnState.COMPLETED
    assert fsm.is_terminal


def test_empty_asr_finishes_before_reprompt() -> None:
    fsm = TurnStateMachine(turn_id="t1", turn_index=1)
    fsm.on_turn_start()
    fsm.on_turn_end()
    event = fsm.on_asr_empty()
    assert event.type == "turn_complete"
    assert event.outcome == TurnOutcome.ASR_EMPTY
    assert fsm.is_terminal


@pytest.mark.parametrize(
    ("transition", "expected_outcome"),
    [
        ("on_technical_error", TurnOutcome.TECHNICAL_ERROR),
        ("on_rejected", TurnOutcome.REJECTED),
    ],
)
def test_terminal_error_outcomes_complete_turn(
    transition: str, expected_outcome: TurnOutcome
) -> None:
    fsm = TurnStateMachine(conversation_id="conversation-1", turn_id="turn-1", turn_index=0)
    fsm.on_turn_start()
    event = getattr(fsm, transition)()

    assert event.type == "turn_complete"
    assert event.outcome is expected_outcome
    assert fsm.state is TurnState.COMPLETED
    assert fsm.is_terminal


def test_cancel_transitions_to_cancelled_and_is_idempotent() -> None:
    fsm = TurnStateMachine(conversation_id="conversation-1", turn_id="turn-1", turn_index=0)
    fsm.on_turn_start()

    cancelled = fsm.on_turn_cancel()
    duplicate = fsm.on_turn_cancel()

    assert cancelled.type == "turn_cancelled"
    assert duplicate == cancelled
    assert fsm.state is TurnState.CANCELLED
    assert fsm.is_terminal


def test_frame_ack_is_highest_contiguous_and_duplicate_is_reacked() -> None:
    fsm = TurnStateMachine(turn_id="turn-1", turn_index=0)
    fsm.on_turn_start()

    assert fsm.accept_frame(1, "digest-1").highest_contiguous_sequence == -1
    assert fsm.accept_frame(0, "digest-0").highest_contiguous_sequence == 1
    assert fsm.accept_frame(0, "digest-0").highest_contiguous_sequence == 1


def test_frame_sequence_conflict_rejects_changed_duplicate() -> None:
    fsm = TurnStateMachine(turn_id="turn-1", turn_index=0)
    fsm.on_turn_start()
    fsm.accept_frame(0, "digest-0")

    with pytest.raises(ProtocolError, match="^sequence_conflict$"):
        fsm.accept_frame(0, "different-digest")


def test_binary_sequence_resets_for_each_turn() -> None:
    first_turn = TurnStateMachine(turn_id="turn-1", turn_index=0)
    first_turn.on_turn_start()
    assert first_turn.accept_frame(0, "first").highest_contiguous_sequence == 0

    second_turn = TurnStateMachine(turn_id="turn-2", turn_index=1)
    second_turn.on_turn_start()
    assert second_turn.accept_frame(0, "second").highest_contiguous_sequence == 0


def test_protocol_limits_are_locked() -> None:
    assert MAX_TURNS == 4
    assert MAX_FRAME_BYTES == 4096
    assert MAX_TURN_AUDIO_BYTES == 16_000 * 2 * 8
    assert MAX_CONNECTION_SECONDS == 180
