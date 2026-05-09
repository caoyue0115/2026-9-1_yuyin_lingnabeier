# DashScope ASR Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 DashScope 文件 ASR 替换当前云端 Demo 中的假 ASR，使上传音频真正参与 `ASR -> RAG -> LLM -> TTS` 链路。

**Architecture:** 保持现有 `api + worker + redis` 架构不变，只在 worker 内部将固定文本替换为对本地 WAV 的 DashScope ASR 调用。新增 `providers/asr.py` 负责识别请求与响应解析，并在 `/healthz` 与 `trace` 中补齐 ASR 状态和耗时。

**Tech Stack:** FastAPI, RQ, Redis, SQLite, DashScope API, requests, Docker Compose, Python 3.11

---

### Task 1: Add ASR Configuration and Provider Surface

**Files:**
- Create: `20260407_宗教大模型云服务器Demo/src/providers/asr.py`
- Modify: `20260407_宗教大模型云服务器Demo/src/settings.py`
- Modify: `20260407_宗教大模型云服务器Demo/src/models/schema.py`
- Modify: `20260407_宗教大模型云服务器Demo/.env.example`
- Test: `20260407_宗教大模型云服务器Demo/scripts/asr_probe.py`

- [ ] **Step 1: Write the failing ASR probe**

Create `20260407_宗教大模型云服务器Demo/scripts/asr_probe.py`:

```python
from src.providers.asr import asr_health

print(asr_health())
```

- [ ] **Step 2: Run the probe to verify it fails before implementation**

Run: `cd /home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407/20260407_宗教大模型云服务器Demo && PYTHONPATH=. python3 scripts/asr_probe.py`
Expected: FAIL with `ModuleNotFoundError` or `ImportError` for `src.providers.asr`

- [ ] **Step 3: Implement minimal ASR configuration and health surface**

Add these settings:

```python
# src/settings.py
    asr_provider: str = "dashscope"
    asr_model: str = "paraformer-realtime-v2"
    asr_timeout_seconds: int = 30
```

Add ASR health field:

```python
# src/models/schema.py
class HealthzResponse(BaseModel):
    api: str
    redis: str
    sqlite: str
    asr: str
    llm: str
    tts: str
```

Create minimal provider:

```python
# src/providers/asr.py
from src.settings import settings


def asr_health() -> bool:
    return bool(settings.dashscope_api_key and settings.asr_model and settings.asr_provider == "dashscope")
```

Update env template:

```bash
# .env.example
ASR_PROVIDER=dashscope
ASR_MODEL=paraformer-realtime-v2
ASR_TIMEOUT_SECONDS=30
```

- [ ] **Step 4: Run the probe to verify it passes**

Run: `cd /home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407/20260407_宗教大模型云服务器Demo && PYTHONPATH=. python3 scripts/asr_probe.py`
Expected: PASS and print `True` when `.env` contains valid DashScope settings

- [ ] **Step 5: Commit**

```bash
git -C /home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407 add '20260407_宗教大模型云服务器Demo'
git -C /home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407 commit -m "feat: add dashscope asr configuration"
```

### Task 2: Implement DashScope WAV File Recognition

**Files:**
- Modify: `20260407_宗教大模型云服务器Demo/src/providers/asr.py`
- Modify: `20260407_宗教大模型云服务器Demo/requirements.txt`
- Test: `20260407_宗教大模型云服务器Demo/scripts/asr_probe.py`

- [ ] **Step 1: Write the failing real-ASR probe**

Replace `20260407_宗教大模型云服务器Demo/scripts/asr_probe.py`:

```python
from pathlib import Path

from src.providers.asr import transcribe_wav_file


wav_path = Path("data/incoming/test.wav")
print(transcribe_wav_file(wav_path))
```

- [ ] **Step 2: Run the probe to verify it fails before transcription implementation**

Run: `cd /home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407/20260407_宗教大模型云服务器Demo && PYTHONPATH=. python3 scripts/asr_probe.py`
Expected: FAIL because `transcribe_wav_file` is not implemented or `test.wav` is missing

- [ ] **Step 3: Implement file-based DashScope ASR**

Write:

```python
# src/providers/asr.py
from __future__ import annotations

from pathlib import Path

import requests

from src.settings import settings


def asr_health() -> bool:
    return bool(settings.dashscope_api_key and settings.asr_model and settings.asr_provider == "dashscope")


def _extract_text(payload: dict) -> str:
    """
    Parse the first useful recognized text field from the DashScope response.
    Start with a strict, minimal parser and expand only if the real response differs.
    """
```

```python
def transcribe_wav_file(wav_path: Path) -> tuple[str | None, str | None]:
    if not wav_path.exists():
        return None, "asr_missing_wav"

    url = settings.dashscope_base_url.rstrip("/") + "/api/v1/services/audio/asr/transcription"
    headers = {"Authorization": f"Bearer {settings.dashscope_api_key}"}

    with wav_path.open("rb") as fh:
        files = {"file": (wav_path.name, fh, "audio/wav")}
        data = {"model": settings.asr_model}
        try:
            resp = requests.post(url, headers=headers, files=files, data=data, timeout=settings.asr_timeout_seconds)
        except requests.Timeout:
            return None, "asr_timeout"
        except Exception:
            return None, "asr_request_failed"

    if resp.status_code != 200:
        return None, f"asr_http_{resp.status_code}"

    try:
        body = resp.json()
    except Exception:
        return None, "asr_invalid_response"

    text = _extract_text(body).strip()
    if not text:
        return None, "asr_empty_text"
    return text, None
```

If DashScope returns a different response shape in practice, update `_extract_text()` against the real payload instead of broad guessing.

- [ ] **Step 4: Create a test WAV and verify the probe reaches the API**

Run:

```bash
cd /home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407/20260407_宗教大模型云服务器Demo
python3 - <<'PY'
import wave
from pathlib import Path

out = Path("data/incoming/test.wav")
out.parent.mkdir(parents=True, exist_ok=True)
with wave.open(str(out), "wb") as wf:
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(16000)
    wf.writeframes(b"\x00\x00" * 16000)
print(out)
PY
PYTHONPATH=. python3 scripts/asr_probe.py
```

Expected:

- Probe no longer fails with import errors
- If DashScope rejects silence, it should fail with an `asr_*` error code rather than a crash

- [ ] **Step 5: Commit**

```bash
git -C /home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407 add '20260407_宗教大模型云服务器Demo'
git -C /home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407 commit -m "feat: implement dashscope wav asr provider"
```

### Task 3: Replace Fake ASR in the Worker Pipeline

**Files:**
- Modify: `20260407_宗教大模型云服务器Demo/src/workers/pipeline.py`
- Modify: `20260407_宗教大模型云服务器Demo/src/storage/db.py`
- Modify: `20260407_宗教大模型云服务器Demo/src/api/tasks.py`
- Test: `20260407_宗教大模型云服务器Demo/scripts/smoke_poll.py`

- [ ] **Step 1: Write the failing pipeline expectation**

Update `20260407_宗教大模型云服务器Demo/scripts/smoke_poll.py` to assert that completed output includes `question_text` from ASR and `trace["asr_ms"]`.

- [ ] **Step 2: Run the smoke to verify it fails before worker replacement**

Run: `cd /home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407/20260407_宗教大模型云服务器Demo && PYTHONPATH=. python3 scripts/smoke_poll.py`
Expected: FAIL or reveal `question_text` still fixed without `asr_ms`

- [ ] **Step 3: Replace fake ASR with real WAV transcription**

Modify worker:

```python
# src/workers/pipeline.py
from pathlib import Path

from src.providers.asr import transcribe_wav_file
...
        update_task_status(task_id, "running", "asr", 0.2)
        asr_started = time.perf_counter()
        wav_path = Path(row["input_wav_path"])
        question_text, asr_error = transcribe_wav_file(wav_path)
        trace["asr_ms"] = int((time.perf_counter() - asr_started) * 1000)
        if asr_error:
            raise RuntimeError(asr_error)
```

Refine failure mapping:

```python
# src/storage/db.py
def mark_task_failed(...):
    ...
```

Use the ASR error code directly instead of only `type(exc).__name__.lower()`:

```python
# src/workers/pipeline.py
    except RuntimeError as exc:
        code = str(exc)
        mark_task_failed(task_id, "asr" if code.startswith("asr_") else "pipeline", code, code, trace)
```

Remove fake ASR assumptions from scripts and config expectations. `src/api/tasks.py` should remain contract-compatible and not need semantic changes beyond the worker’s new output.

- [ ] **Step 4: Run the worker smoke to verify `question_text` comes from ASR**

Run the existing local or cloud smoke after bringing up API, worker, and Redis.
Expected:

- `status` reaches `done` for good audio
- `question_text` is no longer hard-coded
- `trace["asr_ms"]` exists

- [ ] **Step 5: Commit**

```bash
git -C /home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407 add '20260407_宗教大模型云服务器Demo'
git -C /home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407 commit -m "feat: replace fake asr with dashscope transcription"
```

### Task 4: Update Health Check and Runtime Config

**Files:**
- Modify: `20260407_宗教大模型云服务器Demo/src/app.py`
- Modify: `20260407_宗教大模型云服务器Demo/src/models/schema.py`
- Modify: `20260407_宗教大模型云服务器Demo/.env.example`
- Modify: `20260407_宗教大模型云服务器Demo/.env`
- Test: `curl http://127.0.0.1/healthz`

- [ ] **Step 1: Write the failing health expectation**

Health response should now include `asr`.

- [ ] **Step 2: Run health check to verify it fails before update**

Run: `curl -sS http://127.0.0.1/healthz`
Expected: response lacks `asr`

- [ ] **Step 3: Implement ASR visibility and remove fake ASR config**

Modify:

```python
# src/app.py
from src.providers.asr import asr_health
...
        asr="ok" if asr_health() else "down",
```

Remove fake config from env examples:

```bash
# .env.example
ASR_PROVIDER=dashscope
ASR_MODEL=paraformer-realtime-v2
ASR_TIMEOUT_SECONDS=30
```

Delete:

```bash
FAKE_ASR_TEXT=什么是无相
```

Mirror the same cleanup in the real `.env` on the server.

- [ ] **Step 4: Run health check to verify ASR status is reported**

Run: `curl -sS http://127.0.0.1/healthz`
Expected:

```json
{"api":"ok","redis":"ok","sqlite":"ok","asr":"ok","llm":"ok","tts":"ok"}
```

- [ ] **Step 5: Commit**

```bash
git -C /home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407 add '20260407_宗教大模型云服务器Demo'
git -C /home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407 commit -m "feat: expose asr health and config"
```

### Task 5: Deploy ASR Changes to the Cloud Server and Verify Real Audio

**Files:**
- Modify: remote `/app/religion_demo_20260407/.env`
- Modify: remote `/app/religion_demo_20260407/src/providers/asr.py`
- Test: remote API at `http://<CURRENT_BASE_URL>`

- [ ] **Step 1: Upload the updated project to the cloud server**

Run:

```bash
scp -o StrictHostKeyChecking=no -r /home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407/20260407_宗教大模型云服务器Demo/. OLD_PUBLIC_ENTRY_DISABLED_SSH:/app/religion_demo_20260407/
```

- [ ] **Step 2: Update the remote `.env` to remove fake ASR and add real ASR fields**

Ensure `/app/religion_demo_20260407/.env` contains:

```bash
ASR_PROVIDER=dashscope
ASR_MODEL=paraformer-realtime-v2
ASR_TIMEOUT_SECONDS=30
```

Ensure it no longer contains:

```bash
FAKE_ASR_TEXT=什么是无相
```

- [ ] **Step 3: Rebuild and restart the cloud deployment**

Run on the server:

```bash
cd /app/religion_demo_20260407
docker-compose up -d --build
```

Expected: `api`, `worker`, and `redis` all return to `Up`

- [ ] **Step 4: Verify health and logs**

Run:

```bash
curl -sS http://127.0.0.1/healthz
docker-compose logs --tail=80 worker
```

Expected:

- `/healthz` reports `asr="ok"`
- Worker boots without import or provider errors

- [ ] **Step 5: Submit real audio and verify end-to-end result**

Use a real PCM/WAV sample that contains a short Chinese佛学问题. Submit it via:

```bash
curl -sS -X POST http://127.0.0.1/api/v2/tasks \
  -H 'content-type: application/octet-stream' \
  -H 'x-device-id: esp-demo-001' \
  -H 'x-sample-rate: 16000' \
  -H 'x-sample-width: 16' \
  -H 'x-channels: 1' \
  --data-binary '@/tmp/real_question.pcm'
```

Poll:

```bash
curl -sS http://127.0.0.1/api/v2/tasks/<task_id>
```

Expected:

- `status=done`
- `question_text` contains recognized speech
- `trace.asr_ms` exists
- `references` exists
- `audio_url` exists or `tts_status=failed` if TTS alone fails

- [ ] **Step 6: Verify ASR failure behavior**

Submit an empty or corrupted payload:

```bash
curl -sS -X POST http://127.0.0.1/api/v2/tasks \
  -H 'content-type: application/octet-stream' \
  -H 'x-device-id: esp-demo-001' \
  --data-binary ''
```

Or submit malformed audio and poll task status.

Expected:

- task ends in `failed`
- `error_code` starts with `asr_`

- [ ] **Step 7: Commit**

```bash
git -C /home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407 add '20260407_宗教大模型云服务器Demo'
git -C /home/aitopia/Engineering_Projects/.worktrees/religion-demo-20260407 commit -m "test: verify dashscope asr end to end"
```
