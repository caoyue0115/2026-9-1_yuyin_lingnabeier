from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from typing import Any

from src.models.conversation_v6 import (
    ConversationLimits,
    MAX_TURNS,
    ProtocolError,
    ServerEvent,
    TurnState,
    TurnStateMachine,
    TurnTransition,
    build_turn_event,
    turn_cancelled_event,
)
from src.providers.llm import stream_answer_text
from src.providers.realtime_tts import realtime_tts_health, stream_realtime_tts_chunks
from src.rag.retriever import retrieve_references
from src.services.question_router import (
    DISNEY_KNOWLEDGE_MISS,
    DYNAMIC_REFUSAL,
    QuestionRoute,
    route_question,
)
from src.services.realtime_session import (
    _split_stream_buffer,
    _stream_answer_audio,
    split_realtime_answer_text,
)
from src.settings import settings
from src.storage.conversation_v6_store import (
    BoundedAudioQueue,
    IdempotentTurnBudget,
    TurnCancelled,
)


@dataclass(frozen=True, slots=True)
class TurnRunResult:
    answer: str
    status: str = "committed"
    interrupted: bool = False
    answer_truncated: bool = False


@dataclass(slots=True)
class ConversationTurn:
    turn_id: str
    turn_index: int
    cancel_event: threading.Event
    audio: BoundedAudioQueue
    state_machine: TurnStateMachine
    question: str = ""
    answer: str = ""
    interrupted: bool = False
    question_truncated: bool = False
    answer_truncated: bool = False
    status: str = "receiving"
    future: Future[Any] | None = None
    _cancel_condition: threading.Condition = field(default_factory=threading.Condition)
    _cancellation_in_progress: bool = False
    _cancel_event_message: ServerEvent | None = None

    def join(self, timeout: float | None = None) -> bool:
        future = self.future
        if future is None:
            return True
        try:
            future.result(timeout=timeout)
        except FutureTimeoutError:
            return False
        except BaseException:
            return True
        return True

    def add_close_hook(self, hook: Callable[[], None]) -> None:
        self.audio.add_close_hook(hook)


class ConversationSession:
    """Owns one conversation's turn workers, cancellation, audio, and context."""

    def __init__(
        self,
        *,
        conversation_id: str | None = None,
        max_audio_queue_bytes: int | None = None,
        cancel_timeout_seconds: float | None = None,
        close_timeout_seconds: float | None = None,
        question_chars: int | None = None,
        answer_chars: int | None = None,
        quota_limit: int = 4,
        turn_budget_limit: int = 4,
        worker: Callable[[ConversationTurn], Any] | None = None,
    ) -> None:
        self.conversation_id = conversation_id or str(uuid.uuid4())
        self._max_audio_queue_bytes = (
            settings.conversation_v6_audio_queue_bytes
            if max_audio_queue_bytes is None
            else max_audio_queue_bytes
        )
        self._cancel_timeout_seconds = (
            settings.conversation_v6_cancel_timeout_seconds
            if cancel_timeout_seconds is None
            else cancel_timeout_seconds
        )
        self._close_timeout_seconds = (
            settings.conversation_v6_close_timeout_seconds
            if close_timeout_seconds is None
            else close_timeout_seconds
        )
        self._question_chars = (
            settings.conversation_v6_question_chars if question_chars is None else question_chars
        )
        self._answer_chars = (
            settings.conversation_v6_answer_chars if answer_chars is None else answer_chars
        )
        self._worker = worker
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="conversation-v6")
        self._turns: dict[str, ConversationTurn] = {}
        self._limits = ConversationLimits()
        self._context: list[dict[str, Any]] = []
        self._lock = threading.RLock()
        self.event_log: list[ServerEvent] = []
        self.quota = IdempotentTurnBudget(quota_limit)
        self.turn_budget = IdempotentTurnBudget(turn_budget_limit)

    @classmethod
    def for_test(cls, **kwargs: Any) -> ConversationSession:
        kwargs.setdefault("conversation_id", "conversation-test")
        return cls(**kwargs)

    @property
    def turn_count(self) -> int:
        return self._limits.turn_count

    def start_turn(self, turn_id: str, turn_index: int) -> ConversationTurn:
        if not isinstance(turn_id, str) or not turn_id:
            raise ValueError("missing_turn_id")
        with self._lock:
            existing = self._turns.get(turn_id)
            if existing is not None:
                if existing.turn_index != turn_index:
                    raise ProtocolError("turn_index_mismatch")
                return existing
            if any(
                turn.status not in {"committed", "cancelled", "asr_empty", "technical_error"}
                for turn in self._turns.values()
            ):
                raise RuntimeError("active_turn_exists")
            same_index = [turn for turn in self._turns.values() if turn.turn_index == turn_index]
            allow_index_retry = False
            if same_index:
                if len(same_index) != 1 or same_index[0].status != "asr_empty":
                    raise ProtocolError("turn_index_conflict")
                allow_index_retry = True
            elif self._limits.turn_count >= MAX_TURNS:
                raise ProtocolError("turn_limit_exceeded")
            cancel_event = threading.Event()
            audio = BoundedAudioQueue(self._max_audio_queue_bytes, cancel_event)
            state_machine = TurnStateMachine(
                turn_id,
                turn_index,
                conversation_id=self.conversation_id,
                limits=self._limits,
                allow_index_retry=allow_index_retry,
            )
            state_machine.on_turn_start()
            turn = ConversationTurn(turn_id, turn_index, cancel_event, audio, state_machine)
            self._turns[turn_id] = turn
            if self._worker is not None:
                turn.future = self._executor.submit(self._worker, turn)
            return turn

    def complete_asr_empty(self, turn_id: str) -> None:
        turn = self._require_turn(turn_id)
        with self._lock:
            if turn.state_machine.state is not TurnState.COMPLETED:
                raise ProtocolError("invalid_state")
            turn.status = "asr_empty"
            turn.audio.finish()

    def complete_technical_error(self, turn_id: str) -> None:
        turn = self._require_turn(turn_id)
        with self._lock:
            if turn.state_machine.state is not TurnState.COMPLETED:
                raise ProtocolError("invalid_state")
        cleanup_error: BaseException | None = None
        try:
            self._stop_turn_worker(turn)
        except BaseException as exc:
            cleanup_error = exc
        with self._lock:
            turn.status = "technical_error"
        if cleanup_error is not None:
            raise cleanup_error

    def process_turn(self, turn_id: str, question: str) -> Future[Any]:
        turn = self._require_turn(turn_id)
        normalized_question, question_truncated = _truncate_text(question, self._question_chars)
        if not normalized_question:
            raise ValueError("empty_question")
        with self._lock:
            if turn.future is not None:
                return turn.future
            if not self.consume_quota(turn_id) or not self.consume_turn_budget(turn_id):
                raise RuntimeError("turn_budget_exhausted")
            turn.question = normalized_question
            turn.question_truncated = question_truncated
            turn.status = "processing"
            history = self.history()
            turn.future = self._executor.submit(self._run_owned_turn, turn, history)
            return turn.future

    def consume_quota(self, turn_id: str) -> bool:
        return self.quota.consume(turn_id)

    def consume_turn_budget(self, turn_id: str) -> bool:
        return self.turn_budget.consume(turn_id)

    def check_deadline(self) -> None:
        self._limits.check_deadline(self._limits.now())

    def cancel_turn(self, turn_id: str) -> ServerEvent:
        turn = self._require_turn(turn_id)
        with turn._cancel_condition:
            while turn._cancellation_in_progress and turn._cancel_event_message is None:
                turn._cancel_condition.wait()
            if turn._cancel_event_message is not None:
                return turn._cancel_event_message
            turn._cancellation_in_progress = True

        try:
            deadline = time.monotonic() + max(0.0, self._cancel_timeout_seconds)
            turn.state_machine.begin_cancel()
            self._stop_turn_worker(turn, deadline=deadline)
            transition = turn.state_machine.on_turn_cancelled()
            event = self._cancelled_event(transition)
            with self._lock:
                turn.status = "cancelled"
                turn.interrupted = bool(turn.answer)
                if turn.answer:
                    self._commit_context(turn, interrupted=True)
                self.event_log.append(event)
            with turn._cancel_condition:
                turn._cancel_event_message = event
                turn._cancellation_in_progress = False
                turn._cancel_condition.notify_all()
            return event
        except BaseException:
            with turn._cancel_condition:
                turn._cancellation_in_progress = False
                turn._cancel_condition.notify_all()
            raise

    def commit_turn(
        self,
        turn_id: str,
        *,
        question: str,
        answer: str,
        interrupted: bool = False,
    ) -> dict[str, Any]:
        turn = self._require_turn(turn_id)
        turn.question, question_truncated = _truncate_text(question, self._question_chars)
        turn.answer, answer_truncated = _truncate_text(answer, self._answer_chars)
        turn.question_truncated = turn.question_truncated or question_truncated
        turn.answer_truncated = turn.answer_truncated or answer_truncated
        turn.interrupted = bool(interrupted)
        turn.status = "committed"
        turn.audio.finish()
        with self._lock:
            return dict(self._commit_context(turn, interrupted=turn.interrupted))

    def history(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self._context[-3:]]

    def context_status(self, turn_id: str) -> dict[str, Any] | None:
        with self._lock:
            for item in reversed(self._context):
                if item["turn_id"] == turn_id:
                    return dict(item)
        return None

    def audio_http_status(self, turn_id: str) -> int:
        with self._lock:
            turn = self._turns.get(turn_id)
        if turn is None:
            return 404
        return 410 if turn.audio.revoked else 200

    def close(self) -> None:
        with self._lock:
            active_ids = [
                turn_id
                for turn_id, turn in self._turns.items()
                if (
                    turn.status not in {"committed", "cancelled", "asr_empty", "technical_error"}
                    or (turn.future is not None and not turn.future.done())
                )
            ]
        first_error: BaseException | None = None
        try:
            for turn_id in active_ids:
                try:
                    turn = self._require_turn(turn_id)
                    if turn.state_machine.state is TurnState.COMPLETED:
                        self._stop_turn_worker(turn)
                    else:
                        self.cancel_turn(turn_id)
                except BaseException as exc:
                    if first_error is None:
                        first_error = exc
        finally:
            self._executor.shutdown(wait=False, cancel_futures=True)
        if first_error is not None:
            raise first_error

    def _stop_turn_worker(
        self,
        turn: ConversationTurn,
        *,
        deadline: float | None = None,
    ) -> None:
        if deadline is None:
            deadline = time.monotonic() + max(0.0, self._cancel_timeout_seconds)
        turn.audio.revoke()
        close_timeout = min(
            max(0.0, self._close_timeout_seconds),
            max(0.0, deadline - time.monotonic()),
        )
        turn.audio.close_providers(close_timeout)
        join_timeout = max(0.0, deadline - time.monotonic())
        if not turn.join(timeout=join_timeout):
            raise TimeoutError("turn_cancel_timeout")

    def _run_owned_turn(
        self,
        turn: ConversationTurn,
        history: list[dict[str, Any]],
    ) -> TurnRunResult:
        try:
            result = run_turn(
                turn.question,
                history,
                turn.cancel_event,
                turn.audio,
                answer_chars=self._answer_chars,
            )
        except TurnCancelled as exc:
            turn.answer, turn.answer_truncated = _truncate_text(
                exc.partial_answer, self._answer_chars
            )
            turn.interrupted = bool(turn.answer)
            raise
        turn.answer, turn.answer_truncated = _truncate_text(result.answer, self._answer_chars)
        turn.answer_truncated = turn.answer_truncated or result.answer_truncated
        self.commit_turn(
            turn.turn_id,
            question=turn.question,
            answer=turn.answer,
            interrupted=result.interrupted,
        )
        return result

    def _commit_context(self, turn: ConversationTurn, *, interrupted: bool) -> dict[str, Any]:
        question, question_truncated = _truncate_text(turn.question, self._question_chars)
        answer, answer_truncated = _truncate_text(turn.answer, self._answer_chars)
        record = {
            "turn_id": turn.turn_id,
            "question": question,
            "answer": answer,
            "status": turn.status,
            "interrupted": interrupted,
            "question_truncated": question_truncated or turn.question_truncated,
            "answer_truncated": answer_truncated or turn.answer_truncated,
        }
        for index, item in enumerate(self._context):
            if item["turn_id"] == turn.turn_id:
                self._context[index] = record
                return record
        self._context.append(record)
        return record

    def _cancelled_event(self, transition: TurnTransition) -> ServerEvent:
        built = build_turn_event(
            transition,
            conversation_id=self.conversation_id,
            turn_id=transition.turn_id,
            turn_index=transition.turn_index,
        )
        canonical = turn_cancelled_event(
            self.conversation_id,
            transition.turn_id,
            transition.turn_index,
        )
        if built.to_payload() != canonical.to_payload():
            raise RuntimeError("invalid_turn_cancelled_transition")
        return canonical

    def _require_turn(self, turn_id: str) -> ConversationTurn:
        with self._lock:
            turn = self._turns.get(turn_id)
        if turn is None:
            raise KeyError("turn_not_found")
        return turn


def run_turn(
    question: str,
    history: list[Mapping[str, Any]],
    cancel_event: threading.Event,
    audio_queue: BoundedAudioQueue,
    *,
    answer_chars: int | None = None,
) -> TurnRunResult:
    """Adapt the v5 retrieval, LLM, and TTS providers to an owned v6 turn."""
    answer_parts: list[str] = []
    _check_cancel(cancel_event, answer_parts)
    route = route_question(question)
    references: list[dict] = []
    canned_answer: str | None = None
    if route == QuestionRoute.DYNAMIC_CURRENT:
        canned_answer = DYNAMIC_REFUSAL
    elif route == QuestionRoute.DISNEY_KNOWLEDGE:
        try:
            references, top_score = retrieve_references(question, top_k=settings.top_k)
        except FileNotFoundError:
            references, top_score = [], 0.0
        _check_cancel(cancel_event, answer_parts)
        if not references or top_score < settings.min_top_score:
            canned_answer = DISNEY_KNOWLEDGE_MISS

    if canned_answer is not None:
        answer = canned_answer
        limit = settings.conversation_v6_answer_chars if answer_chars is None else answer_chars
        answer, answer_truncated = _truncate_text(answer, limit)
        checked_segments = _cancel_checked_segments([answer], cancel_event, [answer])
        audio_stream = _stream_answer_audio(checked_segments, answer)  # type: ignore[arg-type]
        _register_close_hook(audio_queue, audio_stream)
        try:
            _publish_audio(audio_stream, cancel_event, audio_queue, [answer])
        except TurnCancelled as exc:
            exc.partial_answer = answer
            raise
        audio_queue.finish()
        return TurnRunResult(answer=answer, answer_truncated=answer_truncated)

    llm_question = _question_with_history(question, history[-3:])
    llm_stream = stream_answer_text(llm_question, references)
    _register_close_hook(audio_queue, llm_stream)
    llm_iterator = iter(llm_stream)
    limit = settings.conversation_v6_answer_chars if answer_chars is None else answer_chars
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
        raise ValueError("text_limit_must_be_nonnegative")
    assembly = {"chars": 0, "pending": "", "truncated": False, "limit": limit}
    segments = _iter_llm_segments(llm_iterator, cancel_event, answer_parts, assembly)
    try:
        if realtime_tts_health():
            audio_stream: Iterable[bytes] = stream_realtime_tts_chunks(segments)
            _register_close_hook(audio_queue, audio_stream)
            _publish_audio(audio_stream, cancel_event, audio_queue, answer_parts)
        else:
            collected_segments = list(segments)
            answer = "".join(answer_parts).strip()
            if not answer:
                raise ValueError("llm_empty_text")
            audio_stream = _stream_answer_audio(collected_segments, answer)
            _register_close_hook(audio_queue, audio_stream)
            _publish_audio(audio_stream, cancel_event, audio_queue, answer_parts)
    except TurnCancelled as exc:
        exc.partial_answer = "".join(answer_parts).strip()
        raise

    answer = "".join(answer_parts).strip()
    if not answer:
        raise ValueError("llm_empty_text")
    audio_queue.finish()
    return TurnRunResult(answer=answer, answer_truncated=bool(assembly["truncated"]))


def _iter_llm_segments(
    llm_iterator: Iterable[str],
    cancel_event: threading.Event,
    answer_parts: list[str],
    assembly: dict[str, int | str | bool],
) -> Iterable[str]:
    iterator = iter(llm_iterator)
    try:
        while True:
            _check_cancel(cancel_event, answer_parts)
            try:
                chunk = next(iterator)
            except StopIteration:
                break
            _check_cancel(cancel_event, answer_parts)
            if not chunk:
                continue
            answer_chars = int(assembly["chars"])
            remaining_chars = int(assembly["limit"]) - answer_chars
            if remaining_chars <= 0:
                assembly["truncated"] = True
                break
            bounded_chunk = chunk[:remaining_chars]
            answer_parts.append(bounded_chunk)
            assembly["chars"] = answer_chars + len(bounded_chunk)
            pending = str(assembly["pending"]) + "".join(bounded_chunk.split())
            ready, pending = _split_stream_buffer(
                pending,
                min_chars=settings.realtime_tts_min_chars,
                max_chars=settings.realtime_tts_max_chars,
            )
            assembly["pending"] = pending
            for segment in ready:
                _check_cancel(cancel_event, answer_parts)
                if segment:
                    yield segment
            if len(bounded_chunk) < len(chunk):
                assembly["truncated"] = True
                break

        _check_cancel(cancel_event, answer_parts)
        pending = str(assembly["pending"])
        if pending:
            for segment in split_realtime_answer_text(
                pending,
                min_chars=settings.realtime_tts_min_chars,
                max_chars=settings.realtime_tts_max_chars,
            ):
                _check_cancel(cancel_event, answer_parts)
                if segment:
                    yield segment
            assembly["pending"] = ""
    finally:
        _close_provider(iterator)


def _publish_audio(
    audio_stream: Iterable[bytes],
    cancel_event: threading.Event,
    audio_queue: BoundedAudioQueue,
    answer_parts: list[str],
) -> None:
    iterator = iter(audio_stream)
    try:
        while True:
            _check_cancel(cancel_event, answer_parts)
            try:
                chunk = next(iterator)
            except StopIteration:
                return
            _check_cancel(cancel_event, answer_parts)
            if chunk:
                audio_queue.put(chunk)
    finally:
        _close_provider(iterator)


def _cancel_checked_segments(
    segments: Iterable[str],
    cancel_event: threading.Event,
    answer_parts: list[str],
) -> Iterable[str]:
    for segment in segments:
        _check_cancel(cancel_event, answer_parts)
        yield segment


def _register_close_hook(audio_queue: BoundedAudioQueue, provider: object) -> None:
    close = getattr(provider, "close", None)
    if callable(close):
        audio_queue.add_close_hook(close)


def _close_provider(provider: object) -> None:
    close = getattr(provider, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


def _check_cancel(cancel_event: threading.Event, answer_parts: list[str]) -> None:
    if cancel_event.is_set():
        raise TurnCancelled("".join(answer_parts).strip())


def _question_with_history(question: str, history: list[Mapping[str, Any]]) -> str:
    if not history:
        return question
    lines = ["Previous conversation context:"]
    for item in history:
        interrupted = "true" if item.get("interrupted") else "false"
        lines.append(f"Q: {item.get('question', '')}")
        lines.append(f"A (interrupted={interrupted}): {item.get('answer', '')}")
    lines.append(f"Current question: {question}")
    return "\n".join(lines)


def _truncate_text(value: str, limit: int) -> tuple[str, bool]:
    normalized = str(value or "").strip()
    if limit < 0:
        raise ValueError("text_limit_must_be_nonnegative")
    if len(normalized) <= limit:
        return normalized, False
    return normalized[:limit], True
