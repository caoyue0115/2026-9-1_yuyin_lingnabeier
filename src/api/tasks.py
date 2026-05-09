from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import FileResponse

from src.models.schema import AcceptedResponse, TaskStatusResponse
from src.settings import settings
from src.storage.db import create_task, fetch_task
from src.storage.files import safe_audio_path, save_pcm_as_wav
from src.workers.pipeline import enqueue_task

router = APIRouter()


@router.post("/api/v2/tasks", response_model=AcceptedResponse)
async def submit_task(
    request: Request,
    x_device_id: str = Header(...),
    x_sample_rate: int = Header(default=settings.default_sample_rate),
    x_sample_width: int = Header(default=settings.default_sample_width_bits),
    x_channels: int = Header(default=settings.default_channels),
) -> AcceptedResponse:
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="empty audio body")
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(body) > max_bytes:
        raise HTTPException(status_code=413, detail="audio body too large")
    wav_path = save_pcm_as_wav(body, x_sample_rate, x_sample_width, x_channels)
    task_id = str(uuid.uuid4())
    received_at = create_task(task_id=task_id, device_id=x_device_id, input_wav_path=str(wav_path))
    enqueue_task(task_id)
    return AcceptedResponse(status="accepted", task_id=task_id, received_at=received_at)


@router.get("/api/v2/tasks/{task_id}", response_model=TaskStatusResponse)
def get_task(task_id: str) -> TaskStatusResponse:
    row = fetch_task(task_id)
    if not row:
        raise HTTPException(status_code=404, detail="task not found")
    references = json.loads(row["references_json"]) if row["references_json"] else None
    trace = json.loads(row["trace_json"]) if row["trace_json"] else None
    audio_url = None
    if row["output_audio_path"]:
        audio_name = row["output_audio_path"].split("/")[-1]
        audio_url = f"{settings.public_base_url}/api/v2/audio/{audio_name}"
    return TaskStatusResponse(
        task_id=row["task_id"],
        status=row["status"],
        step=row["step"],
        progress=row["progress"],
        question_text=row["question_text"],
        answer_text=row["answer_text"],
        audio_url=audio_url,
        references=references,
        trace=trace,
        tts_status=row["tts_status"],
        error_code=row["error_code"],
        error_message=row["error_message"],
    )


@router.get("/api/v2/audio/{filename}")
def get_audio(filename: str) -> FileResponse:
    audio_path = safe_audio_path(filename)
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="audio not found")
    return FileResponse(audio_path, media_type=settings.audio_content_type, filename=audio_path.name)

