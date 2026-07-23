from __future__ import annotations

from fastapi import FastAPI
from redis import Redis

from src.api.ota import router as ota_router
from src.api.realtime import router as realtime_router
from src.api.realtime_v6 import router as realtime_v6_router
from src.api.tasks import router as tasks_router
from src.models.schema import HealthzResponse
from src.providers.asr import asr_health
from src.providers.llm import llm_health
from src.providers.tts import tts_health
from src.settings import settings
from src.storage.db import init_db, sqlite_ok

app = FastAPI(title=settings.project_name, version=settings.version)
init_db()
app.include_router(tasks_router)
app.include_router(realtime_router)
app.include_router(realtime_v6_router)
app.include_router(ota_router)


@app.get("/", tags=["meta"])
def root() -> dict:
    return {"status": "ok", "service": settings.project_name}


@app.get("/healthz", response_model=HealthzResponse, tags=["meta"])
def healthz() -> HealthzResponse:
    redis_status = "down"
    try:
        redis_status = "ok" if Redis.from_url(settings.redis_url).ping() else "down"
    except Exception:
        redis_status = "down"
    return HealthzResponse(
        api="ok",
        redis=redis_status,
        sqlite="ok" if sqlite_ok() else "down",
        asr="ok" if asr_health() else "down",
        llm="ok" if llm_health() else "down",
        tts="ok" if tts_health() else "down",
    )
