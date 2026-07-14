from __future__ import annotations

import threading
import time

import pytest

from src.models.conversation_v6 import ServerEvent
from src.services import conversation_v6 as conversation_service
from src.services.conversation_v6 import ConversationSession, TurnRunResult
from src.settings import Settings
from src.storage.conversation_v6_store import (
    BoundedAudioQueue,
    IdempotentTurnBudget,
    TurnCancelled,
)


def test_audio_queue_applies_backpressure_by_bytes() -> None:
    cancel_event = threading.Event()
    audio = BoundedAudioQueue(max_bytes=8, cancel_event=cancel_event)
    audio.put(b"12345678")
    producer_finished = threading.Event()

    def produce() -> None:
        audio.put(b"9")
        producer_finished.set()

    producer = threading.Thread(target=produce)
    producer.start()
    assert not producer_finished.wait(0.05)
    assert audio.byte_count == 8

    assert audio.get() == b"12345678"
    assert producer_finished.wait(0.5)
    producer.join(timeout=0.5)
    assert audio.byte_count == 1


def test_cancel_wakes_a_producer_blocked_on_capacity() -> None:
    cancel_event = threading.Event()
    audio = BoundedAudioQueue(max_bytes=4, cancel_event=cancel_event)
    audio.put(b"1234")
    producer_finished = threading.Event()
    error: list[BaseException] = []

    def produce() -> None:
        try:
            audio.put(b"5")
        except BaseException as exc:
            error.append(exc)
        finally:
            producer_finished.set()

    producer = threading.Thread(target=produce)
    producer.start()
    assert not producer_finished.wait(0.05)

    audio.revoke()

    assert producer_finished.wait(0.5)
    producer.join(timeout=0.5)
    assert len(error) == 1
    assert isinstance(error[0], TurnCancelled)
    assert audio.revoked
    assert audio.byte_count == 0


def test_cancel_is_a_barrier_and_revokes_audio() -> None:
    session = ConversationSession.for_test(max_audio_queue_bytes=8)
    turn = session.start_turn("t1", 0)
    turn.audio.put(b"12345678")
    session.cancel_turn("t1")
    assert turn.join(timeout=2.0)
    assert turn.audio.revoked
    assert session.event_log[-1].type == "turn_cancelled"
    assert session.audio_http_status("t1") == 410


def test_cancel_is_idempotent_and_emits_one_terminal_event() -> None:
    session = ConversationSession.for_test(max_audio_queue_bytes=8)
    turn = session.start_turn("t1", 0)

    first = session.cancel_turn("t1")
    second = session.cancel_turn("t1")

    assert first is second
    assert turn.join(timeout=0.1)
    assert [event.type for event in session.event_log] == ["turn_cancelled"]


def test_cancel_closes_provider_and_joins_worker_within_two_seconds() -> None:
    worker_started = threading.Event()
    worker_stopped = threading.Event()
    provider_closed = threading.Event()

    def worker(turn) -> None:
        turn.add_close_hook(provider_closed.set)
        worker_started.set()
        turn.cancel_event.wait()
        worker_stopped.set()

    session = ConversationSession.for_test(max_audio_queue_bytes=8, worker=worker)
    turn = session.start_turn("t1", 0)
    assert worker_started.wait(0.5)

    started = time.monotonic()
    session.cancel_turn("t1")
    elapsed = time.monotonic() - started

    assert elapsed <= 2.0
    assert provider_closed.is_set()
    assert worker_stopped.is_set()
    assert turn.join(timeout=0.0)


def test_cancel_timeout_bounds_close_hooks_and_worker_join_together() -> None:
    worker_started = threading.Event()
    close_finished = threading.Event()

    def close_provider() -> None:
        time.sleep(0.1)
        close_finished.set()

    def worker(turn) -> None:
        turn.add_close_hook(close_provider)
        worker_started.set()
        turn.cancel_event.wait()
        close_finished.wait()
        time.sleep(0.1)

    session = ConversationSession.for_test(
        max_audio_queue_bytes=8,
        cancel_timeout_seconds=0.1,
        close_timeout_seconds=0.1,
        worker=worker,
    )
    turn = session.start_turn("t1", 0)
    assert worker_started.wait(0.5)

    started = time.monotonic()
    with pytest.raises(TimeoutError, match="turn_cancel_timeout"):
        session.cancel_turn("t1")
    elapsed = time.monotonic() - started

    assert elapsed < 0.3
    assert turn.join(timeout=0.5)
    assert session.event_log == []


def test_context_uses_only_three_committed_turns_and_marks_partial_answer() -> None:
    session = ConversationSession.for_test(
        max_audio_queue_bytes=8,
        question_chars=5,
        answer_chars=7,
    )
    for index in range(4):
        turn_id = f"t{index}"
        session.start_turn(turn_id, index)
        session.commit_turn(
            turn_id,
            question=f"question-{index}",
            answer=f"answer-{index}",
            interrupted=index == 3,
        )

    history = session.history()

    assert [item["turn_id"] for item in history] == ["t1", "t2", "t3"]
    assert history[-1] == {
        "turn_id": "t3",
        "question": "quest",
        "answer": "answer-",
        "status": "committed",
        "interrupted": True,
        "question_truncated": True,
        "answer_truncated": True,
    }


def test_cancelled_partial_answer_is_committed_as_interrupted_context(monkeypatch) -> None:
    worker_started = threading.Event()

    def cancelled_run(question, history, cancel_event, audio_queue):
        worker_started.set()
        cancel_event.wait()
        raise TurnCancelled("partial")

    monkeypatch.setattr(conversation_service, "run_turn", cancelled_run)
    session = ConversationSession.for_test(max_audio_queue_bytes=8)
    session.start_turn("t1", 0)
    session.process_turn("t1", "question")
    assert worker_started.wait(0.5)

    session.cancel_turn("t1")

    assert session.context_status("t1") == {
        "turn_id": "t1",
        "question": "question",
        "answer": "partial",
        "status": "cancelled",
        "interrupted": True,
        "question_truncated": False,
        "answer_truncated": False,
    }


def test_quota_and_turn_budget_are_idempotent_by_turn_id() -> None:
    quota = IdempotentTurnBudget(limit=1)
    turn_budget = IdempotentTurnBudget(limit=1)

    assert quota.consume("t1")
    assert quota.consume("t1")
    assert not quota.consume("t2")
    assert not quota.consume("t2")
    assert quota.used == 1

    assert turn_budget.consume("t1")
    assert turn_budget.consume("t1")
    assert not turn_budget.consume("t2")
    assert turn_budget.used == 1


def test_cancelled_turn_uses_task1_event_shape() -> None:
    session = ConversationSession.for_test(conversation_id="conversation-test")
    session.start_turn("t1", 0)

    event = session.cancel_turn("t1")

    assert isinstance(event, ServerEvent)
    assert event.to_payload() == {
        "type": "turn_cancelled",
        "conversation_id": "conversation-test",
        "turn_id": "t1",
        "turn_index": 0,
    }


def test_v6_settings_defaults() -> None:
    configured = Settings(_env_file=None)

    assert configured.conversation_v6_audio_queue_bytes == 256 * 1024
    assert configured.conversation_v6_cancel_timeout_seconds == 2.0
    assert configured.conversation_v6_close_timeout_seconds == 2.0
    assert configured.conversation_v6_question_chars == 512
    assert configured.conversation_v6_answer_chars == 4096


def test_oversized_audio_chunk_is_rejected_without_waiting() -> None:
    audio = BoundedAudioQueue(max_bytes=4, cancel_event=threading.Event())

    with pytest.raises(ValueError, match="audio_chunk_exceeds_queue_capacity"):
        audio.put(b"12345")


def test_run_turn_checks_cancel_before_each_fallback_tts_segment(monkeypatch) -> None:
    cancel_event = threading.Event()
    audio = BoundedAudioQueue(max_bytes=16, cancel_event=cancel_event)
    synthesized: list[str] = []
    original_put = audio.put

    def cancel_after_first_write(chunk: bytes) -> None:
        original_put(chunk)
        cancel_event.set()

    def synthesize_segments(segments, answer):
        for segment in segments:
            synthesized.append(segment)
            yield b"audio"

    monkeypatch.setattr(
        conversation_service,
        "retrieve_references",
        lambda question, top_k: ([{"source_title": "s", "snippet": "x"}], 1.0),
    )
    monkeypatch.setattr(conversation_service, "stream_answer_text", lambda question, refs: iter(["a" * 80]))
    monkeypatch.setattr(conversation_service, "realtime_tts_health", lambda: False)
    monkeypatch.setattr(conversation_service, "_stream_answer_audio", synthesize_segments)
    monkeypatch.setattr(audio, "put", cancel_after_first_write)

    with pytest.raises(TurnCancelled):
        conversation_service.run_turn("question", [], cancel_event, audio)

    assert synthesized == ["a" * 40]


def test_run_turn_bounds_answer_while_consuming_llm_chunks(monkeypatch) -> None:
    cancel_event = threading.Event()
    audio = BoundedAudioQueue(max_bytes=16, cancel_event=cancel_event)
    monkeypatch.setattr(
        conversation_service,
        "retrieve_references",
        lambda question, top_k: ([{"source_title": "s", "snippet": "x"}], 1.0),
    )
    monkeypatch.setattr(conversation_service, "stream_answer_text", lambda question, refs: iter(["a" * 5000]))
    monkeypatch.setattr(conversation_service, "realtime_tts_health", lambda: False)
    monkeypatch.setattr(conversation_service, "_stream_answer_audio", lambda segments, answer: iter([b"audio"]))

    result = conversation_service.run_turn("question", [], cancel_event, audio)

    assert len(result.answer) == 4096


def test_run_turn_checks_cancel_before_requesting_each_llm_chunk(monkeypatch) -> None:
    cancel_event = threading.Event()
    audio = BoundedAudioQueue(max_bytes=16, cancel_event=cancel_event)
    requested: list[str] = []

    def llm_chunks():
        for chunk in ("first", "second"):
            requested.append(chunk)
            yield chunk

    def cancel_during_first_chunk(buffer, **kwargs):
        cancel_event.set()
        return [], buffer

    monkeypatch.setattr(
        conversation_service,
        "retrieve_references",
        lambda question, top_k: ([{"source_title": "s", "snippet": "x"}], 1.0),
    )
    monkeypatch.setattr(conversation_service, "stream_answer_text", lambda question, refs: llm_chunks())
    monkeypatch.setattr(conversation_service, "_split_stream_buffer", cancel_during_first_chunk)

    with pytest.raises(TurnCancelled):
        conversation_service.run_turn("question", [], cancel_event, audio)

    assert requested == ["first"]


def test_run_turn_streams_ready_llm_segments_into_realtime_tts(monkeypatch) -> None:
    cancel_event = threading.Event()
    audio = BoundedAudioQueue(max_bytes=16, cancel_event=cancel_event)
    tts_started = threading.Event()

    def llm_chunks():
        yield "a" * 40
        assert tts_started.is_set()
        yield "b" * 40

    def tts_chunks(segments):
        for segment in segments:
            tts_started.set()
            yield segment[:1].encode("ascii")

    monkeypatch.setattr(
        conversation_service,
        "retrieve_references",
        lambda question, top_k: ([{"source_title": "s", "snippet": "x"}], 1.0),
    )
    monkeypatch.setattr(conversation_service, "stream_answer_text", lambda question, refs: llm_chunks())
    monkeypatch.setattr(conversation_service, "realtime_tts_health", lambda: True)
    monkeypatch.setattr(conversation_service, "stream_realtime_tts_chunks", tts_chunks)

    result = conversation_service.run_turn("question", [], cancel_event, audio)

    assert result.answer == ("a" * 40) + ("b" * 40)
    assert audio.get() == b"a"
    assert audio.get() == b"b"


def test_run_turn_preserves_partial_answer_when_queue_cancel_interrupts_put(monkeypatch) -> None:
    cancel_event = threading.Event()
    audio = BoundedAudioQueue(max_bytes=5, cancel_event=cancel_event)
    second_chunk_ready = threading.Event()
    error: list[TurnCancelled] = []

    def tts_chunks(segments):
        list(segments)
        yield b"audio"
        second_chunk_ready.set()
        yield b"audio"

    monkeypatch.setattr(
        conversation_service,
        "retrieve_references",
        lambda question, top_k: ([{"source_title": "s", "snippet": "x"}], 1.0),
    )
    monkeypatch.setattr(conversation_service, "stream_answer_text", lambda question, refs: iter(["a" * 40]))
    monkeypatch.setattr(conversation_service, "realtime_tts_health", lambda: True)
    monkeypatch.setattr(conversation_service, "stream_realtime_tts_chunks", tts_chunks)

    def produce() -> None:
        try:
            conversation_service.run_turn("question", [], cancel_event, audio)
        except TurnCancelled as exc:
            error.append(exc)

    producer = threading.Thread(target=produce)
    producer.start()
    assert second_chunk_ready.wait(0.5)
    audio.revoke()
    producer.join(timeout=0.5)

    assert not producer.is_alive()
    assert len(error) == 1
    assert error[0].partial_answer == "a" * 40


def test_owned_worker_preserves_question_and_answer_truncation_status(monkeypatch) -> None:
    session = ConversationSession.for_test(
        max_audio_queue_bytes=8,
        question_chars=5,
        answer_chars=7,
    )
    monkeypatch.setattr(
        conversation_service,
        "run_turn",
        lambda question, history, cancel_event, audio_queue: TurnRunResult(
            answer="answer-", answer_truncated=True
        ),
    )
    session.start_turn("t1", 0)

    future = session.process_turn("t1", "question-long")
    future.result(timeout=1.0)

    assert session.context_status("t1") == {
        "turn_id": "t1",
        "question": "quest",
        "answer": "answer-",
        "status": "committed",
        "interrupted": False,
        "question_truncated": True,
        "answer_truncated": True,
    }
