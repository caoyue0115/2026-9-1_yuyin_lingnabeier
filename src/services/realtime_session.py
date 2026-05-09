from __future__ import annotations

import logging
import threading
import time
import wave
from collections.abc import Iterable
from pathlib import Path

from src.providers.asr import transcribe_wav_result
from src.providers.llm import stream_answer_text
from src.providers.realtime_tts import (
    PreparedRealtimeTtsSession,
    RealtimeTtsError,
    realtime_tts_health,
    stream_realtime_tts_chunks,
    warmup_realtime_tts_session,
)
from src.providers.tts import synthesize_audio
from src.rag.retriever import is_buddhist_question, retrieve_references
from src.settings import settings
from src.storage.realtime_store import InMemoryRealtimeSessionStore


_SENTENCE_ENDINGS = "。！？!?；;…"
_SOFT_CUT_HINTS = "，、,：: "
logger = logging.getLogger(__name__)


def _elapsed_ms(started_at: float, finished_at: float | None = None) -> int:
    end = time.perf_counter() if finished_at is None else finished_at
    return max(0, int(round((end - started_at) * 1000)))


def _pcm_duration_ms(byte_count: int) -> int:
    bytes_per_second = (
        settings.realtime_audio_sample_rate
        * (settings.realtime_audio_sample_width_bits // 8)
        * settings.realtime_audio_channels
    )
    if bytes_per_second <= 0:
        return 0
    return max(0, int(round((byte_count / bytes_per_second) * 1000)))


def _log_realtime_session_terminal(session: dict) -> None:
    trace = session.get("trace") or {}
    logger.info(
        "realtime_session_done",
        extra={
            "realtime": {
                "session_id": session.get("session_id"),
                "device_id": session.get("device_id"),
                "status": session.get("status"),
                "step": session.get("step"),
                "final_reason": session.get("final_reason"),
                "error_code": session.get("error_code"),
                "asr_ms": trace.get("asr_ms"),
                "retrieval_ms": trace.get("retrieval_ms"),
                "first_llm_chunk_ms": trace.get("first_llm_chunk_ms"),
                "first_tts_chunk_ms": trace.get("first_tts_chunk_ms"),
                "first_audio_byte_ms": trace.get("first_audio_byte_ms"),
                "done_ms": trace.get("done_ms"),
                "llm_chunk_count": trace.get("llm_chunk_count"),
                "tts_segment_count": trace.get("tts_segment_count"),
                "segment_ready_ms": trace.get("segment_ready_ms"),
                "audio_chunk_count": trace.get("audio_chunk_count"),
                "audio_bytes": trace.get("audio_bytes"),
                "audio_duration_ms": trace.get("audio_duration_ms"),
                "audio_stream_wall_ms": trace.get("audio_stream_wall_ms"),
                "audio_max_chunk_gap_ms": trace.get("audio_max_chunk_gap_ms"),
                "production_ratio": trace.get("production_ratio"),
            }
        },
    )


def _set_trace_default(trace: dict, key: str, value):
    if trace.get(key) is None:
        trace[key] = value


def _compact_reference_text(text: str, max_chars: int) -> str:
    normalized = "".join(str(text or "").split())
    if max_chars <= 0 or len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars]


def _compact_references_for_realtime_llm(references: list[dict]) -> list[dict]:
    compact_refs: list[dict] = []
    if settings.realtime_llm_compact_top_k <= 0:
        return references
    limit = settings.realtime_llm_compact_top_k
    max_chars = max(1, settings.realtime_llm_compact_snippet_chars)
    for item in references[:limit]:
        compact_item = dict(item)
        compact_snippet = _compact_reference_text(item.get("snippet") or item.get("text") or "", max_chars=max_chars)
        compact_item["snippet"] = compact_snippet
        compact_item["text"] = compact_snippet
        compact_refs.append(compact_item)
    return compact_refs or references


def _split_long_part(part: str, min_chars: int, max_chars: int) -> list[str]:
    segments: list[str] = []
    remaining = part
    while remaining:
        if len(remaining) <= max_chars:
            segments.append(remaining)
            break
        soft_index = max(remaining.rfind(token, 0, max_chars) for token in _SOFT_CUT_HINTS)
        if soft_index >= min_chars - 1:
            cut_index = soft_index + 1
        else:
            cut_index = max_chars
        segments.append(remaining[:cut_index])
        remaining = remaining[cut_index:]
    return [segment for segment in segments if segment]


def split_realtime_answer_text(text: str, min_chars: int, max_chars: int) -> list[str]:
    normalized = "".join(text.split())
    if not normalized:
        return []
    if max_chars <= 0:
        return [normalized]
    min_chars = max(1, min_chars)
    if min_chars > max_chars:
        min_chars = max_chars

    sentence_parts: list[str] = []
    current = []
    for char in normalized:
        current.append(char)
        if char in _SENTENCE_ENDINGS:
            sentence_parts.append("".join(current))
            current = []
    if current:
        sentence_parts.append("".join(current))

    segments: list[str] = []
    for part in sentence_parts:
        if len(part) > max_chars:
            segments.extend(_split_long_part(part, min_chars=min_chars, max_chars=max_chars))
            continue
        segments.append(part)
    return [segment for segment in segments if segment]


def _split_stream_buffer(
    buffer: str,
    min_chars: int,
    max_chars: int,
    flush_all: bool = False,
    first_segment: bool = False,
    first_segment_min_chars: int | None = None,
    first_segment_max_chars: int | None = None,
) -> tuple[list[str], str]:
    if not buffer:
        return [], ""
    if max_chars <= 0:
        return ([buffer], "") if flush_all else ([], buffer)

    min_chars = max(1, min_chars)
    if min_chars > max_chars:
        min_chars = max_chars

    ready_segments: list[str] = []
    remaining = buffer
    use_first_segment_limits = first_segment
    while remaining:
        active_min_chars = min_chars
        active_max_chars = max_chars
        if use_first_segment_limits:
            active_min_chars = max(1, first_segment_min_chars or min_chars)
            active_max_chars = max(1, first_segment_max_chars or max_chars)
            if active_min_chars > active_max_chars:
                active_min_chars = active_max_chars

        boundary_index = -1
        for index, char in enumerate(remaining):
            if char in _SENTENCE_ENDINGS:
                boundary_index = index
                break
            if char in _SOFT_CUT_HINTS and index + 1 >= active_min_chars:
                boundary_index = index
                break
            if index + 1 >= active_max_chars:
                soft_index = max(remaining.rfind(token, 0, index + 1) for token in _SOFT_CUT_HINTS)
                if soft_index >= active_min_chars - 1:
                    boundary_index = soft_index
                else:
                    boundary_index = index
                break
        if boundary_index < 0 and use_first_segment_limits and len(remaining) >= active_min_chars:
            boundary_index = min(len(remaining), active_max_chars) - 1
        if boundary_index < 0:
            break
        ready_segments.append(remaining[: boundary_index + 1])
        remaining = remaining[boundary_index + 1 :]
        use_first_segment_limits = False

    if flush_all and remaining:
        ready_segments.extend(split_realtime_answer_text(remaining, min_chars=min_chars, max_chars=max_chars))
        remaining = ""
    return ready_segments, remaining


def _load_pcm_chunks(audio_path: str, chunk_size: int = 4096) -> list[bytes]:
    path = Path(audio_path)
    if path.suffix.lower() != ".wav":
        raise ValueError("tts_unsupported_audio_format")
    with wave.open(str(path), "rb") as reader:
        frames = reader.readframes(reader.getnframes())
    if not frames:
        raise ValueError("tts_empty_audio")
    return [frames[i : i + chunk_size] for i in range(0, len(frames), chunk_size)]


def _stream_answer_audio(answer_segments: list[str], answer_text: str) -> Iterable[bytes]:
    if realtime_tts_health():
        yield from stream_realtime_tts_chunks(answer_segments or [answer_text])
        return

    for segment in answer_segments or [answer_text]:
        audio_path, tts_error = synthesize_audio(segment)
        if tts_error:
            raise ValueError(tts_error)
        if not audio_path:
            raise ValueError("tts_empty_audio")
        yield from _load_pcm_chunks(audio_path)


def run_stub_realtime_session(store: InMemoryRealtimeSessionStore, session_id: str) -> None:
    overall_started = time.perf_counter()
    session = store.get_session(session_id)
    if not session:
        return
    input_wav_path = session.get("input_wav_path")
    if not input_wav_path:
        store.mark_failed(session_id, "asr_input_missing", "missing input_wav_path")
        return

    updated = store.update_session(
        session_id,
        status="running",
        step="asr",
        started_at=session["created_at"],
    )
    if not updated:
        return

    asr_started = time.perf_counter()
    asr_result = transcribe_wav_result(input_wav_path)
    updated["trace"]["asr_ms"] = _elapsed_ms(asr_started)
    if asr_result.error_code or not asr_result.text:
        store.mark_failed(
            session_id,
            asr_result.error_code or "asr_empty_text",
            asr_result.error_message or "ASR failed",
        )
        store.fail_audio(session_id, asr_result.error_code or "asr_empty_text")
        return

    question_text = asr_result.text
    store.update_session(
        session_id,
        question_text=question_text,
        step="retrieval",
        trace=updated["trace"],
    )

    retrieval_started = time.perf_counter()
    try:
        references, top_score = retrieve_references(question_text, top_k=settings.top_k)
    except FileNotFoundError as exc:
        store.mark_failed(session_id, "retrieval_unavailable", str(exc) or "Retrieval unavailable")
        store.fail_audio(session_id, "retrieval_unavailable")
        return
    except Exception as exc:
        store.mark_failed(session_id, "retrieval_failed", str(exc) or "Retrieval failed")
        store.fail_audio(session_id, "retrieval_failed")
        return
    updated["trace"]["retrieval_ms"] = _elapsed_ms(retrieval_started)
    threshold = settings.min_top_score if is_buddhist_question(question_text) else settings.min_top_score_no_keyword
    is_reject = (not references) or top_score < threshold
    store.update_session(session_id, step="llm", trace=updated["trace"])
    if is_reject:
        answer_text = "佛说不可曰"
        updated["trace"]["first_llm_chunk_ms"] = _elapsed_ms(overall_started)
    else:
        llm_references = references
        prepared_tts_session: PreparedRealtimeTtsSession | None = None
        if realtime_tts_health():
            llm_references = _compact_references_for_realtime_llm(references)
            if settings.realtime_tts_warmup_enabled:
                warmup_started = time.perf_counter()
                try:
                    prepared_tts_session = warmup_realtime_tts_session()
                    updated["trace"]["tts_warmup_failed"] = False
                except Exception:
                    prepared_tts_session = None
                    updated["trace"]["tts_warmup_failed"] = True
                updated["trace"]["tts_warmup_ms"] = _elapsed_ms(warmup_started)
        try:
            llm_stream: Iterable[str] = stream_answer_text(question_text, llm_references)
        except Exception as exc:
            store.mark_failed(session_id, "llm_request_failed", str(exc) or "LLM failed")
            store.fail_audio(session_id, "llm_request_failed")
            if prepared_tts_session is not None:
                prepared_tts_session.close()
            return
        answer_segments: list[str] = []
        answer_text = ""
        if not realtime_tts_health():
            answer_parts: list[str] = []
            pending_answer = ""
            try:
                for chunk in llm_stream:
                    if not chunk:
                        continue
                    if updated["trace"]["first_llm_chunk_ms"] is None:
                        updated["trace"]["first_llm_chunk_ms"] = _elapsed_ms(overall_started)
                    answer_parts.append(chunk)
                    pending_answer += "".join(chunk.split())
                    ready_segments, pending_answer = _split_stream_buffer(
                        pending_answer,
                        min_chars=settings.realtime_tts_min_chars,
                        max_chars=settings.realtime_tts_max_chars,
                    )
                    answer_segments.extend(segment for segment in ready_segments if segment)
            except Exception as exc:
                store.mark_failed(session_id, "llm_request_failed", str(exc) or "LLM failed")
                store.fail_audio(session_id, "llm_request_failed")
                return
            if pending_answer:
                answer_segments.extend(
                    segment
                    for segment in split_realtime_answer_text(
                        pending_answer,
                        min_chars=settings.realtime_tts_min_chars,
                        max_chars=settings.realtime_tts_max_chars,
                    )
                    if segment
                )
            answer_text = "".join(answer_parts).strip()
            if not answer_text:
                store.mark_failed(session_id, "llm_empty_text", "LLM returned empty text")
                store.fail_audio(session_id, "llm_empty_text")
                return
    store.update_session(
        session_id,
        step="tts",
        answer_text=answer_text,
        trace=updated["trace"],
    )
    if is_reject:
        updated["trace"]["first_tts_chunk_ms"] = _elapsed_ms(overall_started)
        store.update_session(session_id, step="streaming", trace=updated["trace"])
        updated["trace"]["first_audio_byte_ms"] = _elapsed_ms(overall_started)
        store.update_session(
            session_id,
            trace=updated["trace"],
            final_reason="completed_reject" if is_reject else "completed_answer",
        )
        store.append_audio_chunk(session_id, b"\x01\x02\x03\x04")
    else:
        started_streaming = False
        audio_stream_started_at: float | None = None
        audio_last_chunk_at: float | None = None
        audio_bytes = 0
        audio_chunk_count = 0
        audio_max_chunk_gap_ms = 0
        if realtime_tts_health():
            answer_parts = []
            pending_answer = ""
            try:
                def _iter_realtime_answer_segments() -> Iterable[str]:
                    nonlocal pending_answer
                    try:
                        for chunk in llm_stream:
                            if not chunk:
                                continue
                            if updated["trace"]["first_llm_chunk_ms"] is None:
                                updated["trace"]["first_llm_chunk_ms"] = _elapsed_ms(overall_started)
                            updated["trace"]["llm_chunk_count"] = (updated["trace"].get("llm_chunk_count") or 0) + 1
                            answer_parts.append(chunk)
                            pending_answer += "".join(chunk.split())
                            ready_segments, pending_answer = _split_stream_buffer(
                                pending_answer,
                                min_chars=settings.realtime_tts_min_chars,
                                max_chars=settings.realtime_tts_max_chars,
                                first_segment=(updated["trace"].get("tts_segment_count") or 0) == 0,
                                first_segment_min_chars=settings.realtime_tts_first_segment_min_chars,
                                first_segment_max_chars=settings.realtime_tts_first_segment_max_chars,
                            )
                            for segment in ready_segments:
                                if segment:
                                    updated["trace"]["tts_segment_count"] = (
                                        updated["trace"].get("tts_segment_count") or 0
                                    ) + 1
                                    segment_ready_ms = updated["trace"].get("segment_ready_ms") or []
                                    segment_ready_ms.append(_elapsed_ms(overall_started))
                                    updated["trace"]["segment_ready_ms"] = segment_ready_ms
                                    yield segment
                    except Exception as exc:
                        raise RealtimeTtsError("llm_request_failed", str(exc) or "LLM failed") from exc
                    if pending_answer:
                        for segment in split_realtime_answer_text(
                            pending_answer,
                            min_chars=settings.realtime_tts_min_chars,
                            max_chars=settings.realtime_tts_max_chars,
                        ):
                            if segment:
                                updated["trace"]["tts_segment_count"] = (
                                    updated["trace"].get("tts_segment_count") or 0
                                ) + 1
                                segment_ready_ms = updated["trace"].get("segment_ready_ms") or []
                                segment_ready_ms.append(_elapsed_ms(overall_started))
                                updated["trace"]["segment_ready_ms"] = segment_ready_ms
                                yield segment
                        pending_answer = ""

                store.update_session(session_id, step="tts", trace=updated["trace"])
                stream_kwargs = {}
                if prepared_tts_session is not None:
                    stream_kwargs["prepared_session"] = prepared_tts_session
                for chunk in stream_realtime_tts_chunks(
                    _iter_realtime_answer_segments(),
                    **stream_kwargs,
                ):
                    if not chunk:
                        continue
                    now = time.perf_counter()
                    if audio_stream_started_at is None:
                        audio_stream_started_at = now
                    if audio_last_chunk_at is not None:
                        audio_max_chunk_gap_ms = max(
                            audio_max_chunk_gap_ms,
                            _elapsed_ms(audio_last_chunk_at, now),
                        )
                    audio_last_chunk_at = now
                    audio_chunk_count += 1
                    audio_bytes += len(chunk)
                    updated["trace"]["audio_chunk_count"] = audio_chunk_count
                    updated["trace"]["audio_bytes"] = audio_bytes
                    updated["trace"]["audio_duration_ms"] = _pcm_duration_ms(audio_bytes)
                    updated["trace"]["audio_max_chunk_gap_ms"] = audio_max_chunk_gap_ms
                    if not started_streaming:
                        updated["trace"]["first_tts_chunk_ms"] = _elapsed_ms(overall_started)
                        store.update_session(session_id, step="streaming", trace=updated["trace"])
                        updated["trace"]["first_audio_byte_ms"] = _elapsed_ms(overall_started)
                        store.update_session(
                            session_id,
                            trace=updated["trace"],
                            final_reason="completed_answer",
                        )
                        started_streaming = True
                    store.append_audio_chunk(session_id, chunk)
                answer_text = "".join(answer_parts).strip()
                if not answer_text:
                    store.mark_failed(session_id, "llm_empty_text", "LLM returned empty text")
                    store.fail_audio(session_id, "llm_empty_text")
                    return
            except RealtimeTtsError as exc:
                store.mark_failed(session_id, exc.code, exc.message)
                store.fail_audio(session_id, exc.code)
                return
            finally:
                if prepared_tts_session is not None:
                    prepared_tts_session.close()
        else:
            try:
                pcm_stream = _stream_answer_audio(answer_segments, answer_text)
                for chunk in pcm_stream:
                    if not chunk:
                        continue
                    now = time.perf_counter()
                    if audio_stream_started_at is None:
                        audio_stream_started_at = now
                    if audio_last_chunk_at is not None:
                        audio_max_chunk_gap_ms = max(
                            audio_max_chunk_gap_ms,
                            _elapsed_ms(audio_last_chunk_at, now),
                        )
                    audio_last_chunk_at = now
                    audio_chunk_count += 1
                    audio_bytes += len(chunk)
                    updated["trace"]["audio_chunk_count"] = audio_chunk_count
                    updated["trace"]["audio_bytes"] = audio_bytes
                    updated["trace"]["audio_duration_ms"] = _pcm_duration_ms(audio_bytes)
                    updated["trace"]["audio_max_chunk_gap_ms"] = audio_max_chunk_gap_ms
                    if not started_streaming:
                        updated["trace"]["first_tts_chunk_ms"] = _elapsed_ms(overall_started)
                        store.update_session(session_id, step="streaming", trace=updated["trace"])
                        updated["trace"]["first_audio_byte_ms"] = _elapsed_ms(overall_started)
                        store.update_session(
                            session_id,
                            trace=updated["trace"],
                            final_reason="completed_reject" if is_reject else "completed_answer",
                        )
                        started_streaming = True
                    store.append_audio_chunk(session_id, chunk)
            except RealtimeTtsError as exc:
                store.mark_failed(session_id, exc.code, exc.message)
                store.fail_audio(session_id, exc.code)
                return
            except ValueError as exc:
                error_code = str(exc)
                store.mark_failed(session_id, error_code, error_code)
                store.fail_audio(session_id, error_code)
                return
        if audio_stream_started_at is not None and audio_last_chunk_at is not None:
            audio_stream_wall_ms = _elapsed_ms(audio_stream_started_at, audio_last_chunk_at)
            updated["trace"]["audio_stream_wall_ms"] = audio_stream_wall_ms
            updated["trace"]["audio_duration_ms"] = _pcm_duration_ms(audio_bytes)
            updated["trace"]["production_ratio"] = (
                round(updated["trace"]["audio_duration_ms"] / audio_stream_wall_ms, 3)
                if audio_stream_wall_ms > 0
                else None
            )
        _set_trace_default(updated["trace"], "llm_chunk_count", 0)
        _set_trace_default(updated["trace"], "tts_segment_count", 0)
        _set_trace_default(updated["trace"], "segment_ready_ms", [])
        _set_trace_default(updated["trace"], "audio_chunk_count", audio_chunk_count)
        _set_trace_default(updated["trace"], "audio_bytes", audio_bytes)
        _set_trace_default(updated["trace"], "audio_max_chunk_gap_ms", audio_max_chunk_gap_ms)
        store.update_session(session_id, trace=updated["trace"])
    store.finish_audio(session_id)
    done_session = store.mark_done(
        session_id,
        final_reason="completed_reject" if is_reject else "completed_answer",
        answer_text=answer_text,
        done_ms=_elapsed_ms(overall_started),
    )
    if done_session is not None:
        _log_realtime_session_terminal(done_session)


def start_realtime_session(store: InMemoryRealtimeSessionStore, session_id: str) -> None:
    thread = threading.Thread(
        target=run_stub_realtime_session,
        args=(store, session_id),
        daemon=True,
    )
    thread.start()
