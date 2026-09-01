from __future__ import annotations

import time

from redis import Redis
from rq import Queue

from src.providers.asr import ASRResult, transcribe_wav_result
from src.providers.llm import generate_answer
from src.providers.tts import synthesize_audio
from src.rag.retriever import retrieve_references
from src.services.question_router import (
    DISNEY_KNOWLEDGE_MISS,
    DYNAMIC_REFUSAL,
    QuestionRoute,
    route_question,
)
from src.settings import settings
from src.storage.db import fetch_task, mark_task_done, mark_task_failed, update_task_status


def enqueue_task(task_id: str) -> None:
    redis_conn = Redis.from_url(settings.redis_url)
    Queue(settings.queue_name, connection=redis_conn).enqueue(run_pipeline, task_id)


def run_pipeline(task_id: str) -> None:
    started = time.perf_counter()
    trace: dict[str, int] = {}
    try:
        row = fetch_task(task_id)
        if not row:
            raise RuntimeError("task_not_found")

        update_task_status(task_id, "running", "asr", 0.2)
        asr_started = time.perf_counter()
        input_wav_path = row.get("input_wav_path")
        if not input_wav_path:
            trace["asr_ms"] = int((time.perf_counter() - asr_started) * 1000)
            trace["total_ms"] = int((time.perf_counter() - started) * 1000)
            mark_task_failed(task_id, "asr", "asr_input_missing", "missing input_wav_path", trace)
            return
        asr_result: ASRResult = transcribe_wav_result(input_wav_path)
        trace["asr_ms"] = int((time.perf_counter() - asr_started) * 1000)
        if asr_result.error_code or not asr_result.text:
            error_code = asr_result.error_code or "asr_empty_text"
            error_message = asr_result.error_message or f"ASR failed for {input_wav_path}: {error_code}"
            trace["total_ms"] = int((time.perf_counter() - started) * 1000)
            mark_task_failed(task_id, "asr", error_code, error_message, trace)
            return
        question_text = asr_result.text

        retrieval_started = time.perf_counter()
        update_task_status(task_id, "running", "retrieval", 0.4)
        route = route_question(question_text)
        references: list[dict] = []
        top_score = 0.0
        if route == QuestionRoute.DISNEY_KNOWLEDGE:
            try:
                references, top_score = retrieve_references(question_text, top_k=settings.top_k)
            except FileNotFoundError:
                references, top_score = [], 0.0
        trace["retrieval_ms"] = int((time.perf_counter() - retrieval_started) * 1000)

        if route == QuestionRoute.DYNAMIC_CURRENT:
            answer_text = DYNAMIC_REFUSAL
        elif route == QuestionRoute.DISNEY_KNOWLEDGE and (
            not references or top_score < settings.min_top_score
        ):
            answer_text = DISNEY_KNOWLEDGE_MISS
        else:
            update_task_status(task_id, "running", "llm", 0.7)
            llm_started = time.perf_counter()
            answer_text = generate_answer(question_text, references)
            trace["llm_ms"] = int((time.perf_counter() - llm_started) * 1000)

        update_task_status(task_id, "running", "tts", 0.9)
        tts_started = time.perf_counter()
        output_audio_path, tts_error = synthesize_audio(answer_text)
        trace["tts_ms"] = int((time.perf_counter() - tts_started) * 1000)
        trace["total_ms"] = int((time.perf_counter() - started) * 1000)
        mark_task_done(
            task_id=task_id,
            question_text=question_text,
            answer_text=answer_text,
            output_audio_path=output_audio_path,
            references=[{k: v for k, v in item.items() if k != "text"} for item in references],
            trace=trace,
            tts_status="failed" if tts_error else "ok",
        )
    except Exception as exc:
        trace["total_ms"] = int((time.perf_counter() - started) * 1000)
        mark_task_failed(task_id, "pipeline", type(exc).__name__.lower(), str(exc), trace)
