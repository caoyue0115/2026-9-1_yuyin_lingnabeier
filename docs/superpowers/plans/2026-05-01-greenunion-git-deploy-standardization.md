# greenunion-sh Git Deploy Standardization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the current `greenunion-sh` copy-based deployment into a tracked git release flow without disturbing the currently verified running service.

**Architecture:** Keep the existing running directory as the rollback baseline, introduce repository-managed GreenUnion deployment files, move runtime state into a shared directory, then cut over with a git checkout release directory. The first deployment must be reversible by switching Docker Compose back to the current copy directory or by checking out the previous commit.

**Tech Stack:** Git, Docker Compose, FastAPI/Uvicorn, RQ worker, Redis, local bind-mounted `data/` and `indices/`.

---

## Current Verified State

- Server target: `greenunion-sh`
- Current running app directory: `/home/ubuntu/religion_demo_v3_greenunion_app`
- Current containers:
  - `religion_demo_v3_greenunion_app-api-1`
  - `religion_demo_v3_greenunion_app-worker-1`
  - `religion_demo_v3_greenunion_app-redis-1`
- Current runtime state:
  - `/home/ubuntu/religion_demo_v3_greenunion_app/.env`
  - `/home/ubuntu/religion_demo_v3_greenunion_app/data`
  - `/home/ubuntu/religion_demo_v3_greenunion_app/indices`
- Current code state verified by hash against local latest commit:
  - `src/rag/ingest.py`
  - `config/asr_hotwords.buddhism.json`
  - `requirements.txt`
- Current index state:
  - `doc_titles=65`
  - `chunk_items=181`
- Current health check:
  - `api/redis/sqlite/asr/llm/tts` all `ok`

## Target Layout

```text
/home/ubuntu/religion_demo_v3_greenunion_app        # current baseline, keep untouched until cutover is verified
/home/ubuntu/religion_demo_shared
  .env                                              # server-local secret config, never committed
  data                                              # server-local runtime data bind mount
  indices                                           # server-local RAG index bind mount
  logs                                              # optional future log bind mount
/home/ubuntu/releases/religion_demo
  20260407_宗教大模型云服务器Demo/                  # git checkout working tree
```

## Files To Add Or Modify In The Repository

- Create: `Dockerfile.greenunion`
  - GreenUnion-specific build file with Tencent/China-friendly apt and pip mirror settings.
- Create: `docker-compose.greenunion.yml`
  - Compose file that uses `Dockerfile.greenunion`.
  - Uses explicit project name when invoked: `-p religion_demo_greenunion`.
  - Mounts `${GREENUNION_DATA_DIR:-/home/ubuntu/religion_demo_shared/data}:/app/data`.
  - Mounts `${GREENUNION_INDICES_DIR:-/home/ubuntu/religion_demo_shared/indices}:/app/indices`.
  - Reads env file from `${GREENUNION_ENV_FILE:-/home/ubuntu/religion_demo_shared/.env}`.
- Create: `docs/deploy/greenunion-sh-runbook.md`
  - Operator runbook with first migration, deploy, rollback, and verification commands.
- Modify: `.gitignore`
  - Ensure local runtime assets remain ignored: `.env`, `data/incoming/`, `data/output/`, `data/tasks.db`, `indices/`, `tmp/`, `*.tar.gz`.
  - Do not ignore repository-managed `data/buddhism/*.md`.

## Server Files To Move During Execution

These moves are server-side deployment execution steps, not part of this plan-writing step.

- Copy, then verify:
  - `/home/ubuntu/religion_demo_v3_greenunion_app/.env` to `/home/ubuntu/religion_demo_shared/.env`
  - `/home/ubuntu/religion_demo_v3_greenunion_app/data` to `/home/ubuntu/religion_demo_shared/data`
  - `/home/ubuntu/religion_demo_v3_greenunion_app/indices` to `/home/ubuntu/religion_demo_shared/indices`
- Do not delete the original runtime directory until at least one successful deploy and rollback drill have been completed.

---

### Task 1: Add GreenUnion-Specific Dockerfile

**Files:**
- Create: `Dockerfile.greenunion`

- [ ] **Step 1: Create `Dockerfile.greenunion`**

Use the currently verified server-specific Dockerfile content so the cloud build behavior is no longer an invisible manual diff.

```dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ENV PIP_TRUSTED_HOST=mirrors.aliyun.com
ENV PIP_DEFAULT_TIMEOUT=600
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN sed -i 's|http://deb.debian.org|http://mirrors.tencentyun.com|g' /etc/apt/sources.list.d/debian.sources

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    libopus0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --retries 10 -r requirements.txt

COPY src ./src
COPY scripts ./scripts
COPY config ./config
COPY README.md ./README.md
COPY 部署计划大纲.md ./部署计划大纲.md

CMD ["uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "8010"]
```

- [ ] **Step 2: Verify Dockerfile diff**

Run:

```bash
git diff -- Dockerfile.greenunion
```

Expected:

```text
Dockerfile.greenunion contains the pip mirror, Tencent apt mirror, and pip retry settings currently present on greenunion-sh.
```

- [ ] **Step 3: Commit**

```bash
git add Dockerfile.greenunion
git commit -m "Add GreenUnion deployment Dockerfile"
```

---

### Task 2: Add GreenUnion Docker Compose File

**Files:**
- Create: `docker-compose.greenunion.yml`

- [ ] **Step 1: Create `docker-compose.greenunion.yml`**

```yaml
services:
  redis:
    image: redis:7-alpine
    restart: unless-stopped

  api:
    build:
      context: .
      dockerfile: Dockerfile.greenunion
    restart: unless-stopped
    command: uvicorn src.app:app --host 0.0.0.0 --port 8010
    env_file:
      - ${GREENUNION_ENV_FILE:-/home/ubuntu/religion_demo_shared/.env}
    volumes:
      - ${GREENUNION_DATA_DIR:-/home/ubuntu/religion_demo_shared/data}:/app/data
      - ${GREENUNION_INDICES_DIR:-/home/ubuntu/religion_demo_shared/indices}:/app/indices
    ports:
      - "80:8010"
    depends_on:
      - redis

  worker:
    build:
      context: .
      dockerfile: Dockerfile.greenunion
    restart: unless-stopped
    command: rq worker -u redis://redis:6379/0 religion_tasks
    env_file:
      - ${GREENUNION_ENV_FILE:-/home/ubuntu/religion_demo_shared/.env}
    volumes:
      - ${GREENUNION_DATA_DIR:-/home/ubuntu/religion_demo_shared/data}:/app/data
      - ${GREENUNION_INDICES_DIR:-/home/ubuntu/religion_demo_shared/indices}:/app/indices
    depends_on:
      - redis
```

- [ ] **Step 2: Validate Compose Syntax Locally**

Run:

```bash
tmpdir="$(mktemp -d)"
touch "$tmpdir/.env"
mkdir -p "$tmpdir/data" "$tmpdir/indices"
GREENUNION_ENV_FILE="$tmpdir/.env" \
GREENUNION_DATA_DIR="$tmpdir/data" \
GREENUNION_INDICES_DIR="$tmpdir/indices" \
docker-compose -f docker-compose.greenunion.yml config >/tmp/greenunion-compose.rendered.yml
rm -rf "$tmpdir"
```

Expected:

```text
Exit code 0. Rendered config contains the temporary env_file and volume paths used for local syntax validation.
```

- [ ] **Step 3: Commit**

```bash
git add docker-compose.greenunion.yml
git commit -m "Add GreenUnion compose deployment"
```

---

### Task 3: Add GreenUnion Deployment Runbook

**Files:**
- Create: `docs/deploy/greenunion-sh-runbook.md`

- [ ] **Step 1: Create the runbook**

```markdown
# greenunion-sh Deployment Runbook

## Scope

This runbook applies only to `greenunion-sh`. It does not apply to Guangzhou or old `religion-demo` hosts.

## Stable Paths

- Current rollback baseline: `/home/ubuntu/religion_demo_v3_greenunion_app`
- Shared runtime state: `/home/ubuntu/religion_demo_shared`
- Git release checkout: `/home/ubuntu/releases/religion_demo`

## First-Time Migration

Run these commands on `greenunion-sh`.

```bash
set -euo pipefail

mkdir -p /home/ubuntu/religion_demo_shared
cp -a /home/ubuntu/religion_demo_v3_greenunion_app/.env /home/ubuntu/religion_demo_shared/.env
cp -a /home/ubuntu/religion_demo_v3_greenunion_app/data /home/ubuntu/religion_demo_shared/data
cp -a /home/ubuntu/religion_demo_v3_greenunion_app/indices /home/ubuntu/religion_demo_shared/indices
mkdir -p /home/ubuntu/religion_demo_shared/logs

test -f /home/ubuntu/religion_demo_shared/.env
test -d /home/ubuntu/religion_demo_shared/data
test -d /home/ubuntu/religion_demo_shared/indices
```

## Clone Or Update Release Checkout

```bash
set -euo pipefail

mkdir -p /home/ubuntu/releases
if [ ! -d /home/ubuntu/releases/religion_demo/.git ]; then
  git clone git@github.com:675401943/20260407_-Demo-.git /home/ubuntu/releases/religion_demo
fi

cd /home/ubuntu/releases/religion_demo
git fetch --all --prune
git checkout religion-demo-20260407
git pull --ff-only
git rev-parse HEAD
```

## Deploy

```bash
set -euo pipefail

cd /home/ubuntu/releases/religion_demo/20260407_宗教大模型云服务器Demo
docker compose -p religion_demo_greenunion -f docker-compose.greenunion.yml build
docker compose -p religion_demo_greenunion -f docker-compose.greenunion.yml up -d
docker compose -p religion_demo_greenunion -f docker-compose.greenunion.yml ps
```

## Verify

```bash
set -euo pipefail

curl -sS --max-time 10 http://127.0.0.1/healthz
docker compose -p religion_demo_greenunion -f docker-compose.greenunion.yml logs --tail=120 api
docker compose -p religion_demo_greenunion -f docker-compose.greenunion.yml logs --tail=120 worker
python3 - <<'PY'
import json
p='/home/ubuntu/religion_demo_shared/indices/buddhism.meta.json'
data=json.load(open(p, encoding='utf-8'))
chunks=data.get('chunks') or []
print('chunk_items', len(chunks))
print('doc_titles', len({x.get('source_title') for x in chunks if isinstance(x, dict)}))
PY
```

Expected:

```text
healthz reports api/redis/sqlite/asr/llm/tts as ok.
chunk_items is 181.
doc_titles is 65.
```

## Rollback

Rollback to a previous git commit:

```bash
set -euo pipefail

cd /home/ubuntu/releases/religion_demo
git checkout <previous_commit_sha>
cd /home/ubuntu/releases/religion_demo/20260407_宗教大模型云服务器Demo
docker compose -p religion_demo_greenunion -f docker-compose.greenunion.yml build
docker compose -p religion_demo_greenunion -f docker-compose.greenunion.yml up -d
curl -sS --max-time 10 http://127.0.0.1/healthz
```

Emergency rollback to the old copy-based baseline:

```bash
set -euo pipefail

cd /home/ubuntu/religion_demo_v3_greenunion_app
docker compose up -d --build
curl -sS --max-time 10 http://127.0.0.1/healthz
```
```

- [ ] **Step 2: Check for forbidden placeholders**

Run:

```bash
grep -nE 'TBD|TODO|fill in|implement later' docs/deploy/greenunion-sh-runbook.md
```

Expected:

```text
No output.
```

- [ ] **Step 3: Commit**

```bash
git add docs/deploy/greenunion-sh-runbook.md
git commit -m "Document GreenUnion deployment runbook"
```

---

### Task 4: Verify Ignore Rules For Runtime State

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Inspect current ignore rules**

Run:

```bash
sed -n '1,160p' .gitignore
```

Expected existing entries include:

```gitignore
.env
.venv/
__pycache__/
*.pyc
data/incoming/
data/output/
data/tasks.db
indices/
tmp/
bug*.txt
esp_idf_demo/managed_components/
esp_idf_demo_handoff_*/
*.tar.gz
```

- [ ] **Step 2: Add only missing runtime ignore rules**

If any of the expected entries are missing, add them. Do not add `data/` because `data/buddhism/*.md` is repository-managed knowledge base content.

- [ ] **Step 3: Verify tracked knowledge base files remain visible**

Run:

```bash
git ls-files data/buddhism | sed -n '1,20p'
```

Expected:

```text
Tracked Buddhism markdown files are listed.
```

- [ ] **Step 4: Commit if `.gitignore` changed**

```bash
git add .gitignore
git commit -m "Clarify runtime ignore rules"
```

If `.gitignore` did not change, skip this commit.

---

### Task 5: Dry-Run Release Checkout On greenunion-sh

**Files:**
- No repository file changes.
- Server-only path: `/home/ubuntu/releases/religion_demo`

- [ ] **Step 1: Confirm server target and current baseline**

Run from WSL:

```bash
ssh greenunion-sh "hostname; docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"
```

Expected:

```text
Host is greenunion-sh.
Current copy-based containers are visible and healthy.
```

- [ ] **Step 2: Clone without touching running service**

Run on `greenunion-sh`:

```bash
set -euo pipefail
mkdir -p /home/ubuntu/releases
git clone git@github.com:675401943/20260407_-Demo-.git /home/ubuntu/releases/religion_demo
cd /home/ubuntu/releases/religion_demo
git checkout religion-demo-20260407
git rev-parse HEAD
```

Expected:

```text
The printed commit SHA matches the intended release commit.
No Docker command is run.
No running container changes.
```

- [ ] **Step 3: Validate repository files on server**

Run:

```bash
cd /home/ubuntu/releases/religion_demo/20260407_宗教大模型云服务器Demo
test -f Dockerfile.greenunion
test -f docker-compose.greenunion.yml
docker compose -f docker-compose.greenunion.yml config >/tmp/greenunion-compose.rendered.yml
```

Expected:

```text
Exit code 0.
```

---

### Task 6: Migrate Shared Runtime State

**Files:**
- No repository file changes.
- Server-only path: `/home/ubuntu/religion_demo_shared`

- [ ] **Step 1: Copy runtime state**

Run on `greenunion-sh`:

```bash
set -euo pipefail
mkdir -p /home/ubuntu/religion_demo_shared
cp -a /home/ubuntu/religion_demo_v3_greenunion_app/.env /home/ubuntu/religion_demo_shared/.env
cp -a /home/ubuntu/religion_demo_v3_greenunion_app/data /home/ubuntu/religion_demo_shared/data
cp -a /home/ubuntu/religion_demo_v3_greenunion_app/indices /home/ubuntu/religion_demo_shared/indices
mkdir -p /home/ubuntu/religion_demo_shared/logs
```

- [ ] **Step 2: Verify shared state**

Run:

```bash
set -euo pipefail
test -f /home/ubuntu/religion_demo_shared/.env
test -d /home/ubuntu/religion_demo_shared/data
test -d /home/ubuntu/religion_demo_shared/indices
python3 - <<'PY'
import json
p='/home/ubuntu/religion_demo_shared/indices/buddhism.meta.json'
data=json.load(open(p, encoding='utf-8'))
chunks=data.get('chunks') or []
print('chunk_items', len(chunks))
print('doc_titles', len({x.get('source_title') for x in chunks if isinstance(x, dict)}))
PY
```

Expected:

```text
chunk_items 181
doc_titles 65
```

---

### Task 7: Cut Over To Git-Tracked Compose

**Files:**
- No repository file changes.
- Server runtime changes: Docker Compose build and container replacement.

- [ ] **Step 1: Build git-tracked images**

Run on `greenunion-sh`:

```bash
set -euo pipefail
cd /home/ubuntu/releases/religion_demo/20260407_宗教大模型云服务器Demo
docker compose -p religion_demo_greenunion -f docker-compose.greenunion.yml build
```

Expected:

```text
Build succeeds for api and worker.
```

- [ ] **Step 2: Start git-tracked stack**

Run:

```bash
set -euo pipefail
cd /home/ubuntu/releases/religion_demo/20260407_宗教大模型云服务器Demo
docker compose -p religion_demo_greenunion -f docker-compose.greenunion.yml up -d
docker compose -p religion_demo_greenunion -f docker-compose.greenunion.yml ps
```

Expected:

```text
api, worker, and redis are up.
Port 80 maps to api:8010.
```

- [ ] **Step 3: Verify service health**

Run:

```bash
curl -sS --max-time 10 http://127.0.0.1/healthz
```

Expected:

```json
{"api":"ok","redis":"ok","sqlite":"ok","asr":"ok","llm":"ok","tts":"ok"}
```

- [ ] **Step 4: Verify running container file hashes**

Run locally and on server, then compare output:

```bash
sha256sum src/rag/ingest.py config/asr_hotwords.buddhism.json requirements.txt
```

```bash
docker exec religion_demo_greenunion-api-1 sha256sum /app/src/rag/ingest.py /app/config/asr_hotwords.buddhism.json /app/requirements.txt
docker exec religion_demo_greenunion-worker-1 sha256sum /app/src/rag/ingest.py /app/config/asr_hotwords.buddhism.json /app/requirements.txt
```

Expected:

```text
Hashes match the intended release commit.
```

---

### Task 8: Post-Cutover Cleanup Decision

**Files:**
- No required repository file changes.

- [ ] **Step 1: Keep the old baseline for one validation window**

Do not delete `/home/ubuntu/religion_demo_v3_greenunion_app` immediately. Keep it available for emergency rollback.

- [ ] **Step 2: Record the deployment**

Create or append `docs/superpowers/summaries/YYYY-MM-DD-greenunion-deploy.md` with:

```markdown
# greenunion-sh Git Deployment Summary

- Release commit:
- Deploy time:
- Previous baseline directory: `/home/ubuntu/religion_demo_v3_greenunion_app`
- New release directory: `/home/ubuntu/releases/religion_demo`
- Shared state directory: `/home/ubuntu/religion_demo_shared`
- Healthz result:
- Index stats:
- Rollback command tested: yes/no
```

- [ ] **Step 3: Commit the summary**

```bash
git add docs/superpowers/summaries/YYYY-MM-DD-greenunion-deploy.md
git commit -m "Record GreenUnion git deployment"
```

---

## Verification Checklist

- [ ] Repository has `Dockerfile.greenunion`.
- [ ] Repository has `docker-compose.greenunion.yml`.
- [ ] Repository has `docs/deploy/greenunion-sh-runbook.md`.
- [ ] `.env`, runtime output, local DB, indexes, tarballs, and build artifacts are ignored.
- [ ] `data/buddhism/*.md` remains tracked.
- [ ] Server shared state exists at `/home/ubuntu/religion_demo_shared`.
- [ ] Server release checkout exists at `/home/ubuntu/releases/religion_demo`.
- [ ] Running service reports healthy `/healthz`.
- [ ] Running container file hashes match the intended commit.
- [ ] Index stats remain `doc_titles=65`, `chunk_items=181`.
- [ ] Rollback path remains available.

## Not In Scope

- Do not modify Guangzhou or old `religion-demo` servers.
- Do not use `OLD_PUBLIC_ENTRY_DISABLED`.
- Do not remove the current greenunion copy-based baseline during first migration.
- Do not commit `.env`, API keys, generated indexes, uploaded audio, SQLite runtime DB, or handoff tarballs.
