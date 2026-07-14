from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


MAX_TURNS = 4
MAX_FRAME_BYTES = 4096
MAX_TURN_AUDIO_BYTES = 16_000 * 2 * 8
MAX_CONNECTION_SECONDS = 180


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
class ServerEvent:
    type: str
    conversation_id: str | None = None
    turn_id: str | None = None
    turn_index: int | None = None
    outcome: TurnOutcome | None = None
    highest_contiguous_sequence: int | None = None
    data: Mapping[str, Any] = field(default_factory=dict)

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
        return ClientControl(
            type=message_type,
            client_conversation_id=client_conversation_id,
            data=_extra_payload(payload),
        )

    conversation_id = _require_nonempty_string(payload.get("conversation_id"), "conversation_id")
    if message_type == "conversation_end":
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


class TurnStateMachine:
    """Pure per-turn state and binary frame sequencing for the v6 protocol."""

    def __init__(
        self,
        turn_id: str,
        turn_index: int,
        conversation_id: str | None = None,
    ) -> None:
        self.turn_id = _require_nonempty_string(turn_id, "turn_id")
        self.turn_index = _validate_turn_index(turn_index)
        self.conversation_id = conversation_id
        if conversation_id is not None:
            _require_nonempty_string(conversation_id, "conversation_id")
        self.state = TurnState.IDLE
        self._frame_digests: dict[int, str] = {}
        self._highest_contiguous_sequence = -1
        self._cancelled_event: ServerEvent | None = None

    @property
    def is_terminal(self) -> bool:
        return self.state in {TurnState.COMPLETED, TurnState.CANCELLED}

    @property
    def highest_contiguous_sequence(self) -> int:
        return self._highest_contiguous_sequence

    def validate_correlation(self, message: ClientControl | ServerEvent) -> None:
        if self.conversation_id is None:
            raise ProtocolError("missing_conversation_id")
        if message.conversation_id != self.conversation_id:
            raise ProtocolError("conversation_mismatch")
        if message.turn_id != self.turn_id:
            raise ProtocolError("turn_mismatch")
        if message.turn_index != self.turn_index:
            raise ProtocolError("turn_index_mismatch")

    def on_turn_start(self, control: ClientControl | None = None) -> ServerEvent:
        self._validate_control(control, "turn_start")
        self._require_state(TurnState.IDLE)
        self._frame_digests.clear()
        self._highest_contiguous_sequence = -1
        self.state = TurnState.RECEIVING
        return self._event("ack", data={"acknowledged_type": "turn_start"})

    def accept_frame(self, sequence: int, digest: str) -> ServerEvent:
        self._require_state(TurnState.RECEIVING)
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
            raise ProtocolError("invalid_sequence")
        _require_nonempty_string(digest, "digest")

        existing_digest = self._frame_digests.get(sequence)
        if existing_digest is not None:
            if existing_digest != digest:
                raise ProtocolError("sequence_conflict")
            return self._event("ack", highest_contiguous_sequence=self._highest_contiguous_sequence)

        self._frame_digests[sequence] = digest
        while self._highest_contiguous_sequence + 1 in self._frame_digests:
            self._highest_contiguous_sequence += 1
        return self._event("ack", highest_contiguous_sequence=self._highest_contiguous_sequence)

    def on_turn_end(self, control: ClientControl | None = None) -> None:
        self._validate_control(control, "turn_end")
        self._require_state(TurnState.RECEIVING)
        self.state = TurnState.PROCESSING

    def on_asr_final(self, text: str) -> ServerEvent:
        self._require_state(TurnState.PROCESSING)
        self.state = TurnState.RESULT_READY
        return self._event("asr_final", data={"text": text})

    def on_asr_empty(self) -> ServerEvent:
        self._require_state(TurnState.PROCESSING)
        self.state = TurnState.COMPLETED
        return self._event("turn_complete", outcome=TurnOutcome.ASR_EMPTY)

    def on_turn_result(self, *, session_id: str, audio_stream_url: str) -> ServerEvent:
        self._require_state(TurnState.RESULT_READY)
        self.state = TurnState.PLAYING
        return self._event(
            "turn_result",
            data={"session_id": session_id, "audio_stream_url": audio_stream_url, "status": "ready"},
        )

    def on_turn_playback_complete(self, control: ClientControl | None = None) -> ServerEvent:
        self._validate_control(control, "turn_playback_complete")
        self._require_state(TurnState.PLAYING)
        self.state = TurnState.COMPLETED
        return self._event("turn_complete", outcome=TurnOutcome.PLAYED)

    def on_technical_error(self) -> ServerEvent:
        return self._complete_error(TurnOutcome.TECHNICAL_ERROR)

    def on_rejected(self) -> ServerEvent:
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

    def on_turn_cancelled(self) -> ServerEvent:
        if self.state is TurnState.CANCELLED:
            assert self._cancelled_event is not None
            return self._cancelled_event
        self._require_state(TurnState.CANCELLING)
        self.state = TurnState.CANCELLED
        self._cancelled_event = self._event("turn_cancelled")
        return self._cancelled_event

    def on_turn_cancel(self, control: ClientControl | None = None) -> ServerEvent:
        self.begin_cancel(control)
        return self.on_turn_cancelled()

    def _complete_error(self, outcome: TurnOutcome) -> ServerEvent:
        if self.is_terminal or self.state is TurnState.CANCELLING:
            raise ProtocolError("invalid_state")
        self.state = TurnState.COMPLETED
        return self._event("turn_complete", outcome=outcome)

    def _validate_control(self, control: ClientControl | None, expected_type: str) -> None:
        if control is None:
            return
        if control.type != expected_type:
            raise ProtocolError("unexpected_control")
        self.validate_correlation(control)

    def _require_state(self, expected: TurnState) -> None:
        if self.state is not expected:
            raise ProtocolError("invalid_state")

    def _event(
        self,
        event_type: str,
        *,
        outcome: TurnOutcome | None = None,
        highest_contiguous_sequence: int | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> ServerEvent:
        return ServerEvent(
            type=event_type,
            conversation_id=self.conversation_id,
            turn_id=self.turn_id,
            turn_index=self.turn_index,
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
