from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class RealtimeTrace(BaseModel):
    asr_ms: int | None = None
    retrieval_ms: int | None = None
    first_llm_chunk_ms: int | None = None
    first_tts_chunk_ms: int | None = None
    first_audio_byte_ms: int | None = None
    done_ms: int | None = None
    tts_warmup_ms: int | None = None
    tts_warmup_failed: bool | None = None
    llm_chunk_count: int | None = None
    tts_segment_count: int | None = None
    segment_ready_ms: list[int] | None = None
    audio_chunk_count: int | None = None
    audio_bytes: int | None = None
    audio_duration_ms: int | None = None
    audio_stream_wall_ms: int | None = None
    audio_max_chunk_gap_ms: int | None = None
    production_ratio: float | None = None
    uplink_opus_bytes: int | None = None
    uplink_pcm_bytes: int | None = None
    uplink_compression_ratio: float | None = None
    uplink_frame_count: int | None = None
    opus_decode_ms: int | None = None
    reconstructed_audio_ms: int | None = None
    first_pcm_to_asr_ms: int | None = None
    first_asr_partial_ms: int | None = None
    asr_final_ms: int | None = None
    realtime_asr_request_id: str | None = None
    retrieval_top_score: float | None = None
    stream_to_session_start_abs_ms: int | None = None
    server_stream_accept_abs_ms: int | None = None
    first_frame_server_abs_ms: int | None = None
    first_pcm_to_asr_abs_ms: int | None = None
    first_asr_partial_abs_ms: int | None = None
    asr_final_abs_ms: int | None = None
    retrieval_done_abs_ms: int | None = None
    first_llm_chunk_abs_ms: int | None = None
    first_tts_chunk_abs_ms: int | None = None
    first_audio_byte_abs_ms: int | None = None
    done_abs_ms: int | None = None


class RealtimeSessionAcceptedResponse(BaseModel):
    status: Literal["accepted"]
    session_id: str
    received_at: str
    audio_stream_url: str


class RealtimeSessionStatusResponse(BaseModel):
    session_id: str
    status: Literal["accepted", "running", "done", "failed"]
    step: Literal["accepted", "asr", "retrieval", "llm", "tts", "streaming", "done", "failed"]
    final_reason: Literal["completed_answer", "completed_reject", "failed"] | None = None
    created_at: str
    updated_at: str
    started_at: str | None = None
    finished_at: str | None = None
    question_text: str | None = None
    answer_text: str | None = None
    audio_stream_url: str
    trace: RealtimeTrace
    error_code: str | None = None
    error_message: str | None = None
