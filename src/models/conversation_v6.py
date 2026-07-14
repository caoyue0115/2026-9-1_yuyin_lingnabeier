from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from time import monotonic as default_monotonic
from typing import Any, Callable, Mapping


MAX_TURNS = 4
MAX_FRAME_BYTES = 4096
MAX_TURN_AUDIO_BYTES = 16_000 * 2 * 8
MAX_CONNECTION_SECONDS = 180
SUPPORTED_AUDIO_FORMATS = frozenset({"opus"})
SUPPORTED_ANSWER_MODES = frozenset({"streaming"})


class TurnState(StrEnum):
    IDLE = "idle"
    RECEIVING = "receiving"
    PROCESSING = "processing"
    RESULT_READY = "result_ready"
    PLAYING = "playing"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TurnOutcome(StrEnum):
    PLAYED = "played"
    ASR_EMPTY = "asr_empty"
    TECHNICAL_ERROR = "technical_error"
    REJECTED = "rejected"


class ProtocolError(ValueError):
    """A stable v6 protocol error code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


_TURN_CONTROLS = frozenset({"turn_start", "turn_end", "turn_cancel", "turn_playback_complete"})
_CONVERSATION_CONTROLS = frozenset({"conversation_start", "conversation_end"})
_TURN_EVENTS = frozenset({"ack", "asr_final", "turn_result", "turn_complete", "turn_cancelled"})


@dataclass(frozen=True, slots=True)
class ClientControl:
    type: str
    conversation_id: str | None = None
    turn_id: str | None = None
    turn_index: int | None = None
    client_conversation_id: str | None = None
    data: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TurnTransition:
    """Internal FSM output that cannot be serialized onto the wire."""

    type: str
    outcome: TurnOutcome | None = None
    highest_contiguous_sequence: int | None = None
    data: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ServerEvent:
    type: str
    conversation_id: str | None = None
    turn_id: str | None = None
    turn_index: int | None = None
    outcome: TurnOutcome | None = None
    highest_contiguous_sequence: int | None = None
    data: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.data, Mapping):
            raise ProtocolError("invalid_event_data")
        if self.type in _TURN_EVENTS:
            _require_turn_correlation(self.conversation_id, self.turn_id, self.turn_index)
        elif self.type in {"conversation_ready", "conversation_done", "error"}:
            _require_nonempty_string(self.conversation_id, "conversation_id")
        _validate_server_event(self)

    def to_payload(self) -> dict[str, Any]:
        if self.type in _TURN_EVENTS:
            _require_turn_correlation(self.conversation_id, self.turn_id, self.turn_index)
        elif self.type in {"conversation_ready", "conversation_done", "error"}:
            _require_nonempty_string(self.conversation_id, "conversation_id")

        payload: dict[str, Any] = {"type": self.type, **self.data}
        if self.conversation_id is not None:
            payload["conversation_id"] = self.conversation_id
        if self.turn_id is not None:
            payload["turn_id"] = self.turn_id
        if self.turn_index is not None:
            payload["turn_index"] = self.turn_index
        if self.outcome is not None:
            payload["outcome"] = self.outcome.value
        if self.highest_contiguous_sequence is not None:
            payload["highest_contiguous_sequence"] = self.highest_contiguous_sequence
        return payload


def parse_client_control(payload: Mapping[str, Any]) -> ClientControl:
    """Validate one JSON client control without applying it to a conversation."""
    if not isinstance(payload, Mapping):
        raise ProtocolError("invalid_control")

    message_type = payload.get("type")
    if message_type not in _TURN_CONTROLS | _CONVERSATION_CONTROLS:
        raise ProtocolError("unknown_control")

    if message_type == "conversation_start":
        client_conversation_id = _require_nonempty_string(
            payload.get("client_conversation_id"), "client_conversation_id"
        )
        if payload.get("conversation_id") is not None:
            raise ProtocolError("unexpected_conversation_id")
        _require_nonempty_string(payload.get("device_id"), "device_id")
        audio_format = _require_nonempty_string(payload.get("audio_format"), "audio_format")
        if audio_format not in SUPPORTED_AUDIO_FORMATS:
            raise ProtocolError("unsupported_audio_format")
        if payload.get("protocol_version") != "v6":
            raise ProtocolError("unsupported_protocol_version")
        answer_mode = _require_nonempty_string(payload.get("answer_mode"), "answer_mode")
        if answer_mode not in SUPPORTED_ANSWER_MODES:
            raise ProtocolError("unsupported_answer_mode")
        return ClientControl(
            type=message_type,
            client_conversation_id=client_conversation_id,
            data=_extra_payload(payload),
        )

    conversation_id = _require_nonempty_string(payload.get("conversation_id"), "conversation_id")
    if message_type == "conversation_end":
        _require_nonempty_string(payload.get("reason"), "reason")
        return ClientControl(type=message_type, conversation_id=conversation_id, data=_extra_payload(payload))

    turn_id, turn_index = _parse_turn_correlation(payload)
    return ClientControl(
        type=message_type,
        conversation_id=conversation_id,
        turn_id=turn_id,
        turn_index=turn_index,
        data=_extra_payload(payload),
    )


def conversation_ready_event(client_conversation_id: str, conversation_id: str) -> ServerEvent:
    return ServerEvent(
        type="conversation_ready",
        conversation_id=_require_nonempty_string(conversation_id, "conversation_id"),
        data={
            "client_conversation_id": _require_nonempty_string(
                client_conversation_id, "client_conversation_id"
            )
        },
    )


def conversation_done_event(conversation_id: str) -> ServerEvent:
    return ServerEvent(
        type="conversation_done",
        conversation_id=_require_nonempty_string(conversation_id, "conversation_id"),
    )


def error_event(conversation_id: str, code: str, message: str | None = None) -> ServerEvent:
    data: dict[str, Any] = {"code": _require_nonempty_string(code, "code")}
    if message is not None:
        data["message"] = message
    return ServerEvent(
        type="error",
        conversation_id=_require_nonempty_string(conversation_id, "conversation_id"),
        data=data,
    )


def ack_event(
    conversation_id: str,
    turn_id: str,
    turn_index: int,
    message_type: str,
    highest_contiguous_sequence: int | None = None,
) -> ServerEvent:
    data = {"acknowledged_type": _require_nonempty_string(message_type, "message_type")}
    return _turn_event(
        "ack",
        conversation_id,
        turn_id,
        turn_index,
        highest_contiguous_sequence=highest_contiguous_sequence,
        data=data,
    )


def asr_final_event(
    conversation_id: str, turn_id: str, turn_index: int, text: str
) -> ServerEvent:
    return _turn_event(
        "asr_final", conversation_id, turn_id, turn_index, data={"text": text}
    )


def turn_result_event(
    conversation_id: str,
    turn_id: str,
    turn_index: int,
    *,
    session_id: str,
    audio_stream_url: str,
) -> ServerEvent:
    return _turn_event(
        "turn_result",
        conversation_id,
        turn_id,
        turn_index,
        data={"session_id": session_id, "audio_stream_url": audio_stream_url, "status": "ready"},
    )


def turn_complete_event(
    conversation_id: str, turn_id: str, turn_index: int, outcome: TurnOutcome
) -> ServerEvent:
    return _turn_event("turn_complete", conversation_id, turn_id, turn_index, outcome=outcome)


def turn_cancelled_event(conversation_id: str, turn_id: str, turn_index: int) -> ServerEvent:
    return _turn_event("turn_cancelled", conversation_id, turn_id, turn_index)


def build_turn_event(
    transition: TurnTransition,
    *,
    conversation_id: str,
    turn_id: str,
    turn_index: int,
) -> ServerEvent:
    if not isinstance(transition, TurnTransition) or transition.type not in _TURN_EVENTS:
        raise ProtocolError("invalid_turn_transition")
    return _turn_event(
        transition.type,
        conversation_id,
        turn_id,
        turn_index,
        outcome=transition.outcome,
        highest_contiguous_sequence=transition.highest_contiguous_sequence,
        data=transition.data,
    )


class ConversationLimits:
    """Connection-scoped turn and duration limits with an injectable clock."""

    def __init__(
        self,
        *,
        started_at: float | None = None,
        monotonic: Callable[[], float] = default_monotonic,
    ) -> None:
        self._monotonic = monotonic
        self._started_at = monotonic() if started_at is None else _validate_timestamp(started_at)
        self._last_activity_at = self._started_at
        self._turn_ids: set[str] = set()

    @property
    def turn_count(self) -> int:
        return len(self._turn_ids)

    def check_deadline(self, now: float) -> None:
        now = _validate_timestamp(now)
        if now - self._started_at > MAX_CONNECTION_SECONDS:
            raise ProtocolError("connection_time_exceeded")

    def note_activity(self, now: float) -> None:
        self.check_deadline(now)
        self._last_activity_at = now

    def start_turn(self, turn_id: str, *, now: float | None = None) -> None:
        self.note_activity(self._monotonic() if now is None else now)
        turn_id = _require_nonempty_string(turn_id, "turn_id")
        if turn_id in self._turn_ids:
            return
        if len(self._turn_ids) >= MAX_TURNS:
            raise ProtocolError("turn_limit_exceeded")
        self._turn_ids.add(turn_id)


class TurnStateMachine:
    """Pure per-turn state and binary frame sequencing for the v6 protocol."""

    def __init__(self, turn_id: str, turn_index: int) -> None:
        self.turn_id = _require_nonempty_string(turn_id, "turn_id")
        self.turn_index = _validate_turn_index(turn_index)
        self.state = TurnState.IDLE
        self._frame_digests: dict[int, str] = {}
        self._highest_contiguous_sequence = -1
        self._audio_bytes = 0
        self._cancelled_event: TurnTransition | None = None

    @property
    def is_terminal(self) -> bool:
        return self.state in {TurnState.COMPLETED, TurnState.CANCELLED}

    @property
    def highest_contiguous_sequence(self) -> int:
        return self._highest_contiguous_sequence

    @property
    def audio_bytes(self) -> int:
        return self._audio_bytes

    def validate_correlation(
        self, message: ClientControl | ServerEvent, *, conversation_id: str
    ) -> None:
        if message.conversation_id != _require_nonempty_string(conversation_id, "conversation_id"):
            raise ProtocolError("conversation_mismatch")
        if message.turn_id != self.turn_id:
            raise ProtocolError("turn_mismatch")
        if message.turn_index != self.turn_index:
            raise ProtocolError("turn_index_mismatch")

    def on_turn_start(self, control: ClientControl | None = None) -> TurnTransition:
        self._validate_control(control, "turn_start")
        self._require_state(TurnState.IDLE)
        self._frame_digests.clear()
        self._highest_contiguous_sequence = -1
        self._audio_bytes = 0
        self.state = TurnState.RECEIVING
        return self._transition("ack", data={"acknowledged_type": "turn_start"})

    def accept_frame(self, sequence: int, digest: str) -> TurnTransition:
        self._require_state(TurnState.RECEIVING)
        duplicate = self._check_duplicate(sequence, digest)
        if duplicate is not None:
            return duplicate
        return self._record_frame(sequence, digest, frame_bytes=0)

    def ingest_frame(
        self, sequence: int, digest: str, payload_or_size: bytes | bytearray | memoryview | int
    ) -> TurnTransition:
        """Accept a binary payload after enforcing per-frame and per-turn byte limits."""
        self._require_state(TurnState.RECEIVING)
        duplicate = self._check_duplicate(sequence, digest)
        if duplicate is not None:
            return duplicate
        frame_bytes = _frame_byte_count(payload_or_size)
        if frame_bytes > MAX_FRAME_BYTES:
            raise ProtocolError("frame_too_large")
        if self._audio_bytes + frame_bytes > MAX_TURN_AUDIO_BYTES:
            raise ProtocolError("turn_audio_limit_exceeded")
        return self._record_frame(sequence, digest, frame_bytes=frame_bytes)

    def on_turn_end(self, control: ClientControl | None = None) -> None:
        self._validate_control(control, "turn_end")
        self._require_state(TurnState.RECEIVING)
        self.state = TurnState.PROCESSING

    def on_asr_final(self, text: str) -> TurnTransition:
        self._require_state(TurnState.PROCESSING)
        self.state = TurnState.RESULT_READY
        return self._transition("asr_final", data={"text": text})

    def on_asr_empty(self) -> TurnTransition:
        self._require_state(TurnState.PROCESSING)
        self.state = TurnState.COMPLETED
        return self._transition("turn_complete", outcome=TurnOutcome.ASR_EMPTY)

    def on_turn_result(self, *, session_id: str, audio_stream_url: str) -> TurnTransition:
        self._require_state(TurnState.RESULT_READY)
        self.state = TurnState.PLAYING
        return self._transition(
            "turn_result",
            data={"session_id": session_id, "audio_stream_url": audio_stream_url, "status": "ready"},
        )

    def on_turn_playback_complete(self, control: ClientControl | None = None) -> TurnTransition:
        self._validate_control(control, "turn_playback_complete")
        self._require_state(TurnState.PLAYING)
        self.state = TurnState.COMPLETED
        return self._transition("turn_complete", outcome=TurnOutcome.PLAYED)

    def on_technical_error(self) -> TurnTransition:
        return self._complete_error(TurnOutcome.TECHNICAL_ERROR)

    def on_rejected(self) -> TurnTransition:
        return self._complete_error(TurnOutcome.REJECTED)

    def begin_cancel(self, control: ClientControl | None = None) -> None:
        self._validate_control(control, "turn_cancel")
        if self.state is TurnState.CANCELLED:
            return
        if self.state not in {
            TurnState.RECEIVING,
            TurnState.PROCESSING,
            TurnState.RESULT_READY,
            TurnState.PLAYING,
            TurnState.CANCELLING,
        }:
            raise ProtocolError("invalid_state")
        self.state = TurnState.CANCELLING

    def on_turn_cancelled(self) -> TurnTransition:
        if self.state is TurnState.CANCELLED:
            assert self._cancelled_event is not None
            return self._cancelled_event
        self._require_state(TurnState.CANCELLING)
        self.state = TurnState.CANCELLED
        self._cancelled_event = self._transition("turn_cancelled")
        return self._cancelled_event

    def on_turn_cancel(self, control: ClientControl | None = None) -> TurnTransition:
        self.begin_cancel(control)
        return self.on_turn_cancelled()

    def _complete_error(self, outcome: TurnOutcome) -> TurnTransition:
        if self.is_terminal or self.state is TurnState.CANCELLING:
            raise ProtocolError("invalid_state")
        self.state = TurnState.COMPLETED
        return self._transition("turn_complete", outcome=outcome)

    def _validate_control(self, control: ClientControl | None, expected_type: str) -> None:
        if control is None:
            return
        if control.type != expected_type:
            raise ProtocolError("unexpected_control")
        _require_turn_correlation(control.conversation_id, control.turn_id, control.turn_index)
        if control.turn_id != self.turn_id:
            raise ProtocolError("turn_mismatch")
        if control.turn_index != self.turn_index:
            raise ProtocolError("turn_index_mismatch")

    def _require_state(self, expected: TurnState) -> None:
        if self.state is not expected:
            raise ProtocolError("invalid_state")

    def _check_duplicate(self, sequence: int, digest: str) -> TurnTransition | None:
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
            raise ProtocolError("invalid_sequence")
        _require_nonempty_string(digest, "digest")
        existing_digest = self._frame_digests.get(sequence)
        if existing_digest is None:
            return None
        if existing_digest != digest:
            raise ProtocolError("sequence_conflict")
        return self._transition(
            "ack",
            highest_contiguous_sequence=self._highest_contiguous_sequence,
            data={"acknowledged_type": "binary"},
        )

    def _record_frame(self, sequence: int, digest: str, *, frame_bytes: int) -> TurnTransition:
        self._frame_digests[sequence] = digest
        self._audio_bytes += frame_bytes
        while self._highest_contiguous_sequence + 1 in self._frame_digests:
            self._highest_contiguous_sequence += 1
        return self._transition(
            "ack",
            highest_contiguous_sequence=self._highest_contiguous_sequence,
            data={"acknowledged_type": "binary"},
        )

    def _transition(
        self,
        transition_type: str,
        *,
        outcome: TurnOutcome | None = None,
        highest_contiguous_sequence: int | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> TurnTransition:
        return TurnTransition(
            type=transition_type,
            outcome=outcome,
            highest_contiguous_sequence=highest_contiguous_sequence,
            data={} if data is None else data,
        )


def _turn_event(
    event_type: str,
    conversation_id: str,
    turn_id: str,
    turn_index: int,
    *,
    outcome: TurnOutcome | None = None,
    highest_contiguous_sequence: int | None = None,
    data: Mapping[str, Any] | None = None,
) -> ServerEvent:
    conversation_id, turn_id, turn_index = _require_turn_correlation(
        conversation_id, turn_id, turn_index
    )
    return ServerEvent(
        type=event_type,
        conversation_id=conversation_id,
        turn_id=turn_id,
        turn_index=turn_index,
        outcome=outcome,
        highest_contiguous_sequence=highest_contiguous_sequence,
        data={} if data is None else data,
    )


def _parse_turn_correlation(payload: Mapping[str, Any]) -> tuple[str, int]:
    return _require_turn_correlation(
        payload.get("conversation_id"), payload.get("turn_id"), payload.get("turn_index")
    )[1:]


def _require_turn_correlation(
    conversation_id: Any, turn_id: Any, turn_index: Any
) -> tuple[str, str, int]:
    return (
        _require_nonempty_string(conversation_id, "conversation_id"),
        _require_nonempty_string(turn_id, "turn_id"),
        _validate_turn_index(turn_index),
    )


def _validate_server_event(event: ServerEvent) -> None:
    if event.type == "turn_complete":
        if not isinstance(event.outcome, TurnOutcome):
            raise ProtocolError("invalid_turn_outcome")
        return
    if event.type == "ack":
        _require_event_data_string(event.data, "acknowledged_type")
        return
    if event.type == "asr_final":
        _require_event_data_string(event.data, "text")
        return
    if event.type == "turn_result":
        _require_event_data_string(event.data, "session_id")
        _require_event_data_string(event.data, "audio_stream_url")
        return
    if event.type == "conversation_ready":
        _require_event_data_string(event.data, "client_conversation_id")
        return
    if event.type == "error":
        _require_event_data_string(event.data, "code")


def _require_event_data_string(data: Mapping[str, Any], field_name: str) -> str:
    return _require_nonempty_string(data.get(field_name), field_name)


def _frame_byte_count(payload_or_size: bytes | bytearray | memoryview | int) -> int:
    if isinstance(payload_or_size, int) and not isinstance(payload_or_size, bool):
        if payload_or_size < 0:
            raise ProtocolError("invalid_frame_bytes")
        return payload_or_size
    if isinstance(payload_or_size, (bytes, bytearray, memoryview)):
        return len(payload_or_size)
    raise ProtocolError("invalid_frame_bytes")


def _validate_timestamp(value: Any) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ProtocolError("invalid_timestamp")
    return float(value)


def _require_nonempty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProtocolError(f"missing_{field_name}")
    return value


def _validate_turn_index(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value < MAX_TURNS:
        raise ProtocolError("invalid_turn_index")
    return value


def _extra_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    reserved = {"type", "conversation_id", "turn_id", "turn_index", "client_conversation_id"}
    return {key: value for key, value in payload.items() if key not in reserved}
