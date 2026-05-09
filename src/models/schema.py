from __future__ import annotations

from pydantic import BaseModel


class AcceptedResponse(BaseModel):
    status: str
    task_id: str
    received_at: str


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    step: str | None = None
    progress: float | None = None
    question_text: str | None = None
    answer_text: str | None = None
    audio_url: str | None = None
    references: list[dict] | None = None
    trace: dict | None = None
    tts_status: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class HealthzResponse(BaseModel):
    api: str
    redis: str
    sqlite: str
    asr: str
    llm: str
    tts: str
