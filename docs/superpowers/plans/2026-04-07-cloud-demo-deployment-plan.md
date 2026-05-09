# Cloud Demo Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `OLD_PUBLIC_ENTRY_DISABLED` 上完成首轮云端 Demo 部署，打通 `ESP 上传 PCM -> task_id -> 假 ASR -> RAG -> LLM -> TTS -> 轮询 -> 音频下载` 全链路。

**Architecture:** 服务以 `docker compose` 运行 `api + worker + redis` 三个组件。API 负责接收原始 PCM、封装 WAV、创建任务并入队；worker 负责执行 `Fake ASR -> RAG -> LLM -> TTS`；SQLite 和本地磁盘负责结果与文件持久化。

**Tech Stack:** FastAPI, RQ, Redis, SQLite, FAISS, DashScope API, Docker Compose, Python 3.11-slim

---

### Task 1: Create Local Project Skeleton

**Files:**
- Create: `20260407_宗教大模型云服务器Demo/src/__init__.py`
- Create: `20260407_宗教大模型云服务器Demo/src/app.py`
- Create: `20260407_宗教大模型云服务器Demo/src/settings.py`
- Create: `20260407_宗教大模型云服务器Demo/src/models/schema.py`
- Create: `20260407_宗教大模型云服务器Demo/src/api/tasks.py`
- Create: `20260407_宗教大模型云服务器Demo/src/workers/pipeline.py`
- Create: `20260407_宗教大模型云服务器Demo/src/providers/llm.py`
- Create: `20260407_宗教大模型云服务器Demo/src/providers/tts.py`
- Create: `20260407_宗教大模型云服务器Demo/src/storage/db.py`
- Create: `20260407_宗教大模型云服务器Demo/src/storage/files.py`
- Create: `20260407_宗教大模型云服务器Demo/requirements.txt`
- Create: `20260407_宗教大模型云服务器Demo/.env.example`
- Create: `20260407_宗教大模型云服务器Demo/scripts/smoke_submit.py`
- Create: `20260407_宗教大模型云服务器Demo/scripts/smoke_poll.py`

- [ ] **Step 1: Write the failing smoke import check**

Create a temporary import probe in `scripts/smoke_submit.py` first:

```python
from src.app import app

print(app.title)
```

- [ ] **Step 2: Run import check to verify it fails before scaffolding**

Run: `cd /home/aitopia/Engineering_Projects/20260407_宗教大模型云服务器Demo && python3 scripts/smoke_submit.py`
Expected: FAIL with `ModuleNotFoundError` for `src`

- [ ] **Step 3: Write minimal project skeleton**

Create these minimal files:

```python
# src/__init__.py
```

```python
# src/app.py
from fastapi import FastAPI

app = FastAPI(title="Religion Cloud Demo", version="0.1.0")
```

```python
# src/settings.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "dev"
    host: str = "0.0.0.0"
    port: int = 8010

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
```

```python
# src/models/schema.py
from pydantic import BaseModel


class HealthzResponse(BaseModel):
    api: str
```

```python
# src/api/tasks.py
from fastapi import APIRouter

router = APIRouter()
```

```python
# src/workers/pipeline.py
def run_pipeline(task_id: str) -> None:
    raise NotImplementedError
```

```python
# src/providers/llm.py
def generate_answer(question_text: str) -> str:
    return question_text
```

```python
# src/providers/tts.py
def synthesize_audio(text: str) -> str | None:
    return None
```

```python
# src/storage/db.py
def init_db() -> None:
    return None
```

```python
# src/storage/files.py
def save_upload(data: bytes) -> str:
    return ""
```

```text
# requirements.txt
fastapi
uvicorn
pydantic
pydantic-settings
```

```bash
# .env.example
APP_ENV=dev
HOST=0.0.0.0
PORT=8010
```

- [ ] **Step 4: Replace `scripts/smoke_submit.py` with the real import check**

```python
from src.app import app

print(app.title)
```

- [ ] **Step 5: Run import check to verify the skeleton works**

Run: `cd /home/aitopia/Engineering_Projects/20260407_宗教大模型云服务器Demo && PYTHONPATH=. python3 scripts/smoke_submit.py`
Expected: PASS and print `Religion Cloud Demo`

- [ ] **Step 6: Commit**

```bash
git add 20260407_宗教大模型云服务器Demo
git commit -m "feat: scaffold religion cloud demo project"
```

### Task 2: Implement Configuration and Persistent Storage

**Files:**
- Modify: `20260407_宗教大模型云服务器Demo/src/settings.py`
- Modify: `20260407_宗教大模型云服务器Demo/src/storage/db.py`
- Modify: `20260407_宗教大模型云服务器Demo/src/storage/files.py`
- Create: `20260407_宗教大模型云服务器Demo/src/storage/__init__.py`
- Test: `20260407_宗教大模型云服务器Demo/scripts/smoke_submit.py`

- [ ] **Step 1: Write the failing storage smoke**

Replace `scripts/smoke_submit.py` with:

```python
from src.storage.db import init_db
from src.storage.files import ensure_data_dirs

ensure_data_dirs()
init_db()
print("storage-ready")
```

- [ ] **Step 2: Run the smoke to verify it fails**

Run: `cd /home/aitopia/Engineering_Projects/20260407_宗教大模型云服务器Demo && PYTHONPATH=. python3 scripts/smoke_submit.py`
Expected: FAIL because `ensure_data_dirs` is undefined

- [ ] **Step 3: Implement data directories and SQLite schema**

Write:

```python
# src/settings.py
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "dev"
    host: str = "0.0.0.0"
    port: int = 8010
    redis_url: str = "redis://127.0.0.1:6379/0"
    sqlite_path: str = "./data/tasks.db"
    public_base_url: str = "http://<CURRENT_BASE_URL>"
    fake_asr_text: str = "什么是无相"
    max_upload_mb: int = 3
    max_audio_seconds: int = 8
    llm_model: str = "qwen-max-latest"
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com"
    dashscope_tts_model: str = "qwen3-tts-vc-2026-01-22"
    tts_voice: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def project_root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    @property
    def data_dir(self) -> Path:
        return self.project_root / "data"

    @property
    def incoming_dir(self) -> Path:
        return self.data_dir / "incoming"

    @property
    def output_dir(self) -> Path:
        return self.data_dir / "output"

    @property
    def kb_dir(self) -> Path:
        return self.data_dir / "buddhism"

    @property
    def sqlite_file(self) -> Path:
        return (self.project_root / self.sqlite_path).resolve()


settings = Settings()
```

```python
# src/storage/files.py
from pathlib import Path

from src.settings import settings


def ensure_data_dirs() -> None:
    for path in (
        settings.data_dir,
        settings.incoming_dir,
        settings.output_dir,
        settings.kb_dir,
        settings.data_dir / "logs",
    ):
        path.mkdir(parents=True, exist_ok=True)
```

```python
# src/storage/db.py
import sqlite3

from src.settings import settings
from src.storage.files import ensure_data_dirs


def init_db() -> None:
    ensure_data_dirs()
    conn = sqlite3.connect(settings.sqlite_file)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                device_id TEXT NOT NULL,
                status TEXT NOT NULL,
                step TEXT,
                progress REAL NOT NULL DEFAULT 0,
                input_wav_path TEXT,
                output_audio_path TEXT,
                question_text TEXT,
                answer_text TEXT,
                references_json TEXT,
                trace_json TEXT,
                tts_status TEXT,
                error_code TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()
```

- [ ] **Step 4: Run storage smoke to verify it passes**

Run: `cd /home/aitopia/Engineering_Projects/20260407_宗教大模型云服务器Demo && PYTHONPATH=. python3 scripts/smoke_submit.py`
Expected: PASS and print `storage-ready`

- [ ] **Step 5: Commit**

```bash
git add 20260407_宗教大模型云服务器Demo
git commit -m "feat: add persistent storage foundations"
```

### Task 3: Implement HTTP Upload and Polling API

**Files:**
- Modify: `20260407_宗教大模型云服务器Demo/src/app.py`
- Modify: `20260407_宗教大模型云服务器Demo/src/api/tasks.py`
- Modify: `20260407_宗教大模型云服务器Demo/src/models/schema.py`
- Modify: `20260407_宗教大模型云服务器Demo/src/storage/db.py`
- Modify: `20260407_宗教大模型云服务器Demo/src/storage/files.py`
- Test: `20260407_宗教大模型云服务器Demo/scripts/smoke_submit.py`

- [ ] **Step 1: Write the failing API smoke**

Replace `scripts/smoke_submit.py` with:

```python
import httpx


pcm = b"\x00\x00" * 16000
resp = httpx.post(
    "http://127.0.0.1:8010/api/v2/tasks",
    content=pcm,
    headers={
        "content-type": "application/octet-stream",
        "x-device-id": "esp-demo-001",
        "x-sample-rate": "16000",
        "x-sample-width": "16",
        "x-channels": "1",
    },
    timeout=10,
)
print(resp.status_code)
print(resp.text)
```

- [ ] **Step 2: Run the smoke to verify it fails before endpoint implementation**

Run: `cd /home/aitopia/Engineering_Projects/20260407_宗教大模型云服务器Demo && PYTHONPATH=. python3 scripts/smoke_submit.py`
Expected: FAIL with connection error or 404

- [ ] **Step 3: Implement the upload, polling, audio and health endpoints**

Add these capabilities:

```python
# src/models/schema.py
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
```

```python
# src/storage/files.py
import uuid
import wave
from pathlib import Path

from src.settings import settings


def save_pcm_as_wav(pcm_bytes: bytes, sample_rate: int, sample_width_bits: int, channels: int) -> Path:
    ensure_data_dirs()
    out_path = settings.incoming_dir / f"{uuid.uuid4()}.wav"
    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width_bits // 8)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return out_path
```

```python
# src/storage/db.py
import json
import sqlite3
from datetime import datetime, timezone

from src.settings import settings


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_task(task_id: str, device_id: str, input_wav_path: str) -> None:
    conn = sqlite3.connect(settings.sqlite_file)
    try:
        ts = now_iso()
        conn.execute(
            """
            INSERT INTO tasks(task_id, device_id, status, step, progress, input_wav_path, created_at, updated_at)
            VALUES (?, ?, 'accepted', 'queued', 0.0, ?, ?, ?)
            """,
            (task_id, device_id, input_wav_path, ts, ts),
        )
        conn.commit()
    finally:
        conn.close()


def fetch_task(task_id: str) -> dict | None:
    conn = sqlite3.connect(settings.sqlite_file)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
```

```python
# src/api/tasks.py
import json
import uuid

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import FileResponse

from src.models.schema import AcceptedResponse, TaskStatusResponse
from src.settings import settings
from src.storage.db import create_task, fetch_task
from src.storage.files import save_pcm_as_wav

router = APIRouter()


@router.post("/api/v2/tasks", response_model=AcceptedResponse)
async def submit_task(
    request: Request,
    x_device_id: str = Header(...),
    x_sample_rate: int = Header(default=16000),
    x_sample_width: int = Header(default=16),
    x_channels: int = Header(default=1),
) -> AcceptedResponse:
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="empty audio body")
    wav_path = save_pcm_as_wav(body, x_sample_rate, x_sample_width, x_channels)
    task_id = str(uuid.uuid4())
    create_task(task_id=task_id, device_id=x_device_id, input_wav_path=str(wav_path))
    return AcceptedResponse(status="accepted", task_id=task_id, received_at="placeholder")


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
    return FileResponse(settings.output_dir / filename, media_type="audio/wav")
```

```python
# src/app.py
from fastapi import FastAPI

from src.api.tasks import router as tasks_router
from src.storage.db import init_db

app = FastAPI(title="Religion Cloud Demo", version="0.1.0")
init_db()
app.include_router(tasks_router)


@app.get("/healthz")
def healthz() -> dict:
    return {"api": "ok"}
```

- [ ] **Step 4: Run the app and verify the endpoint works**

Run in terminal A: `cd /home/aitopia/Engineering_Projects/20260407_宗教大模型云服务器Demo && PYTHONPATH=. uvicorn src.app:app --host 0.0.0.0 --port 8010`

Run in terminal B: `cd /home/aitopia/Engineering_Projects/20260407_宗教大模型云服务器Demo && PYTHONPATH=. python3 scripts/smoke_submit.py`

Expected: HTTP 200 and JSON with `status=accepted`

- [ ] **Step 5: Commit**

```bash
git add 20260407_宗教大模型云服务器Demo
git commit -m "feat: implement demo upload and polling api"
```

### Task 4: Implement Queueing and Task State Transitions

**Files:**
- Modify: `20260407_宗教大模型云服务器Demo/src/api/tasks.py`
- Modify: `20260407_宗教大模型云服务器Demo/src/storage/db.py`
- Modify: `20260407_宗教大模型云服务器Demo/src/workers/pipeline.py`
- Modify: `20260407_宗教大模型云服务器Demo/src/settings.py`
- Test: `20260407_宗教大模型云服务器Demo/scripts/smoke_poll.py`

- [ ] **Step 1: Write the failing queue smoke**

Create `scripts/smoke_poll.py`:

```python
import time

import httpx


pcm = b"\x00\x00" * 16000
resp = httpx.post(
    "http://127.0.0.1:8010/api/v2/tasks",
    content=pcm,
    headers={
        "content-type": "application/octet-stream",
        "x-device-id": "esp-demo-001",
    },
    timeout=10,
)
task_id = resp.json()["task_id"]
for _ in range(3):
    status = httpx.get(f"http://127.0.0.1:8010/api/v2/tasks/{task_id}", timeout=10).json()
    print(status["status"], status.get("step"))
    time.sleep(1)
```

- [ ] **Step 2: Run the queue smoke to verify it stays stuck in `accepted`**

Run: `cd /home/aitopia/Engineering_Projects/20260407_宗教大模型云服务器Demo && PYTHONPATH=. python3 scripts/smoke_poll.py`
Expected: No state change beyond `accepted`

- [ ] **Step 3: Implement Redis enqueue and task updates**

Add these functions:

```python
# src/storage/db.py
def update_task_status(task_id: str, status: str, step: str, progress: float) -> None:
    conn = sqlite3.connect(settings.sqlite_file)
    try:
        conn.execute(
            "UPDATE tasks SET status = ?, step = ?, progress = ?, updated_at = ? WHERE task_id = ?",
            (status, step, progress, now_iso(), task_id),
        )
        conn.commit()
    finally:
        conn.close()


def mark_task_done(
    task_id: str,
    question_text: str,
    answer_text: str,
    output_audio_path: str | None,
    references: list[dict],
    trace: dict,
    tts_status: str | None,
) -> None:
    conn = sqlite3.connect(settings.sqlite_file)
    try:
        conn.execute(
            """
            UPDATE tasks
            SET status = 'done',
                step = 'done',
                progress = 1.0,
                question_text = ?,
                answer_text = ?,
                output_audio_path = ?,
                references_json = ?,
                trace_json = ?,
                tts_status = ?,
                updated_at = ?
            WHERE task_id = ?
            """,
            (
                question_text,
                answer_text,
                output_audio_path,
                json.dumps(references, ensure_ascii=False),
                json.dumps(trace, ensure_ascii=False),
                tts_status,
                now_iso(),
                task_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()
```

```python
# src/workers/pipeline.py
from redis import Redis
from rq import Queue

from src.settings import settings
from src.storage.db import update_task_status


def enqueue_task(task_id: str) -> None:
    redis_conn = Redis.from_url(settings.redis_url)
    queue = Queue("religion_tasks", connection=redis_conn)
    queue.enqueue(run_pipeline, task_id)


def run_pipeline(task_id: str) -> None:
    update_task_status(task_id, "running", "fake_asr", 0.2)
```

Wire enqueue into submit endpoint:

```python
# src/api/tasks.py
from src.workers.pipeline import enqueue_task
...
    create_task(task_id=task_id, device_id=x_device_id, input_wav_path=str(wav_path))
    enqueue_task(task_id)
```

- [ ] **Step 4: Run API, Redis, worker and verify state moves to `running`**

Run in separate terminals:

```bash
redis-server
```

```bash
cd /home/aitopia/Engineering_Projects/20260407_宗教大模型云服务器Demo && PYTHONPATH=. uvicorn src.app:app --host 0.0.0.0 --port 8010
```

```bash
cd /home/aitopia/Engineering_Projects/20260407_宗教大模型云服务器Demo && PYTHONPATH=. rq worker -u redis://127.0.0.1:6379/0 religion_tasks
```

Then run:

```bash
cd /home/aitopia/Engineering_Projects/20260407_宗教大模型云服务器Demo && PYTHONPATH=. python3 scripts/smoke_poll.py
```

Expected: status progresses from `accepted` to `running`

- [ ] **Step 5: Commit**

```bash
git add 20260407_宗教大模型云服务器Demo
git commit -m "feat: add redis queue and worker transitions"
```

### Task 5: Port RAG Retrieval for Buddhism Knowledge Base

**Files:**
- Create: `20260407_宗教大模型云服务器Demo/src/rag/retriever.py`
- Create: `20260407_宗教大模型云服务器Demo/src/rag/ingest.py`
- Modify: `20260407_宗教大模型云服务器Demo/src/workers/pipeline.py`
- Modify: `20260407_宗教大模型云服务器Demo/requirements.txt`
- Test: `20260407_宗教大模型云服务器Demo/scripts/smoke_poll.py`

- [ ] **Step 1: Write the failing retrieval smoke**

Edit `scripts/smoke_poll.py` to print `references` and `answer_text` and expect them to be empty before retrieval is implemented.

- [ ] **Step 2: Run it to confirm no references are produced**

Run: `cd /home/aitopia/Engineering_Projects/20260407_宗教大模型云服务器Demo && PYTHONPATH=. python3 scripts/smoke_poll.py`
Expected: task completes without real references

- [ ] **Step 3: Port the minimal RAG ingest and retrieve logic from the 20260404 project**

Implement:

```python
# src/rag/ingest.py
def ingest_buddhism_docs() -> dict:
    """
    Read files from data/buddhism, clean text, chunk content, build BM25 + FAISS artifacts,
    and persist them under local indices/.
    """
```

```python
# src/rag/retriever.py
def retrieve_references(question_text: str, top_k: int = 2) -> list[dict]:
    """
    Return up to top_k references with source_title, snippet, score.
    """
```

Worker integration behavior:

- `question_text` always starts as `什么是无相`
- if retrieval confidence is below threshold:
  - set `answer_text` to `佛说不可曰`
  - skip LLM generation
- if retrieval confidence passes threshold:
  - continue to LLM

Update dependencies:

```text
numpy
faiss-cpu
jieba
rank-bm25
pypdf
```

- [ ] **Step 4: Run ingest and verify the worker now returns references**

Run:

```bash
cd /home/aitopia/Engineering_Projects/20260407_宗教大模型云服务器Demo && PYTHONPATH=. python3 -c "from src.rag.ingest import ingest_buddhism_docs; print(ingest_buddhism_docs())"
```

Then rerun:

```bash
cd /home/aitopia/Engineering_Projects/20260407_宗教大模型云服务器Demo && PYTHONPATH=. python3 scripts/smoke_poll.py
```

Expected: `references` contains up to 2 Buddhism snippets

- [ ] **Step 5: Commit**

```bash
git add 20260407_宗教大模型云服务器Demo
git commit -m "feat: add buddhism rag retrieval"
```

### Task 6: Integrate DashScope LLM and TTS

**Files:**
- Modify: `20260407_宗教大模型云服务器Demo/src/providers/llm.py`
- Modify: `20260407_宗教大模型云服务器Demo/src/providers/tts.py`
- Modify: `20260407_宗教大模型云服务器Demo/src/workers/pipeline.py`
- Modify: `20260407_宗教大模型云服务器Demo/.env.example`
- Modify: `20260407_宗教大模型云服务器Demo/requirements.txt`
- Test: `20260407_宗教大模型云服务器Demo/scripts/smoke_poll.py`

- [ ] **Step 1: Write the failing provider smoke**

Update `scripts/smoke_poll.py` to poll until terminal state and print `answer_text`, `audio_url`, and `tts_status`.

- [ ] **Step 2: Run it to confirm `audio_url` is still null**

Run: `cd /home/aitopia/Engineering_Projects/20260407_宗教大模型云服务器Demo && PYTHONPATH=. python3 scripts/smoke_poll.py`
Expected: no generated audio yet

- [ ] **Step 3: Implement DashScope provider wrappers**

Implement:

```python
# src/providers/llm.py
from openai import OpenAI

from src.settings import settings


def generate_answer(question_text: str, references: list[dict]) -> str:
    client = OpenAI(api_key=settings.dashscope_api_key, base_url=f"{settings.dashscope_base_url}/compatible-mode/v1")
    evidence = "\n".join(f"- {item['source_title']}: {item['snippet']}" for item in references)
    resp = client.chat.completions.create(
        model=settings.llm_model,
        temperature=0.2,
        messages=[
            {"role": "system", "content": "你是佛学问答助手，只根据证据作答，语言简洁。"},
            {"role": "user", "content": f"问题：{question_text}\n证据：\n{evidence}\n请给出简明回答。"},
        ],
    )
    return resp.choices[0].message.content.strip()
```

```python
# src/providers/tts.py
import uuid
from pathlib import Path

import requests

from src.settings import settings


def synthesize_audio(text: str) -> str | None:
    out_path = settings.output_dir / f"{uuid.uuid4()}.wav"
    # Call DashScope TTS HTTP API using the confirmed TTS model and voice.
    # Save the resulting wav bytes to out_path.
    return str(out_path)
```

Worker behavior:

- if answer is `佛说不可曰`:
  - still attempt TTS
- if TTS succeeds:
  - save absolute audio path in DB
- if TTS fails:
  - keep task `done`
  - set `tts_status=failed`
  - set `audio_url=null`

Update dependencies:

```text
openai
requests
redis
rq
httpx
```

- [ ] **Step 4: Run end-to-end smoke and verify text plus audio path**

Run:

```bash
cd /home/aitopia/Engineering_Projects/20260407_宗教大模型云服务器Demo && PYTHONPATH=. python3 scripts/smoke_poll.py
```

Expected:

- `answer_text` is present
- `audio_url` is an absolute `http://<CURRENT_BASE_URL>/api/v2/audio/...`
- if TTS fails, output shows `tts_status=failed`

- [ ] **Step 5: Commit**

```bash
git add 20260407_宗教大模型云服务器Demo
git commit -m "feat: integrate dashscope llm and tts"
```

### Task 7: Add Docker Compose Deployment Assets

**Files:**
- Create: `20260407_宗教大模型云服务器Demo/docker-compose.yml`
- Create: `20260407_宗教大模型云服务器Demo/Dockerfile`
- Create: `20260407_宗教大模型云服务器Demo/.dockerignore`
- Modify: `20260407_宗教大模型云服务器Demo/.env.example`
- Test: `20260407_宗教大模型云服务器Demo/docker-compose.yml`

- [ ] **Step 1: Write the failing compose validation**

Run: `cd /home/aitopia/Engineering_Projects/20260407_宗教大模型云服务器Demo && docker compose config`
Expected: FAIL because no compose file exists

- [ ] **Step 2: Write the deployment assets**

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY scripts ./scripts
COPY .env.example ./.env.example

CMD ["uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "8010"]
```

```yaml
# docker-compose.yml
services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  api:
    build: .
    command: uvicorn src.app:app --host 0.0.0.0 --port 8010
    env_file:
      - .env
    volumes:
      - ./data:/app/data
    ports:
      - "8010:8010"
    depends_on:
      - redis

  worker:
    build: .
    command: rq worker -u redis://redis:6379/0 religion_tasks
    env_file:
      - .env
    volumes:
      - ./data:/app/data
    depends_on:
      - redis
```

```text
# .dockerignore
.venv
__pycache__
data/output
data/incoming
indices
```

- [ ] **Step 3: Run compose validation to verify it passes**

Run: `cd /home/aitopia/Engineering_Projects/20260407_宗教大模型云服务器Demo && docker compose config`
Expected: PASS with rendered service definitions

- [ ] **Step 4: Commit**

```bash
git add 20260407_宗教大模型云服务器Demo
git commit -m "feat: add docker compose deployment assets"
```

### Task 8: Upload Knowledge Base and Deploy to the Cloud Server

**Files:**
- Modify: `20260407_宗教大模型云服务器Demo/.env`
- Modify: `20260407_宗教大模型云服务器Demo/data/buddhism/*`
- Test: remote deployment under `/app/religion_demo_20260407`

- [ ] **Step 1: Verify server connectivity and prepare the remote directory**

Run:

```bash
ssh -p 22 ubuntu@106.54.240.51
mkdir -p /app/religion_demo_20260407
```

Expected: remote directory exists

- [ ] **Step 2: Upload the local project and Buddhism documents**

Run:

```bash
scp -r /home/aitopia/Engineering_Projects/20260407_宗教大模型云服务器Demo/* OLD_PUBLIC_ENTRY_DISABLED_SSH:/app/religion_demo_20260407/
scp -r /home/aitopia/Engineering_Projects/20260404_宗教对话大模型/data/buddhism/* OLD_PUBLIC_ENTRY_DISABLED_SSH:/app/religion_demo_20260407/data/buddhism/
```

Expected: remote project tree and knowledge base files are present

- [ ] **Step 3: Create the remote `.env` with the frozen parameters**

Create `/app/religion_demo_20260407/.env`:

```bash
APP_ENV=prod
HOST=0.0.0.0
PORT=8010
REDIS_URL=redis://redis:6379/0
SQLITE_PATH=./data/tasks.db
LLM_MODEL=qwen-max-latest
DASHSCOPE_API_KEY=<DASHSCOPE_API_KEY>
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com
DASHSCOPE_TTS_MODEL=qwen3-tts-vc-2026-01-22
TTS_VOICE=qwen-tts-vc-rulaivc04060251-voice-20260406155234264-4a78
FAKE_ASR_TEXT=什么是无相
PUBLIC_BASE_URL=http://<CURRENT_BASE_URL>
```

- [ ] **Step 4: Start the cloud deployment**

Run on the server:

```bash
cd /app/religion_demo_20260407
docker compose up -d --build
```

Expected: `redis`, `api`, and `worker` containers are running

- [ ] **Step 5: Build the cloud RAG index**

Run on the server:

```bash
cd /app/religion_demo_20260407
docker compose exec api python -c "from src.rag.ingest import ingest_buddhism_docs; print(ingest_buddhism_docs())"
```

Expected: Buddhism index build completes successfully

- [ ] **Step 6: Commit**

```bash
git add 20260407_宗教大模型云服务器Demo
git commit -m "docs: add cloud deployment execution plan"
```

### Task 9: Verify End-to-End Demo Behavior on the Cloud Server

**Files:**
- Test: remote API at `http://<CURRENT_BASE_URL>:8010`
- Test: `20260407_宗教大模型云服务器Demo/scripts/smoke_submit.py`
- Test: `20260407_宗教大模型云服务器Demo/scripts/smoke_poll.py`

- [ ] **Step 1: Write the final smoke validation commands**

Run:

```bash
curl http://<CURRENT_BASE_URL>:8010/healthz
```

Expected:

```json
{"api":"ok"}
```

- [ ] **Step 2: Submit a PCM task and verify `accepted + task_id`**

Run:

```bash
cd /home/aitopia/Engineering_Projects/20260407_宗教大模型云服务器Demo
PYTHONPATH=. python3 scripts/smoke_submit.py
```

Expected: response JSON contains `status=accepted` and a non-empty `task_id`

- [ ] **Step 3: Poll until terminal state and verify result fields**

Run:

```bash
cd /home/aitopia/Engineering_Projects/20260407_宗教大模型云服务器Demo
PYTHONPATH=. python3 scripts/smoke_poll.py
```

Expected terminal result:

- `status` is `done` or `failed`
- `question_text` is `什么是无相`
- `answer_text` is present
- `references` is present
- `trace` is present
- `audio_url` is absolute if TTS succeeded
- `tts_status=failed` if TTS failed

- [ ] **Step 4: Verify audio download when present**

Run:

```bash
curl -I "http://<CURRENT_BASE_URL>:8010/api/v2/audio/<filename>.wav"
```

Expected: `HTTP/1.1 200 OK` and `Content-Type: audio/wav`

- [ ] **Step 5: Record residual risks**

Document any remaining issues:

- LLM connectivity not yet proven under DashScope compatible mode
- FAISS package behavior inside `python:3.11-slim`
- No real ASR yet
- No HTTPS or authentication yet

- [ ] **Step 6: Commit**

```bash
git add 20260407_宗教大模型云服务器Demo
git commit -m "test: verify cloud demo end to end"
```
