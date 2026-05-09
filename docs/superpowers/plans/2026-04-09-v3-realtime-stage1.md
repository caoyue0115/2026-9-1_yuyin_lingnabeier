# V3 Realtime Stage 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 固化 `v3/realtime` 第一阶段的服务端契约，实现 schema、API 基础路由、内存态 session store，并用测试锁定 HTTP 状态码和响应字段。

**Architecture:** 在不改动现有 `v2` 路由和 pipeline 的前提下，新增独立的 `src/models/realtime.py`、`src/storage/realtime_store.py` 和 `src/api/realtime.py`。先用内存态 session 元数据支撑 `POST /sessions`、`GET /sessions/{id}` 与占位版 `GET /audio` 行为，再通过 FastAPI 测试把协议固定下来。

**Tech Stack:** FastAPI, Pydantic, unittest, in-memory store, existing `src/app.py` router registration.

---

## 文件结构与责任边界

- Create: `/home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407/20260407_宗教大模型云服务器Demo/src/models/realtime.py`
  - 定义 realtime 请求/响应 schema、时间字段、`final_reason` 与 `trace` 结构。
- Create: `/home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407/20260407_宗教大模型云服务器Demo/src/storage/realtime_store.py`
  - 管理内存态 session 元数据、单消费者占坑、基础状态更新。
- Create: `/home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407/20260407_宗教大模型云服务器Demo/src/api/realtime.py`
  - 暴露 `POST /api/v3/realtime/sessions`、`GET /api/v3/realtime/sessions/{session_id}`、`GET /api/v3/realtime/sessions/{session_id}/audio`。
- Modify: `/home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407/20260407_宗教大模型云服务器Demo/src/app.py`
  - 挂载 realtime router。
- Modify: `/home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407/20260407_宗教大模型云服务器Demo/src/settings.py`
  - 增加 realtime 开关、超时、TTL、音频头常量。
- Create: `/home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407/20260407_宗教大模型云服务器Demo/tests/test_realtime_api.py`
  - 锁定 HTTP code、响应字段、错误码与 header。

### Task 1: 锁定 Realtime Schema

**Files:**
- Create: `/home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407/20260407_宗教大模型云服务器Demo/tests/test_realtime_api.py`
- Create: `/home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407/20260407_宗教大模型云服务器Demo/src/models/realtime.py`

- [ ] **Step 1: 写 schema 级失败测试**

```python
def test_realtime_status_response_exposes_required_fields(self) -> None:
    from src.models.realtime import RealtimeSessionStatusResponse

    payload = RealtimeSessionStatusResponse(
        session_id="session-1",
        status="running",
        step="tts",
        final_reason=None,
        created_at="2026-04-09T15:34:12.245000+00:00",
        updated_at="2026-04-09T15:34:13.901000+00:00",
        started_at="2026-04-09T15:34:12.260000+00:00",
        finished_at=None,
        question_text=None,
        answer_text=None,
        audio_stream_url="http://testserver/api/v3/realtime/sessions/session-1/audio",
        trace={
            "asr_ms": None,
            "retrieval_ms": None,
            "first_llm_chunk_ms": None,
            "first_tts_chunk_ms": None,
            "first_audio_byte_ms": None,
            "done_ms": None,
        },
        error_code=None,
        error_message=None,
    )

    self.assertEqual(payload.session_id, "session-1")
    self.assertIn("first_audio_byte_ms", payload.trace)
```

- [ ] **Step 2: 跑测试确认失败**

Run:

```bash
cd /home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407/20260407_宗教大模型云服务器Demo
python -m unittest tests.test_realtime_api -v
```

Expected:

```text
ERROR: No module named 'src.models.realtime'
```

- [ ] **Step 3: 写最小 schema 实现**

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run:

```bash
cd /home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407/20260407_宗教大模型云服务器Demo
python -m unittest tests.test_realtime_api -v
```

Expected:

```text
OK
```

### Task 2: 锁定 Settings 与默认值

**Files:**
- Modify: `/home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407/20260407_宗教大模型云服务器Demo/src/settings.py`
- Modify: `/home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407/20260407_宗教大模型云服务器Demo/tests/test_realtime_api.py`

- [ ] **Step 1: 写 settings 失败测试**

```python
def test_settings_expose_realtime_defaults(self) -> None:
    from src.settings import settings

    self.assertFalse(settings.realtime_enabled)
    self.assertEqual(settings.realtime_audio_sample_rate, 16000)
    self.assertEqual(settings.realtime_audio_sample_width_bits, 16)
    self.assertEqual(settings.realtime_audio_channels, 1)
    self.assertEqual(settings.realtime_audio_endian, "little")
    self.assertEqual(settings.realtime_session_ttl_seconds, 900)
```

- [ ] **Step 2: 跑测试确认失败**

Run:

```bash
cd /home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407/20260407_宗教大模型云服务器Demo
python -m unittest tests.test_realtime_api -v
```

Expected:

```text
AttributeError: 'Settings' object has no attribute 'realtime_enabled'
```

- [ ] **Step 3: 增加最小 settings 字段**

```python
    realtime_enabled: bool = False
    realtime_session_ttl_seconds: int = 900
    realtime_stream_first_chunk_timeout_ms: int = 5000
    realtime_stream_idle_timeout_ms: int = 8000
    realtime_audio_sample_rate: int = 16000
    realtime_audio_sample_width_bits: int = 16
    realtime_audio_channels: int = 1
    realtime_audio_endian: str = "little"
```

- [ ] **Step 4: 跑测试确认通过**

Run:

```bash
cd /home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407/20260407_宗教大模型云服务器Demo
python -m unittest tests.test_realtime_api -v
```

Expected:

```text
OK
```

### Task 3: 内存态 Session Store

**Files:**
- Create: `/home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407/20260407_宗教大模型云服务器Demo/src/storage/realtime_store.py`
- Modify: `/home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407/20260407_宗教大模型云服务器Demo/tests/test_realtime_api.py`

- [ ] **Step 1: 写 store 失败测试**

```python
def test_store_creates_and_fetches_session(self) -> None:
    from src.storage.realtime_store import InMemoryRealtimeSessionStore

    store = InMemoryRealtimeSessionStore(base_url="http://testserver")
    session = store.create_session(device_id="esp-1")

    fetched = store.get_session(session["session_id"])

    self.assertEqual(fetched["session_id"], session["session_id"])
    self.assertEqual(fetched["status"], "accepted")
    self.assertEqual(
        fetched["audio_stream_url"],
        f"http://testserver/api/v3/realtime/sessions/{session['session_id']}/audio",
    )
```

- [ ] **Step 2: 跑测试确认失败**

Run:

```bash
cd /home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407/20260407_宗教大模型云服务器Demo
python -m unittest tests.test_realtime_api -v
```

Expected:

```text
ERROR: No module named 'src.storage.realtime_store'
```

- [ ] **Step 3: 写最小 store 实现**

```python
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class InMemoryRealtimeSessionStore:
    def __init__(self, base_url: str, ttl_seconds: int = 900) -> None:
        self._base_url = base_url.rstrip("/")
        self._ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._sessions: dict[str, dict] = {}

    def create_session(self, device_id: str) -> dict:
        session_id = str(uuid.uuid4())
        now = _now_iso()
        payload = {
            "session_id": session_id,
            "device_id": device_id,
            "status": "accepted",
            "step": "accepted",
            "final_reason": None,
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "finished_at": None,
            "question_text": None,
            "answer_text": None,
            "audio_stream_url": f"{self._base_url}/api/v3/realtime/sessions/{session_id}/audio",
            "trace": {
                "asr_ms": None,
                "retrieval_ms": None,
                "first_llm_chunk_ms": None,
                "first_tts_chunk_ms": None,
                "first_audio_byte_ms": None,
                "done_ms": None,
            },
            "error_code": None,
            "error_message": None,
            "audio_consumer_id": None,
            "expires_at": (
                datetime.now(timezone.utc) + timedelta(seconds=self._ttl_seconds)
            ).isoformat(),
        }
        with self._lock:
            self._sessions[session_id] = payload
        return dict(payload)

    def get_session(self, session_id: str) -> dict | None:
        with self._lock:
            payload = self._sessions.get(session_id)
            return dict(payload) if payload else None
```

- [ ] **Step 4: 跑测试确认通过**

Run:

```bash
cd /home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407/20260407_宗教大模型云服务器Demo
python -m unittest tests.test_realtime_api -v
```

Expected:

```text
OK
```

### Task 4: POST /sessions API

**Files:**
- Create: `/home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407/20260407_宗教大模型云服务器Demo/src/api/realtime.py`
- Modify: `/home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407/20260407_宗教大模型云服务器Demo/src/app.py`
- Modify: `/home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407/20260407_宗教大模型云服务器Demo/tests/test_realtime_api.py`

- [ ] **Step 1: 写 POST 路由失败测试**

```python
def test_post_realtime_session_returns_202_and_audio_stream_url(self) -> None:
    response = self.client.post(
        "/api/v3/realtime/sessions",
        content=b"\x00\x00" * 16,
        headers={
            "content-type": "application/octet-stream",
            "x-device-id": "esp-1",
            "x-sample-rate": "16000",
            "x-sample-width": "16",
            "x-channels": "1",
        },
    )

    self.assertEqual(response.status_code, 202)
    payload = response.json()
    self.assertEqual(payload["status"], "accepted")
    self.assertIn("/api/v3/realtime/sessions/", payload["audio_stream_url"])
```

- [ ] **Step 2: 跑测试确认失败**

Run:

```bash
cd /home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407/20260407_宗教大模型云服务器Demo
python -m unittest tests.test_realtime_api -v
```

Expected:

```text
AssertionError: 404 != 202
```

- [ ] **Step 3: 写最小 POST 路由与 router 注册**

```python
router = APIRouter()
store = InMemoryRealtimeSessionStore(base_url=settings.public_base_url, ttl_seconds=settings.realtime_session_ttl_seconds)


@router.post("/api/v3/realtime/sessions", response_model=RealtimeSessionAcceptedResponse, status_code=202)
async def create_realtime_session(
    request: Request,
    x_device_id: str = Header(...),
) -> RealtimeSessionAcceptedResponse:
    if request.headers.get("content-type") != "application/octet-stream":
        raise HTTPException(status_code=400, detail="invalid_request")
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="empty_audio_body")
    session = store.create_session(device_id=x_device_id)
    return RealtimeSessionAcceptedResponse(
        status="accepted",
        session_id=session["session_id"],
        received_at=session["created_at"],
        audio_stream_url=session["audio_stream_url"],
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run:

```bash
cd /home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407/20260407_宗教大模型云服务器Demo
python -m unittest tests.test_realtime_api -v
```

Expected:

```text
OK
```

### Task 5: GET /sessions/{id} 与占位版 GET /audio

**Files:**
- Modify: `/home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407/20260407_宗教大模型云服务器Demo/src/api/realtime.py`
- Modify: `/home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407/20260407_宗教大模型云服务器Demo/src/storage/realtime_store.py`
- Modify: `/home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407/20260407_宗教大模型云服务器Demo/tests/test_realtime_api.py`

- [ ] **Step 1: 写 GET 状态与 /audio 失败测试**

```python
def test_get_realtime_session_returns_404_when_missing(self) -> None:
    response = self.client.get("/api/v3/realtime/sessions/missing")
    self.assertEqual(response.status_code, 404)


def test_get_realtime_audio_returns_409_when_session_has_no_audio_ready(self) -> None:
    accepted = self.client.post(
        "/api/v3/realtime/sessions",
        content=b"\x00\x00" * 16,
        headers={
            "content-type": "application/octet-stream",
            "x-device-id": "esp-1",
            "x-sample-rate": "16000",
            "x-sample-width": "16",
            "x-channels": "1",
        },
    ).json()

    response = self.client.get(f"/api/v3/realtime/sessions/{accepted['session_id']}/audio")
    self.assertEqual(response.status_code, 409)
```

- [ ] **Step 2: 跑测试确认失败**

Run:

```bash
cd /home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407/20260407_宗教大模型云服务器Demo
python -m unittest tests.test_realtime_api -v
```

Expected:

```text
AssertionError: 404 != 409
```

- [ ] **Step 3: 写最小 GET 实现**

```python
@router.get("/api/v3/realtime/sessions/{session_id}", response_model=RealtimeSessionStatusResponse)
def get_realtime_session(session_id: str) -> RealtimeSessionStatusResponse:
    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session_not_found")
    return RealtimeSessionStatusResponse(**session)


@router.get("/api/v3/realtime/sessions/{session_id}/audio")
def get_realtime_audio(session_id: str) -> Response:
    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session_not_found")
    raise HTTPException(status_code=409, detail="session_not_ready")
```

- [ ] **Step 4: 跑测试确认通过**

Run:

```bash
cd /home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407/20260407_宗教大模型云服务器Demo
python -m unittest tests.test_realtime_api -v
```

Expected:

```text
OK
```

### Task 6: 回归验证

**Files:**
- Test: `/home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407/20260407_宗教大模型云服务器Demo/tests/test_realtime_api.py`
- Test: `/home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407/20260407_宗教大模型云服务器Demo/tests/test_app_healthz.py`

- [ ] **Step 1: 跑 realtime 测试全集**

Run:

```bash
cd /home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407/20260407_宗教大模型云服务器Demo
python -m unittest tests.test_realtime_api -v
```

Expected:

```text
OK
```

- [ ] **Step 2: 跑现有健康检查测试确认无回归**

Run:

```bash
cd /home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407/20260407_宗教大模型云服务器Demo
python -m unittest tests.test_app_healthz -v
```

Expected:

```text
OK
```
