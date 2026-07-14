from __future__ import annotations

import pytest

from src.models.conversation_v6 import (
    ConversationLimits,
    MAX_CONNECTION_SECONDS,
    MAX_FRAME_BYTES,
    MAX_TURN_AUDIO_BYTES,
    MAX_TURNS,
    ProtocolError,
    ServerEvent,
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


def _assert_turn_event_correlation(
    event: ServerEvent, *, turn_id: str = "turn-1", turn_index: int = 0
) -> None:
    assert event.conversation_id == "conversation-1"
    assert event.turn_id == turn_id
    assert event.turn_index == turn_index


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

    end = parse_client_control(
        {"type": "conversation_end", "conversation_id": "conversation-1", "reason": "normal"}
    )
    assert end.conversation_id == "conversation-1"
    assert end.data["reason"] == "normal"


@pytest.mark.parametrize(
    ("field", "value", "error_code"),
    [
        ("device_id", "", "missing_device_id"),
        ("audio_format", "", "missing_audio_format"),
        ("audio_format", "pcm", "unsupported_audio_format"),
        ("protocol_version", None, "unsupported_protocol_version"),
        ("protocol_version", "v5", "unsupported_protocol_version"),
        ("answer_mode", "", "missing_answer_mode"),
        ("answer_mode", "batch", "unsupported_answer_mode"),
    ],
)
def test_conversation_start_rejects_missing_or_unsupported_wire_contract(
    field: str, value: object, error_code: str
) -> None:
    payload = {
        "type": "conversation_start",
        "client_conversation_id": "client-1",
        "device_id": "device-1",
        "audio_format": "opus",
        "protocol_version": "v6",
        "answer_mode": "streaming",
    }
    payload[field] = value

    with pytest.raises(ProtocolError, match=f"^{error_code}$"):
        parse_client_control(payload)


def test_conversation_end_requires_a_nonempty_reason() -> None:
    with pytest.raises(ProtocolError, match="^missing_reason$"):
        parse_client_control({"type": "conversation_end", "conversation_id": "conversation-1"})


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
    frame_ack = fsm.accept_frame(0, "digest-0", 1)
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
        _assert_turn_event_correlation(event)

    assert fsm.state is TurnState.COMPLETED
    assert fsm.is_terminal


def test_empty_asr_finishes_before_reprompt() -> None:
    fsm = TurnStateMachine(conversation_id="conversation-1", turn_id="t1", turn_index=1)
    fsm.on_turn_start()
    fsm.on_turn_end()
    event = fsm.on_asr_empty()
    assert event.type == "turn_complete"
    assert event.outcome == TurnOutcome.ASR_EMPTY
    _assert_turn_event_correlation(event, turn_id="t1", turn_index=1)
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
    _assert_turn_event_correlation(event)
    assert fsm.state is TurnState.COMPLETED
    assert fsm.is_terminal


def test_cancel_transitions_to_cancelled_and_is_idempotent() -> None:
    fsm = TurnStateMachine(conversation_id="conversation-1", turn_id="turn-1", turn_index=0)
    fsm.on_turn_start()

    cancelled = fsm.on_turn_cancel()
    duplicate = fsm.on_turn_cancel()

    assert cancelled.type == "turn_cancelled"
    assert duplicate == cancelled
    _assert_turn_event_correlation(cancelled)
    assert fsm.state is TurnState.CANCELLED
    assert fsm.is_terminal


def test_frame_ack_is_highest_contiguous_and_duplicate_is_reacked() -> None:
    fsm = TurnStateMachine(conversation_id="conversation-1", turn_id="turn-1", turn_index=0)
    fsm.on_turn_start()

    out_of_order = fsm.accept_frame(1, "digest-1", 1)
    first = fsm.accept_frame(0, "digest-0", 1)
    duplicate = fsm.accept_frame(0, "digest-0", 1)

    assert out_of_order.highest_contiguous_sequence == -1
    assert first.highest_contiguous_sequence == 1
    assert duplicate.highest_contiguous_sequence == 1
    for event in (out_of_order, first, duplicate):
        _assert_turn_event_correlation(event)


def test_frame_sequence_conflict_rejects_changed_duplicate() -> None:
    fsm = TurnStateMachine(conversation_id="conversation-1", turn_id="turn-1", turn_index=0)
    fsm.on_turn_start()
    fsm.accept_frame(0, "digest-0", 1)

    with pytest.raises(ProtocolError, match="^sequence_conflict$"):
        fsm.accept_frame(0, "different-digest", 1)


def test_binary_sequence_resets_for_each_turn() -> None:
    first_turn = TurnStateMachine(conversation_id="conversation-1", turn_id="turn-1", turn_index=0)
    first_turn.on_turn_start()
    first_ack = first_turn.accept_frame(0, "first", 1)
    assert first_ack.highest_contiguous_sequence == 0
    _assert_turn_event_correlation(first_ack)

    second_turn = TurnStateMachine(conversation_id="conversation-1", turn_id="turn-2", turn_index=1)
    second_turn.on_turn_start()
    second_ack = second_turn.accept_frame(0, "second", 1)
    assert second_ack.highest_contiguous_sequence == 0
    _assert_turn_event_correlation(second_ack, turn_id="turn-2", turn_index=1)


def test_turn_events_cannot_be_created_without_correlation() -> None:
    with pytest.raises(ProtocolError, match="^missing_conversation_id$"):
        ServerEvent(type="ack")

    with pytest.raises(ProtocolError, match="^missing_conversation_id$"):
        TurnStateMachine(conversation_id="", turn_id="turn-1", turn_index=0)


def test_frame_size_and_turn_audio_limits_are_enforced() -> None:
    fsm = TurnStateMachine(conversation_id="conversation-1", turn_id="turn-1", turn_index=0)
    fsm.on_turn_start()

    with pytest.raises(ProtocolError, match="^frame_too_large$"):
        fsm.accept_frame(0, "too-large", MAX_FRAME_BYTES + 1)

    for sequence in range(MAX_TURN_AUDIO_BYTES // MAX_FRAME_BYTES):
        fsm.accept_frame(sequence, f"digest-{sequence}", MAX_FRAME_BYTES)
    remainder = MAX_TURN_AUDIO_BYTES % MAX_FRAME_BYTES
    if remainder:
        fsm.accept_frame(MAX_TURN_AUDIO_BYTES // MAX_FRAME_BYTES, "remainder", remainder)

    with pytest.raises(ProtocolError, match="^turn_audio_limit_exceeded$"):
        fsm.accept_frame((MAX_TURN_AUDIO_BYTES // MAX_FRAME_BYTES) + 1, "over-limit", 1)


def test_conversation_limits_enforce_turn_count_and_connection_duration() -> None:
    now = [10.0]
    limits = ConversationLimits(monotonic=lambda: now[0])

    for turn_index in range(MAX_TURNS):
        limits.start_turn(f"turn-{turn_index}")
    with pytest.raises(ProtocolError, match="^turn_limit_exceeded$"):
        limits.start_turn("turn-over-limit")

    timed_limits = ConversationLimits(monotonic=lambda: now[0])
    now[0] += MAX_CONNECTION_SECONDS + 1
    with pytest.raises(ProtocolError, match="^connection_time_exceeded$"):
        timed_limits.start_turn("turn-0")


def test_protocol_limits_are_locked() -> None:
    assert MAX_TURNS == 4
    assert MAX_FRAME_BYTES == 4096
    assert MAX_TURN_AUDIO_BYTES == 16_000 * 2 * 8
    assert MAX_CONNECTION_SECONDS == 180
