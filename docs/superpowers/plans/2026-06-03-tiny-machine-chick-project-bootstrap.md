# Tiny Machine Chick Project Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bootstrap an independent private `20260601_tiny_chicken_coffee_robot` project for the `小机仔` v6_tiny line from the current v6 source baseline, without carrying v6 git history, v6 production defaults, religion-domain content, or secret-bearing files into the new repository history.

**Architecture:** Create a clean source copy on `/mnt/data100`, immediately prune v6-only and religion-domain residue before new git history exists, then initialize a fresh private repository with tracked isolation tests, secret-scan gates, tiny naming, 32MB Flash + 8MB PSRAM device gates, display/MJPEG scaffolding, Doubao provider scaffolding, and Guangzhou-only deployment documentation. Phase 1 is a scaffold and safety-isolation phase; it does not deploy, publish OTA, upload artifacts, operate devices, implement coffee RAG, build an app, add BLE provisioning, add alarms, or create a custom `小机仔` WakeNet model.

**Tech Stack:** ESP-IDF v5.5.x, ESP32-S3-class 32MB Flash + 8MB PSRAM target, current WakeNet `小明同学` model, GPIO7 trigger, GPIO0 Wi-Fi reprovision trigger if present in the copied baseline, Python/FastAPI cloud, Redis/SQLite, Docker Compose, Volcengine Ark Doubao-Seed-2.0-mini text path, existing Volcengine TTS path, FFmpeg MJPEG conversion, gitleaks or trufflehog secret scanning.

---

## Source Of Truth

- Design spec: `/mnt/data100/GMT/20260521_16flash_8psram/docs/superpowers/specs/2026-06-02-tiny-chicken-coffee-robot-design.md`
- Current plan: `/mnt/data100/GMT/20260521_16flash_8psram/docs/superpowers/plans/2026-06-03-tiny-machine-chick-project-bootstrap.md`
- Source v6 repo: `/mnt/data100/GMT/20260521_16flash_8psram`
- New project directory: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot`
- New GitHub repository: `https://github.com/675401943/20260601_tiny_chicken_coffee_robot.git`
- Material root: `/mnt/data100/GMT/assets/20260602_tiny_chicken_materials/20260602_小机仔`
- Material archive: `/mnt/data100/20260602_小机仔.rar`
- Product name and future custom wake-word spelling: `小机仔`
- Phase 1 wake word: `小明同学`
- Phase 1 repository visibility: private

## Non-Negotiable Guardrails

- Keep all project, build, temporary, and delivery files under `/mnt/data100`.
- Do not read, print, modify, commit, or upload `.env`, token files, Wi-Fi passwords, private keys, certificates, or secret-bearing files.
- Do not fork v6 and do not carry v6 git history into the new repository.
- Do not deploy cloud services, SSH to Guangzhou, publish OTA, upload release artifacts, or operate hardware during bootstrap.
- Do not touch the old v6 production line containers, databases, Redis, logs, runtime configuration, or server.
- Before every implementation phase, run `git status --short --branch` in the relevant repo and preserve user-owned changes.
- Before the first push and every later push, run a redacted secret scan and the tracked secret-name gate.


## Shared Static Scan Terms

Every cleanup task, tracked-file test, `git grep`, and secret/static scan that checks religion-domain residue must use this same term list over active git tracked files, excluding only `docs/migration/**`:

```text
佛
佛说
佛学
佛教
净土
菩萨
阿弥陀
念佛
东林
往生
极乐
观音
经文
祷告
圣经
buddhism
prayer
sermon
```

The scan is intentionally broad. It is not limited to prompt, RAG, settings, or config paths. Residual ignored disk files are not accepted as test inputs; Task 2 deletes or migrates those files before `git init`.

## File And Directory Responsibilities

- `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/.gitignore`: blocks local secrets, runtime state, build outputs, generated binaries, caches, and delivery archives.
- `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/.github/workflows/secret-scan.yml`: required CI secret scan for pushes and pull requests.
- `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/scripts/security/secret_scan.sh`: local pre-push-compatible secret scan wrapper.
- `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/scripts/git-hooks/pre-push`: tracked hook template that calls `scripts/security/secret_scan.sh`.
- `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/README.md`: tiny project identity and phase 1 boundaries, using old-line-neutral wording rather than old server tokens.
- `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/docs/migration/v6-bootstrap/`: allowed location for retained migration notes. Isolation tests exclude this path.
- `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/docs/tiny/repository-bootstrap.md`: clean-copy, prune, new-history, remote, and secret-scan record.
- `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/docs/tiny/naming-and-product-boundaries.md`: `小机仔` naming, removed v6 domain content, and phase 1 scope boundaries.
- `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/docs/tiny/partition-32m8m-design.md`: 32MB Flash + 8MB PSRAM partition budget and measurement gate.
- `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/docs/tiny/display-asset-format.md`: 320x240 display, 240x240 safe region, MJPEG conversion, `.idx` binary format, loop flags, animation names, and manifest schema.
- `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/docs/tiny/mjpeg-hardware-validation.md`: early device throughput gate for 240x240 MJPEG at 15fps.
- `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/docs/deployment/guangzhou-runbook.md`: Guangzhou deployment layout and approval-only execution procedure.
- `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/scripts/tiny_assets/convert_mjpeg_assets.py`: FFmpeg wrapper for 240x240, 15fps, `-q:v 5` conversion.
- `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/scripts/tiny_assets/write_mjpeg_idx.py`: `.idx` writer using the format defined in docs.
- `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/src/providers/tiny_doubao.py`: isolated Doubao provider for text output and direct-audio capability probing.
- `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/tests/test_tiny_project_safety.py`: tracked-file isolation tests for secrets policy, naming, v6 production target leakage, religion-domain leakage, and deferred-scope boundaries.
- `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/tests/test_tiny_healthz.py`: healthz readiness and no-secret-response tests.
- `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/tests/test_tiny_display_assets.py`: `.mjpeg + .idx` format tests.
- `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/tests/test_tiny_doubao_provider.py`: mocked Doubao provider tests without real credentials.
- `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/tests/test_tiny_esp_assets.py`: ESP static tests adapted to tiny, 32MB partition, GPIO7/WakeNet retention, and OTA safety defaults.
- `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/tests/test_tiny_release_gate.py`: tiny/32MB release and partition gate replacing the v6 16MB N16R8 release gate.

---

### Task 1: Verify Source Baseline And Create Clean Copy

**Files:**
- Read: `/mnt/data100/GMT/20260521_16flash_8psram/docs/superpowers/specs/2026-06-02-tiny-chicken-coffee-robot-design.md`
- Copy from: `/mnt/data100/GMT/20260521_16flash_8psram`
- Create directory: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot`

- [ ] **Step 1: Confirm source repo state without pinning an obsolete HEAD**

Run:

```bash
cd /mnt/data100/GMT/20260521_16flash_8psram
git status --short --branch
git log --oneline -5
```

Expected:

```text
## main...origin/main
```

The recent log must include the tiny design spec and tiny bootstrap plan commits, including `docs: finalize tiny machine chick review notes` and `docs: plan tiny machine chick project bootstrap` or later revisions. If the worktree is dirty, stop and report the paths before copying.

- [ ] **Step 2: Confirm the target path is not already populated**

Run:

```bash
test ! -e /mnt/data100/GMT/20260601_tiny_chicken_coffee_robot
```

Expected: command exits with status `0`.

If the path exists, run:

```bash
find /mnt/data100/GMT/20260601_tiny_chicken_coffee_robot -mindepth 1 -maxdepth 1 -print
```

Expected: no output. If files are listed, stop and ask for owner direction.

- [ ] **Step 3: Copy source to the 100GB disk without rebuildable outputs**

Run:

```bash
mkdir -p /mnt/data100/GMT/20260601_tiny_chicken_coffee_robot
rsync -a \
  --exclude 'build*/' \
  --exclude '.pytest_cache/' \
  --exclude '**/__pycache__/' \
  --exclude 'tmp/' \
  --exclude '*.tar.gz' \
  --exclude '*.zip' \
  --exclude '*.rar' \
  --exclude '*.bin' \
  --exclude '*.elf' \
  --exclude '*.map' \
  /mnt/data100/GMT/20260521_16flash_8psram/ \
  /mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/
```

Expected: source files are copied; build outputs and delivery archives are absent.

- [ ] **Step 4: Remove old v6 git history immediately**

Run:

```bash
rm -rf /mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/.git
test ! -e /mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/.git
```

Expected: command exits with status `0`. The source v6 repository remains untouched.

### Task 2: Prune v6 Residue Before New Git History

**Files:**
- Delete from new copy before git init: listed v6-only paths
- Modify before git init: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/src/services/realtime_session.py`
- Modify before git init: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/src/workers/pipeline.py`
- Modify before git init: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/src/providers/llm.py`
- Modify before git init: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/src/settings.py`
- Create: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/docs/migration/v6-bootstrap/`
- Create later: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/docs/tiny/repository-bootstrap.md`

- [ ] **Step 1: Delete enumerated religion-domain and handoff residue before `git init`**

Run from the new project directory:

```bash
cd /mnt/data100/GMT/20260601_tiny_chicken_coffee_robot
rm -rf \
  data/buddhism \
  config/asr_hotwords.buddhism.json \
  src/rag \
  handoff \
  部署计划大纲.md \
  20260409_流式传输
find docs/deploy -maxdepth 1 -type f \( -name 'greenunion-sh-*' -o -name 'v6-n16r8-release-handoff-*' \) -delete
```

Expected: these paths are absent from the clean copy before the new repository exists. `src/rag/` is deleted by default; keeping it is allowed only in a later tiny-specific task that renames the module, removes old knowledge calls, and adds tests proving no copied religion-domain data is reachable.

- [ ] **Step 2: Replace hard-coded religion fallback answers and prompts before `git init`**

Run discovery on the four known leak paths:

```bash
rg -n '佛说不可曰|佛学问答助手|data_dir|buddhism|few-shot|few_shot' \
  src/services/realtime_session.py \
  src/workers/pipeline.py \
  src/providers/llm.py \
  src/settings.py
```

Apply these exact cleanup rules:

- In `src/services/realtime_session.py`, replace every fallback assignment equivalent to `answer_text = "佛说不可曰"` with `answer_text = "我还没听清，可以再说一遍咖啡问题吗？"`.
- In `src/workers/pipeline.py`, replace every fallback assignment equivalent to `answer_text = "佛说不可曰"` with `answer_text = "我还没听清，可以再说一遍咖啡问题吗？"`.
- In `src/providers/llm.py`, replace the old system prompt and few-shot examples with the tiny coffee persona:

```python
TINY_COFFEE_SYSTEM_PROMPT = (
    "你是小机仔，一只活泼懂咖啡的小机器人店员。"
    "默认用中文回答，回答控制在1到3句话，具体、友好、适合咖啡新手。"
    "可以回答咖啡豆、手冲、意式、奶咖、研磨度、萃取和风味问题。"
)
```

- In `src/settings.py`, remove or replace every default that points to `buddhism`. If a data directory property is still needed, use a tiny-specific neutral path such as `data/tiny` or `data/coffee`. Phase 1 has no coffee RAG, so no runtime default may load an old knowledge directory.

Run verification:

```bash
rg -n '佛说不可曰|佛学问答助手|data/buddhism|asr_hotwords[.]buddhism|buddhism' \
  src/services/realtime_session.py \
  src/workers/pipeline.py \
  src/providers/llm.py \
  src/settings.py || true
```

Expected: no output. This step closes the known leak paths that broad path-based tests can miss.

- [ ] **Step 3: Remove old deployment, handoff, and root-level docs that would mix product lines**

Run path-only discovery over root docs and shallow documentation trees:

```bash
find . -maxdepth 3 -type f \
  \( -name '*.md' -o -name '*.txt' -o -iname '*handoff*' -o -iname '*deploy*' -o -iname '*release*' \) \
  -print
```

For every root-level `.md` or `.txt`, README, docs file, deployment note, handoff note, release note, or old server-state note that describes old v6 deployment, old production operations, old handoff packages, old release runbooks, old root manuals such as `快速启动手册.md` or `使用手册.md`, or old server state, do one of these before `git init`:

- delete it if it is not needed for the tiny repo;
- move it under `docs/migration/v6-bootstrap/` if it is needed only as migration history;
- rewrite it as active tiny documentation with no old production IP, no old server token, no religion-domain content, and no old release package instructions.

Do not open `.env`, key, token, certificate, or credential files while classifying paths.

- [ ] **Step 4: Decide `docs/superpowers` migration history**

Use this policy:

- Keep only the tiny design spec and this revised bootstrap plan as migration context.
- Move retained context to `docs/migration/v6-bootstrap/`.
- Delete unrelated old v6 specs, plans, and summaries from the tiny repo.
- Isolation tests explicitly exclude `docs/migration/`.

Run:

```bash
mkdir -p docs/migration/v6-bootstrap
cp docs/superpowers/specs/2026-06-02-tiny-chicken-coffee-robot-design.md docs/migration/v6-bootstrap/
cp docs/superpowers/plans/2026-06-03-tiny-machine-chick-project-bootstrap.md docs/migration/v6-bootstrap/
rm -rf docs/superpowers
```

Expected: retained migration context exists only under `docs/migration/v6-bootstrap/`; unrelated old v6 superpowers history is absent from active docs.

- [ ] **Step 5: Remove active references to the old production target from the whole active tree**

Run path-only discovery from the repository root:

```bash
rg -l --glob '!.env*' --glob '!**/build*/**' --glob '!**/.git/**' --glob '!docs/migration/**' \
  '106\.54\.240\.51|greenunion-sh|greenunion_sh' \
  .
```

Expected after pruning: no active runtime/source/config/test/README/root-doc/env-example files are listed.

If an active path is listed, apply this fix policy:

- `scripts/*`: remove concrete old IP/server defaults; require an explicit `--server-base-url` argument or tiny env value such as `TINY_SERVER_BASE_URL`.
- `tests/*`: replace old IP fixtures with tiny-local values such as `http://tiny-server.test` or assert that no concrete production URL is embedded.
- root-level `.md` or `.txt`: delete, migrate to `docs/migration/`, or rewrite as tiny-specific docs.
- `README.md` and active docs: write "old v6 production line" or "non-shared production line" instead of old server tokens.
- env examples: use empty values or fake local examples, never concrete production IPs.
- device config: default server URL must be tiny-specific, empty, or local bring-up value; it must not point to the old v6 production target.

- [ ] **Step 6: Verify pruned paths and known content leaks are gone before `git init`**

Run:

```bash
test ! -e data/buddhism
test ! -e config/asr_hotwords.buddhism.json
test ! -e src/rag
test ! -e handoff
test ! -e 部署计划大纲.md
test ! -e 20260409_流式传输
find docs/deploy -maxdepth 1 -type f \( -name 'greenunion-sh-*' -o -name 'v6-n16r8-release-handoff-*' \) -print
rg -n '佛说不可曰|佛学问答助手|data/buddhism|asr_hotwords[.]buddhism|buddhism' \
  src/services/realtime_session.py \
  src/workers/pipeline.py \
  src/providers/llm.py \
  src/settings.py || true
```

Expected: every `test ! -e` command exits `0`; the `find` prints no files; the final `rg` prints no output.

### Task 3: Initialize New Repository, Ignore Rules, And Secret Gates

**Files:**
- Create or replace: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/.gitignore`
- Create: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/.github/workflows/secret-scan.yml`
- Create: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/scripts/security/secret_scan.sh`
- Create: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/scripts/git-hooks/pre-push`
- Create: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/docs/tiny/repository-bootstrap.md`

- [ ] **Step 1: Initialize new git history only after pruning**

Run:

```bash
cd /mnt/data100/GMT/20260601_tiny_chicken_coffee_robot
git init
git branch -M main
git remote add origin https://github.com/675401943/20260601_tiny_chicken_coffee_robot.git
git status --short --branch
```

Expected:

```text
## No commits yet on main
?? ...
```

- [ ] **Step 2: Write `.gitignore` before any commit**

Create `.gitignore`:

```gitignore
# Local secrets and credentials
.env
.env.*
!.env.example
*.pem
*.key
*.crt
*.csr
*.p12
*.pfx
id_rsa*
id_ed25519*
*_token
*_token.*
*_secret
*_secret.*
*_credentials.*
wifi_credentials.*
wifi-password*

# Local deployment/runtime state
data/runtime/
logs/
runtime/
local_deploy/
docker-data/
*.sqlite
*.sqlite3
*.db

# Python/cache outputs
__pycache__/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/
.venv/
venv/

# ESP-IDF and generated binaries
build/
build_*/
managed_components/
sdkconfig
sdkconfig.old
*.bin
*.elf
*.map
*.uf2
*.hex
srmodels.bin
storage.bin

# Generated delivery packages and assets
tmp/
dist/
release/
ota_bundles/
*.tar
*.tar.gz
*.zip
*.rar
assets/generated/
*.mjpeg
*.idx
```

- [ ] **Step 3: Add tracked secret scan script**

Create `scripts/security/secret_scan.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

if command -v gitleaks >/dev/null 2>&1; then
  gitleaks detect --source . --redact --no-banner
elif command -v trufflehog >/dev/null 2>&1; then
  trufflehog filesystem --only-verified --no-update .
else
  echo "secret scanner missing: install gitleaks or trufflehog before push" >&2
  exit 127
fi

dashscope='DASH''SCOPE_API_KEY'
dash_scope='DASH''_SCOPE_API_KEY'
qwen='QW''EN_API_KEY'
wifi_password='DEMO_WIFI_PASS''WORD'
wifi_ssid='DEMO_WIFI_SS''ID'
old_host='green''union-sh'
old_host_us='green''union_sh'
b_word='bud''dhism'
p_word='pr''ayer'
s_word='ser''mon'
src_rag='src/r''ag'
cn_buddha=$(printf '\344\275\233')
cn_buddha_said=$(printf '\344\275\233\350\257\264')
cn_buddhist_study=$(printf '\344\275\233\345\255\246')
cn_bdh=$(printf '\344\275\233\346\225\231')
cn_pureland=$(printf '\345\207\200\345\234\237')
cn_bodhisattva=$(printf '\350\217\251\350\220\250')
cn_amitabha=$(printf '\351\230\277\345\274\245\351\231\200')
cn_nianfo=$(printf '\345\277\265\344\275\233')
cn_donglin=$(printf '\344\270\234\346\236\227')
cn_rebirth=$(printf '\345\276\200\347\224\237')
cn_sukhavati=$(printf '\346\236\201\344\271\220')
cn_guanyin=$(printf '\350\247\202\351\237\263')
cn_scripture=$(printf '\347\273\217\346\226\207')
cn_pray=$(printf '\347\245\267\345\221\212')
cn_bible=$(printf '\345\234\243\347\273\217')
blocked_pattern="${dashscope}|${dash_scope}|${qwen}|${wifi_password}|${wifi_ssid}|PUBLIC_BASE_URL=http://106[.]54[.]240[.]51|106[.]54[.]240[.]51|${old_host}|${old_host_us}|asr_hotwords[.]${b_word}|data/${b_word}|${src_rag}|${cn_buddha}|${cn_buddha_said}|${cn_buddhist_study}|${cn_bdh}|${cn_pureland}|${cn_bodhisattva}|${cn_amitabha}|${cn_nianfo}|${cn_donglin}|${cn_rebirth}|${cn_sukhavati}|${cn_guanyin}|${cn_scripture}|${cn_pray}|${cn_bible}|${b_word}|${p_word}|${s_word}"
blocked_hits="$(git grep -Il -E "$blocked_pattern" -- ':!docs/migration/**' || true)"
if [ -n "$blocked_hits" ]; then
  echo "blocked v6 production, credential-name, or religion-domain residue in tracked active files:" >&2
  printf '%s\n' "$blocked_hits" >&2
  exit 1
fi

generic_hits="$(git grep -Il -E 'SSID|PASSWORD|API[_-]?KEY|TOKEN|SECRET|CREDENTIAL|PRIVATE[_-]?KEY|CERT' -- ':!docs/migration/**' ':!.github/workflows/secret-scan.yml' ':!scripts/security/secret_scan.sh' ':!scripts/git-hooks/pre-push' ':!.gitignore' || true)"
if [ -n "$generic_hits" ]; then
  echo "sensitive field names are present; path-only audit follows. Values are not printed. This audit output does not block by itself; scanner exit code and blocked_pattern hits are the blocking gates." >&2
  printf '%s\n' "$generic_hits" >&2
fi
```

Run:

```bash
chmod +x scripts/security/secret_scan.sh
```

Expected: script is executable and prints only file paths for targeted name checks, never matching values.

Use obviously test-only fake values that avoid high-entropy or real-token shapes. If gitleaks flags a fixed fake value in tests, add a narrow `.gitleaksignore` or gitleaks allowlist entry scoped to that exact test file and exact fake value. Do not weaken scanner rules globally.

- [ ] **Step 4: Add tracked pre-push hook template**

Create `scripts/git-hooks/pre-push`:

```bash
#!/usr/bin/env bash
set -euo pipefail
scripts/security/secret_scan.sh
```

Run:

```bash
chmod +x scripts/git-hooks/pre-push
```

Expected: hook template is executable. To install locally after repo init, copy or symlink it to `.git/hooks/pre-push`; the CI workflow remains the mandatory shared gate.

- [ ] **Step 5: Add CI secret scan workflow**

Create `.github/workflows/secret-scan.yml`:

```yaml
name: secret-scan

on:
  push:
  pull_request:

jobs:
  secret-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Install gitleaks
        run: |
          curl -sSfL https://raw.githubusercontent.com/gitleaks/gitleaks/master/install.sh | sh -s -- -b "$HOME/bin"
          echo "$HOME/bin" >> "$GITHUB_PATH"
      - name: Run redacted secret scan
        run: scripts/security/secret_scan.sh
```

Expected: every push and pull request runs the same redacted scanner and targeted path-only name checks.

- [ ] **Step 6: Record repository bootstrap rules**

Create `docs/tiny/repository-bootstrap.md`:

```markdown
# Repository Bootstrap Record

Source baseline: `/mnt/data100/GMT/20260521_16flash_8psram`
New project: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot`
Remote: `https://github.com/675401943/20260601_tiny_chicken_coffee_robot.git`
Visibility requirement: private for phase 1.

Bootstrap rules:
- The new repository is initialized with a fresh git history after v6 residue pruning.
- The copied v6 `.git` directory is removed before `git init`.
- Religion-domain data, old hotword config, old RAG module, old handoff files, old deployment docs, and old production target references are removed from active files before first commit.
- Migration context, if retained, lives only under `docs/migration/`.
- Local secrets and credential-like files are removed by path pattern without reading values.
- `scripts/security/secret_scan.sh` must pass before first push and every later push.
- `.github/workflows/secret-scan.yml` must pass in CI.
- Cloud deployment, OTA publishing, artifact upload, and hardware operation require separate approval.
```

### Task 4: Add Tracked-File Isolation Tests

**Files:**
- Create: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/tests/test_tiny_project_safety.py`

- [ ] **Step 1: Add tests that scan only git-indexed active files**

Create `tests/test_tiny_project_safety.py`:

```python
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".md", ".py", ".c", ".h", ".cc", ".yml", ".yaml", ".json", ".csv", ".txt", ".sh", ".toml"}
OLD_PRODUCTION_TERMS = ["106.54.240.51", "green" + "union-sh", "green" + "union_sh"]


def cp(*values: int) -> str:
    return "".join(chr(value) for value in values)


def religion_domain_terms() -> list[str]:
    return [
        cp(0x4F5B),
        cp(0x4F5B, 0x8BF4),
        cp(0x4F5B, 0x5B66),
        cp(0x4F5B, 0x6559),
        cp(0x51C0, 0x571F),
        cp(0x83E9, 0x8428),
        cp(0x963F, 0x5F25, 0x9640),
        cp(0x5FF5, 0x4F5B),
        cp(0x4E1C, 0x6797),
        cp(0x5F80, 0x751F),
        cp(0x6781, 0x4E50),
        cp(0x89C2, 0x97F3),
        cp(0x7ECF, 0x6587),
        cp(0x7977, 0x544A),
        cp(0x5723, 0x7ECF),
        "bud" + "dhism",
        "pr" + "ayer",
        "ser" + "mon",
    ]


def git_index_files() -> list[Path]:
    result = subprocess.run(["git", "ls-files", "--cached"], cwd=ROOT, text=True, capture_output=True, check=True)
    paths = [ROOT / line for line in result.stdout.splitlines() if line]
    assert paths, "stage files with `git add -A` before running tiny isolation tests"
    return paths


def tracked_text_files() -> list[Path]:
    paths = []
    for path in git_index_files():
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith("docs/migration/"):
            continue
        if path.suffix in TEXT_SUFFIXES:
            paths.append(path)
    return paths


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def test_gitignore_blocks_local_secrets_and_build_outputs():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    required_patterns = [
        ".env",
        ".env.*",
        "*.pem",
        "*.key",
        "*.crt",
        "*_token",
        "*_secret",
        "wifi_credentials.*",
        "build/",
        "build_*/",
        "managed_components/",
        "*.bin",
        "*.elf",
        "*.map",
        "ota_bundles/",
        "assets/generated/",
        "*.mjpeg",
        "*.idx",
    ]
    for pattern in required_patterns:
        assert pattern in gitignore


def test_product_name_uses_canonical_spelling_in_active_files():
    joined = "\n".join(read(path) for path in tracked_text_files())
    assert "小机仔" in joined
    assert "\u5c0f\u9e21\u4ed4" not in joined


def test_active_files_do_not_embed_old_production_target():
    for path in tracked_text_files():
        text = read(path)
        rel = path.relative_to(ROOT).as_posix()
        for token in OLD_PRODUCTION_TERMS:
            assert token not in text, f"{token} remains in active tracked file {rel}"


def test_religion_domain_residue_is_not_tracked_or_active():
    tracked = [path.relative_to(ROOT).as_posix() for path in git_index_files()]
    Buddhism = "bud" + "dhism"
    assert not any(path == f"config/asr_hotwords.{Buddhism}.json" for path in tracked)
    assert not any(path.startswith(f"data/{Buddhism}/") for path in tracked)
    assert not any(path.startswith("src/r" + "ag/") for path in tracked)
    assert not any(path.startswith("handoff/") for path in tracked)
    assert "部署计划大纲.md" not in tracked
    assert not any(path.startswith("20260409_流式传输/") for path in tracked)

    for path in tracked_text_files():
        text = read(path)
        rel = path.relative_to(ROOT).as_posix()
        for term in religion_domain_terms():
            assert term not in text, f"{term} remains in active tracked file {rel}"


def test_known_religion_fallback_and_settings_are_replaced():
    checks = {
        "src/services/realtime_session.py": "我还没听清，可以再说一遍咖啡问题吗？",
        "src/workers/pipeline.py": "我还没听清，可以再说一遍咖啡问题吗？",
        "src/providers/llm.py": "你是小机仔",
        "src/settings.py": "tiny",
    }
    old_fallback = cp(0x4F5B, 0x8BF4, 0x4E0D, 0x53EF, 0x66F0)
    old_assistant = cp(0x4F5B, 0x5B66, 0x95EE, 0x7B54, 0x52A9, 0x624B)
    for rel, expected in checks.items():
        path = ROOT / rel
        assert path.exists(), f"{rel} must remain present unless the module is intentionally replaced with a tiny equivalent"
        text = read(path)
        assert expected in text
        assert old_fallback not in text
        assert old_assistant not in text
        assert "bud" + "dhism" not in text


def test_phase1_boundaries_are_documented_not_enabled():
    docs = "\n".join(read(path) for path in tracked_text_files() if path.relative_to(ROOT).as_posix().startswith("docs/tiny/"))
    for phrase in [
        "Coffee RAG is not enabled in phase 1",
        "App and mini-program are not built in phase 1",
        "BLE provisioning is future scope",
        "Custom 小机仔 wake word model is future scope",
        "Alarm implementation is future scope",
        "OTA publishing requires separate approval",
    ]:
        assert phrase in docs
```

The test constructs religion terms with codepoints and string fragments so the guard file itself does not trip the active tracked-file residue scan. The shared term list in this plan remains the source of truth.

- [ ] **Step 2: Stage candidate files and run the isolation test as a TDD red checkpoint**

Run:

```bash
cd /mnt/data100/GMT/20260601_tiny_chicken_coffee_robot
git add -A
env PYTHONPATH=. python3 -m pytest tests/test_tiny_project_safety.py -q
```

Expected: `FAIL` at this checkpoint if Task 5 has not yet rewritten README, tiny boundary docs, settings, LLM persona, and fallback answers. This is intentional. Task 5 turns this test green, and Task 11 is the all-green gate before first commit.

### Task 5: Rewrite Active Product Identity And Runtime Defaults

**Files:**
- Modify: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/README.md`
- Modify: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/src/settings.py`
- Modify: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/src/app.py`
- Create: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/docs/tiny/naming-and-product-boundaries.md`

- [ ] **Step 1: Replace README identity without old server tokens**

Update the first section of `README.md`:

```markdown
# 20260601 Tiny Chicken Coffee Robot

`小机仔` is a coffee-focused tiny robot assistant built from a clean v6 source copy with independent repository history, deployment state, runtime configuration, and product behavior.

Phase 1 status:
- Target hardware baseline: ESP32-S3-class board, 32MB Flash, 8MB PSRAM, display, v6 audio/Wi-Fi/WakeNet foundations.
- Product persona: Chinese coffee-savvy shop assistant, concise 1-3 sentence answers.
- Wake word for phase 1: `小明同学`.
- Future custom wake word spelling: `小机仔`.
- Cloud target: Guangzhou server after separate approval, not the old v6 production line.
- Coffee RAG is not enabled in phase 1.
- App and mini-program are not built in phase 1.
- BLE provisioning is future scope.
- Custom 小机仔 wake word model is future scope.
- Alarm implementation is future scope.
- OTA publishing requires separate approval.
```

- [ ] **Step 2: Add tiny product boundary document**

Create `docs/tiny/naming-and-product-boundaries.md`:

```markdown
# 小机仔 Naming And Product Boundaries

Canonical Chinese product name: `小机仔`.
Repository slug: `20260601_tiny_chicken_coffee_robot`.
Phase 1 wake word: `小明同学`.
Future custom wake word spelling: `小机仔`.

Phase 1 behavior:
- Chinese coffee assistant persona.
- Short, concrete answers of 1-3 sentences by default.
- Coffee RAG is not enabled in phase 1.
- App and mini-program are not built in phase 1.
- BLE provisioning is future scope.
- Custom 小机仔 wake word model is future scope.
- Alarm implementation is future scope.
- OTA publishing requires separate approval.

Copied v6 content that must not remain active:
- Religion-specific prompts.
- Religion-specific few-shot examples.
- Religion/RAG knowledge data.
- Old runtime defaults that route devices to old production cloud state.
- User-facing v6 release naming.

Deployment isolation:
- Guangzhou server only after separate approval.
- Separate SQLite file.
- Separate Redis container or strict tiny key prefix.
- Separate logs and runtime data directories.
- Separate tiny-specific environment variables.
```

- [ ] **Step 3: Replace runtime defaults with tiny-safe names**

In `src/settings.py`, map the existing settings style to tiny-specific fields:

```python
project_name: str = "tiny_chicken_coffee_robot"
tiny_ark_api_key: str = ""
tiny_doubao_model: str = "doubao-seed-2-0-mini-260428"
tiny_doubao_base_url: str = "https://ark.cn-beijing.volces.com"
tiny_doubao_endpoint: str = ""
tiny_persona: str = (
    "你是小机仔，一只活泼懂咖啡的小机器人店员。"
    "默认用中文回答，回答控制在1到3句话，具体、友好、适合咖啡新手。"
)
tiny_cloud_target: str = "guangzhou"
```

Do not add real keys or concrete production URLs. If existing cloud code still reads old LLM env names, keep compatibility only inside provider adapters and make tiny settings the documented runtime path.

- [ ] **Step 4: Update healthz shape without leaking values**

In `src/app.py`, keep status-only readiness fields. Healthz may report `ok`, `down`, `configured`, or provider readiness booleans. It must not return API keys, tokens, secrets, credentials, or full URLs containing query parameters.

- [ ] **Step 5: Re-run the isolation test and verify it is green after product cleanup**

Run:

```bash
git add -A
env PYTHONPATH=. python3 -m pytest tests/test_tiny_project_safety.py -q
```

Expected: `PASS`. If it still fails, fix the active tracked file named in the failure before continuing.

### Task 6: Add Healthz No-Secret Tests

**Files:**
- Read first: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/src/app.py`
- Read first: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/src/settings.py`
- Create: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/tests/test_tiny_healthz.py`
- Modify: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/src/app.py` if the copied health route exposes values

- [ ] **Step 1: Inspect the copied health route before writing the test**

Run:

```bash
rg -n 'FastAPI|healthz|health|settings|Redis|sqlite|asr|llm|tts' src/app.py src/settings.py tests/test_app_healthz.py 2>/dev/null || true
```

Expected: identify whether the copied project exposes a FastAPI `app`, a direct `healthz()` function, both, or a different route name. Write the test against the actual copied structure. Do not assume `app_module.healthz()` or `app_module.settings` exists unless the discovery command proves it.

- [ ] **Step 2: Add a structure-adaptive healthz no-secret test**

Create `tests/test_tiny_healthz.py`:

```python
from __future__ import annotations

import importlib
import json
from unittest import mock

try:
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover - dependency stubs may be used in local tests
    TestClient = None


SAFE_FAKE_VALUES = [
    "unit-test-redacted-ark-marker",
    "unit-test-redacted-token-marker",
    "unit-test-redacted-credential-marker",
    "https://ark.example.invalid/unit-test-redacted-query-marker",
]
SENSITIVE_FIELD_NAMES = ["api_key", "token", "secret", "credential"]


def response_body_text(response: object) -> str:
    if hasattr(response, "text"):
        return str(response.text)
    if hasattr(response, "model_dump"):
        return json.dumps(response.model_dump(), ensure_ascii=False, sort_keys=True)
    if hasattr(response, "dict"):
        return json.dumps(response.dict(), ensure_ascii=False, sort_keys=True)
    return json.dumps(response, ensure_ascii=False, sort_keys=True, default=str)


def call_healthz(app_module: object) -> str:
    if hasattr(app_module, "app") and TestClient is not None:
        response = TestClient(app_module.app).get("/healthz")
        assert response.status_code == 200
        return response_body_text(response)
    if hasattr(app_module, "healthz"):
        return response_body_text(app_module.healthz())
    raise AssertionError("src.app must expose either FastAPI app /healthz or a healthz function")


def test_healthz_reports_status_without_secret_values(monkeypatch):
    monkeypatch.setenv("TINY_ARK_API_KEY", SAFE_FAKE_VALUES[0])
    monkeypatch.setenv("TINY_PROVIDER_TOKEN", SAFE_FAKE_VALUES[1])
    monkeypatch.setenv("TINY_PROVIDER_CREDENTIAL", SAFE_FAKE_VALUES[2])
    monkeypatch.setenv("TINY_DOUBAO_ENDPOINT", SAFE_FAKE_VALUES[3])

    app_module = importlib.reload(importlib.import_module("src.app"))

    patches = []
    for name in ("sqlite_ok", "asr_health", "llm_health", "tts_health"):
        if hasattr(app_module, name):
            patches.append(mock.patch.object(app_module, name, return_value=True))
    if hasattr(app_module, "Redis"):
        patches.append(mock.patch("src.app.Redis.from_url"))

    started = [patch.start() for patch in patches]
    try:
        for started_patch in started:
            if hasattr(started_patch, "return_value") and hasattr(started_patch.return_value, "ping"):
                started_patch.return_value.ping.return_value = True
        body = call_healthz(app_module)
    finally:
        for patch in reversed(patches):
            patch.stop()

    assert "ok" in body or "configured" in body
    for fake_value in SAFE_FAKE_VALUES:
        assert fake_value not in body
    for field_name in SENSITIVE_FIELD_NAMES:
        assert field_name not in body.lower()
```

The fake values are deliberately low-entropy test markers, not realistic tokens. If a scanner still flags one fixed fake value, add a narrow `.gitleaksignore` or allowlist entry scoped to `tests/test_tiny_healthz.py` and that exact marker. Do not weaken global scanner rules.

- [ ] **Step 3: Run healthz tests**

Run:

```bash
env PYTHONPATH=. python3 -m pytest tests/test_tiny_healthz.py -q
```

Expected: healthz tests pass. If they fail because healthz exposes settings values, remove value exposure and return status-only fields. If they fail because the copied app has a different route shape, update `call_healthz()` using the discovery output from Step 1 while keeping the no-secret assertion unchanged.

### Task 7: Replace v6 16MB Release Gate With Tiny 32MB Gates

**Files:**
- Delete or rewrite: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/tests/test_v6_n16r8_release_gate.py`
- Modify or split: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/tests/test_esp_assets.py`
- Create: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/tests/test_tiny_release_gate.py`
- Create: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/tests/test_tiny_esp_assets.py`
- Create: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/docs/tiny/partition-32m8m-design.md`

- [ ] **Step 1: Remove the v6 N16R8 release gate from tiny tests**

Run:

```bash
rm -f tests/test_v6_n16r8_release_gate.py
```

Expected: the tiny project no longer runs the v6 16MB N16R8 release gate.

- [ ] **Step 2: Add 32MB partition design document**

Create `docs/tiny/partition-32m8m-design.md`:

```markdown
# 32MB Flash + 8MB PSRAM Partition Design

Hardware target:
- Flash: 32MB.
- PSRAM: 8MB.
- ESP32-S3-class MCU with display.

Required partitions:
- bootloader and partition table.
- nvs.
- otadata.
- phy_init.
- ota_0.
- ota_1.
- WakeNet/model partition.
- storage for prompt audio and display assets.
- reserved space for future config/assets.

Design rules:
- Keep two OTA app slots while OTA rollback scaffolding remains.
- Do not reuse the 16MB v6 partition table without measurement.
- Measure app binary, srmodels image, prompt audio, and converted MJPEG asset subset before finalizing offsets and sizes.
- App image must fit the selected OTA slot with at least 15 percent headroom.
- Storage must fit prompt audio plus selected display assets with at least 20 percent headroom.
- No tiny test may require the old v6 production IP or old v6 release package naming.
```

- [ ] **Step 3: Add tiny release gate tests**

Create `tests/test_tiny_release_gate.py`:

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_tiny_release_gate_does_not_embed_old_v6_production_target():
    forbidden = ["106.54.240.51", "greenunion-sh", "greenunion_sh"]
    for path in (ROOT / "tests").glob("test_tiny*.py"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text


def test_tiny_partition_design_requires_32mb_flash_and_two_ota_slots():
    doc = (ROOT / "docs" / "tiny" / "partition-32m8m-design.md").read_text(encoding="utf-8")
    assert "32MB" in doc
    assert "8MB" in doc
    assert "ota_0" in doc
    assert "ota_1" in doc
    assert "model partition" in doc
    assert "display assets" in doc
```

- [ ] **Step 4: Adapt ESP asset tests to tiny names and 32MB partition**

Rename or split `tests/test_esp_assets.py` into `tests/test_tiny_esp_assets.py` if that keeps old v6 assertions out of tiny. Before writing assertions, inspect the copied files:

```bash
rg -n 'DEMO_BUTTON_GPIO|GPIO_NUM_7|DEMO_TRIGGER_SOURCE|DEMO_WAKE_WORD_MODEL_NAME|wn9_xiaomingtongxue|DEMO_OTA_BOOT_SWITCH_ENABLED|DEMO_OTA_ROLLBACK_VALIDATION_ENABLED' esp_idf_demo/main tests/test_esp_assets.py
```

Use the discovered real symbols. For the current v6 baseline, the tiny test should contain:

```python
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
ESP_MAIN = ROOT / "esp_idf_demo" / "main"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def macro_value(text: str, name: str) -> str:
    match = re.search(rf"^\s*#define\s+{re.escape(name)}\s+(.+?)\s*$", text, re.MULTILINE)
    assert match, f"{name} not found"
    return match.group(1)


def test_tiny_keeps_gpio7_button_and_wakenet_combined_trigger():
    config = read(ESP_MAIN / "config.h")
    trigger = read(ESP_MAIN / "trigger_input.c")
    wake_header = read(ESP_MAIN / "wake_word_service.h")
    assert macro_value(config, "DEMO_BUTTON_GPIO") == "GPIO_NUM_7"
    assert "DEMO_TRIGGER_SOURCE_BUTTON_AND_WAKE_WORD" in config
    assert "wn9_xiaomingtongxue_tts2" in config or "wn9_xiaomingtongxue_tts2" in wake_header
    assert "wake_word_service_start" in trigger
    assert "GPIO7" in trigger


def test_tiny_keeps_ota_publish_switches_off_by_default():
    config = read(ESP_MAIN / "config.h")
    assert macro_value(config, "DEMO_OTA_BOOT_SWITCH_ENABLED") == "0"
    assert macro_value(config, "DEMO_OTA_ROLLBACK_VALIDATION_ENABLED") == "0"


def test_tiny_partition_table_has_32mb_profile_requirements():
    partitions = (ROOT / "esp_idf_demo" / "partitions.csv").read_text(encoding="utf-8")
    for label in ["ota_0", "ota_1", "model", "storage"]:
        assert label in partitions
```

If the copied baseline uses different symbol names, update the test from the discovery output before committing. Do not keep assertions that depend on old v6 16MB package names or old production IPs.

- [ ] **Step 5: Run tiny release and ESP tests**

Run:

```bash
env PYTHONPATH=. python3 -m pytest tests/test_tiny_release_gate.py tests/test_tiny_esp_assets.py -q
```

Expected: tests pass after tiny partition and asset assertions are aligned.

### Task 8: Define Display Asset Format And MJPEG Hardware Gate

**Files:**
- Create: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/docs/tiny/display-asset-format.md`
- Create: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/docs/tiny/mjpeg-hardware-validation.md`
- Create: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/scripts/tiny_assets/convert_mjpeg_assets.py`
- Create: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/scripts/tiny_assets/write_mjpeg_idx.py`
- Create: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/tests/test_tiny_display_assets.py`

- [ ] **Step 1: Define display safe region, manifest, and `.idx` format**

Create `docs/tiny/display-asset-format.md` with these rules:

```markdown
# Display Asset Format

Display baseline:
- Physical display: 320x240.
- Safe expression region: 240x240.
- Safe region rationale: expressions and short text must avoid rounded-corner, circular, or other physical mask occlusion.
- `DISPLAY_SAFE_X` and `DISPLAY_SAFE_Y` remain configurable until hardware confirms the visible mask and rotation.
- Supported rotations: 0, 90, 180, 270.

Conversion target:
- Frame size: 240x240.
- FPS: 15.
- JPEG quality: `-q:v 5`.
- Runtime files: `<animation>.mjpeg` and `<animation>.idx`.

FFmpeg command:

```bash
ffmpeg -y -i input.avi \
  -vf "fps=15,scale=240:240:force_original_aspect_ratio=decrease,pad=240:240:(ow-iw)/2:(oh-ih)/2:black" \
  -q:v 5 -an -f mjpeg output.mjpeg
```

`.idx` byte order:
- Little-endian for every integer field.

`.idx` header:
- bytes 0..7: ASCII magic `TCMJIDX1`.
- uint16 width.
- uint16 height.
- uint16 fps_num.
- uint16 fps_den.
- uint32 frame_count.
- uint32 flags.
- uint32 manifest_name_len.
- UTF-8 manifest animation name bytes.
- frame table follows immediately.

Flags:
- bit 0: loop by default.
- bit 1: wake animation.
- bit 2: speaking animation.
- bit 3: error animation.

Frame table entry:
- uint32 byte_offset in `.mjpeg`.
- uint32 byte_size.

Animation names:
- standby
- wakeup
- listening
- thinking
- speaking
- happy
- sad
- angry
- surprise
- shutdown

Manifest format:

```json
{
  "version": 1,
  "display": {
    "width": 320,
    "height": 240,
    "safe_size": 240,
    "safe_x": 40,
    "safe_y": 0,
    "rotation": 0
  },
  "animations": [
    {
      "name": "standby",
      "mjpeg": "standby.mjpeg",
      "idx": "standby.idx",
      "fps": 15,
      "width": 240,
      "height": 240,
      "loop": true
    }
  ]
}
```
```

- [ ] **Step 2: Add conversion CLI**

Create `scripts/tiny_assets/convert_mjpeg_assets.py`:

```python
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


FILTER = "fps=15,scale=240:240:force_original_aspect_ratio=decrease,pad=240:240:(ow-iw)/2:(oh-ih)/2:black"


def convert(input_path: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-vf",
        FILTER,
        "-q:v",
        "5",
        "-an",
        "-f",
        "mjpeg",
        str(output_path),
    ]
    subprocess.run(cmd, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert one AVI/MJPEG source to 240x240 15fps raw MJPEG.")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    convert(args.input, args.output)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Add `.idx` writer implementation**

Create `scripts/tiny_assets/write_mjpeg_idx.py`:

```python
from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path


MAGIC = b"TCMJIDX1"
FLAG_LOOP = 1 << 0
FLAG_WAKE = 1 << 1
FLAG_SPEAKING = 1 << 2
FLAG_ERROR = 1 << 3


def find_jpeg_frames(data: bytes) -> list[tuple[int, int]]:
    frames: list[tuple[int, int]] = []
    pos = 0
    while True:
        start = data.find(b"\xff\xd8", pos)
        if start < 0:
            break
        end = data.find(b"\xff\xd9", start + 2)
        if end < 0:
            raise ValueError("unterminated JPEG frame")
        end += 2
        frames.append((start, end - start))
        pos = end
    if not frames:
        raise ValueError("no JPEG frames found")
    return frames


def flags_for(animation_name: str, loop: bool) -> int:
    flags = FLAG_LOOP if loop else 0
    if animation_name == "wakeup":
        flags |= FLAG_WAKE
    if animation_name == "speaking":
        flags |= FLAG_SPEAKING
    if animation_name in {"sad", "angry"}:
        flags |= FLAG_ERROR
    return flags


def write_idx(mjpeg_path: Path, idx_path: Path, animation_name: str, loop: bool) -> None:
    data = mjpeg_path.read_bytes()
    frames = find_jpeg_frames(data)
    name_bytes = animation_name.encode("utf-8")
    header = MAGIC + struct.pack("<HHHHIII", 240, 240, 15, 1, len(frames), flags_for(animation_name, loop), len(name_bytes))
    table = b"".join(struct.pack("<II", offset, size) for offset, size in frames)
    idx_path.parent.mkdir(parents=True, exist_ok=True)
    idx_path.write_bytes(header + name_bytes + table)


def write_manifest(manifest_path: Path, animations: list[dict[str, object]]) -> None:
    manifest = {
        "version": 1,
        "display": {"width": 320, "height": 240, "safe_size": 240, "safe_x": 40, "safe_y": 0, "rotation": 0},
        "animations": animations,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Write a little-endian index for a raw MJPEG animation.")
    parser.add_argument("mjpeg", type=Path)
    parser.add_argument("idx", type=Path)
    parser.add_argument("--name", required=True)
    parser.add_argument("--no-loop", action="store_true")
    args = parser.parse_args()
    write_idx(args.mjpeg, args.idx, args.name, not args.no_loop)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Add display asset tests**

Create `tests/test_tiny_display_assets.py`:

```python
from __future__ import annotations

import json
import struct
from pathlib import Path

from scripts.tiny_assets.write_mjpeg_idx import FLAG_LOOP, FLAG_WAKE, MAGIC, find_jpeg_frames, flags_for, write_idx, write_manifest


def test_idx_writer_uses_little_endian_header_and_loop_flag(tmp_path: Path):
    mjpeg = tmp_path / "wakeup.mjpeg"
    idx = tmp_path / "wakeup.idx"
    mjpeg.write_bytes(b"\xff\xd8frame1\xff\xd9\xff\xd8frame2\xff\xd9")

    write_idx(mjpeg, idx, "wakeup", True)

    data = idx.read_bytes()
    assert data[:8] == MAGIC
    width, height, fps_num, fps_den, frame_count, flags, name_len = struct.unpack("<HHHHIII", data[8:32])
    assert (width, height, fps_num, fps_den, frame_count, name_len) == (240, 240, 15, 1, 2, len("wakeup"))
    assert flags & FLAG_LOOP
    assert flags & FLAG_WAKE
    assert data[32:32 + name_len] == b"wakeup"


def test_find_jpeg_frames_returns_offsets_and_sizes():
    data = b"pad\xff\xd8abc\xff\xd9gap\xff\xd8defg\xff\xd9"
    assert find_jpeg_frames(data) == [(3, 7), (13, 8)]


def test_manifest_schema_contains_display_safe_region_and_animation_registry(tmp_path: Path):
    manifest = tmp_path / "manifest.json"
    write_manifest(
        manifest,
        [
            {"name": "standby", "mjpeg": "standby.mjpeg", "idx": "standby.idx", "fps": 15, "width": 240, "height": 240, "loop": True}
        ],
    )

    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["display"] == {"width": 320, "height": 240, "safe_size": 240, "safe_x": 40, "safe_y": 0, "rotation": 0}
    assert data["animations"][0]["name"] == "standby"
    assert data["animations"][0]["loop"] is True


def test_animation_flags_are_named_and_stable():
    assert flags_for("standby", True) & FLAG_LOOP
    assert flags_for("wakeup", True) & FLAG_WAKE
```

- [ ] **Step 5: Add MJPEG hardware validation gate**

Create `docs/tiny/mjpeg-hardware-validation.md`:

```markdown
# MJPEG Hardware Validation Gate

This gate runs only after display hardware is available. It is not part of repo bootstrap.

Target:
- 240x240 MJPEG frames.
- 15fps target playback.
- JPEG quality baseline from conversion script: `-q:v 5`.

Required runtime metrics per animation:
- average JPEG decode time in milliseconds.
- max JPEG decode time in milliseconds.
- display flush time in milliseconds.
- frame drop count.
- achieved fps.
- free internal heap before, during, and after playback.
- free PSRAM before, during, and after playback.

Pass criteria for the first curated asset subset:
- achieved fps is at least 14.0 over a 30 second loop.
- frame drop rate is below 2 percent.
- max decode time plus display flush time stays below the frame interval for at least 95 percent of frames.
- no internal heap or PSRAM downward leak after the loop ends.

If the gate fails:
- reduce FPS from 15 to 12.
- reduce asset complexity or selected animation count.
- reduce JPEG quality cost by adjusting conversion parameters.
- keep audio-only fallback independent from display readiness.
```

- [ ] **Step 6: Run display asset tests**

Run:

```bash
env PYTHONPATH=. python3 -m pytest tests/test_tiny_display_assets.py -q
```

Expected: tests pass and prove the current plan's conversion/index/manifest code is self-contained.

### Task 9: Add Doubao Provider Scaffold And Fallback Tests

**Files:**
- Create: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/src/providers/tiny_doubao.py`
- Create: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/tests/test_tiny_doubao_provider.py`
- Create: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/docs/tiny/doubao-provider-notes.md`

- [ ] **Step 1: Confirm official Doubao endpoint before network implementation**

Use current official Volcengine documentation before implementing network calls. Record the endpoint and payload decision in `docs/tiny/doubao-provider-notes.md` without copying real credentials:

```markdown
# Doubao Provider Notes

Model: `doubao-seed-2-0-mini-260428`
Output mode for phase 1: text answer.
Speech output: existing Volcengine TTS path.
Direct audio input: enabled only if official API confirms supported request payload.
Fallback: ASR -> Doubao text -> TTS.
Fallback trace field: `doubao_path=fallback_asr_text_tts`.
Direct trace field: `doubao_path=direct_audio_text_tts`.
```

- [ ] **Step 2: Add provider scaffold and tests**

Create a provider that builds text requests without including keys in request bodies, gates direct audio with a typed capability error until confirmed, and has tests for both paths:

```bash
env PYTHONPATH=. python3 -m pytest tests/test_tiny_doubao_provider.py -q
```

Expected: tests pass; no real credentials are committed.

### Task 10: Add Guangzhou Deployment Runbook Without Old Server Tokens

**Files:**
- Create: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/docs/deployment/guangzhou-runbook.md`
- Modify: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/docker-compose.yml`

- [ ] **Step 1: Add runbook using neutral old-line wording**

Create `docs/deployment/guangzhou-runbook.md`:

```markdown
# Guangzhou Deployment Runbook

This runbook is documentation only until the project owner explicitly approves deployment execution.

Target layout:

```text
/app/20260601_tiny_chicken_coffee_robot
/app/20260601_tiny_chicken_coffee_robot/data
/app/20260601_tiny_chicken_coffee_robot/logs
/app/20260601_tiny_chicken_coffee_robot/assets
```

Compose project:

```text
tiny_chicken_coffee_robot
```

Containers:

```text
tiny_chicken_coffee_robot-api-1
tiny_chicken_coffee_robot-worker-1
tiny_chicken_coffee_robot-redis-1
```

Runtime secrets supplied on server only:
- `TINY_ARK_API_KEY`
- Volcengine TTS credentials.
- ASR fallback credentials if fallback mode is enabled.

Deployment boundaries:
- Do not use the old v6 production line.
- Do not share v6 SQLite, Redis, logs, or environment files.
- Start with IP + port bring-up only after separate approval.
- Domain and HTTPS are deferred until device/cloud smoke tests pass.

Approval gates:
1. Owner approves SSH to Guangzhou.
2. Secret owner provides runtime credentials on server.
3. Repository secret scan passes.
4. Tiny cloud tests pass.
5. Device target endpoint is confirmed.
```

- [ ] **Step 2: Rename Compose project and containers**

Set `docker-compose.yml` project/service identity to `tiny_chicken_coffee_robot`. Do not copy old production container names, old Redis state, or old bind mounts.

### Task 11: Validate Phase 1 Boundaries Before First Commit

**Files:**
- Read: tracked candidate files only

- [ ] **Step 1: Run all bootstrap tests with a consistent import path**

Run:

```bash
cd /mnt/data100/GMT/20260601_tiny_chicken_coffee_robot
git add -A
env PYTHONPATH=. python3 -m pytest \
  tests/test_tiny_project_safety.py \
  tests/test_tiny_healthz.py \
  tests/test_tiny_display_assets.py \
  tests/test_tiny_doubao_provider.py \
  tests/test_tiny_esp_assets.py \
  tests/test_tiny_release_gate.py \
  -q
git diff --check
```

Expected: all tests pass and whitespace check reports no errors. Do not run `tests/test_v6_n16r8_release_gate.py` in the tiny repo; that file must be removed or replaced.

- [ ] **Step 2: Verify old production target and religion residue only allow migration docs**

Run path-only checks:

```bash
git grep -Il -E '106[.]54[.]240[.]51|greenunion-sh|greenunion_sh' -- ':!docs/migration/**' || true
git grep -Il -E 'data/buddhism|asr_hotwords[.]buddhism|src/rag|佛|佛说|佛学|佛教|净土|菩萨|阿弥陀|念佛|东林|往生|极乐|观音|经文|祷告|圣经|buddhism|prayer|sermon' -- ':!docs/migration/**' || true
```

Expected: both commands print no active files. If a code/script/test/env-example path is printed, fix it as follows:

- Code/config: remove old runtime default and replace with tiny setting, empty default, or fake local test value.
- Script: remove concrete old production default and require explicit tiny argument/env.
- Test: replace old fixture with `http://tiny-server.test` or a tiny-local fake value.
- README/runbook: rewrite old target wording to "old v6 production line" without old server token.
- Prompt/few-shot/RAG: remove old file or replace with tiny coffee persona content.

- [ ] **Step 3: Run secret scan before first commit**

Run:

```bash
scripts/security/secret_scan.sh
```

Expected: redacted scanner passes. The targeted grep may print path-only generic sensitive field audit entries, but it must not print values and must fail on known v6 credential names or old production target residue.

- [ ] **Step 4: First commit only after all gates pass**

Run:

```bash
git status --short --branch
git commit -m "chore: bootstrap tiny machine chick project"
```

Expected: the first tiny commit contains the pruned, tested, secret-scanned scaffold. It must not contain old `.git` history, old religion data, old RAG code, old handoff docs, old production target defaults, or secret-bearing files.

### Task 12: Verify Private Remote And Push

**Files:**
- Read: git status and remote metadata only

- [ ] **Step 1: Verify or create private repository**

Run:

```bash
gh repo view 675401943/20260601_tiny_chicken_coffee_robot --json visibility,nameWithOwner
```

Expected JSON includes:

```json
{"nameWithOwner":"675401943/20260601_tiny_chicken_coffee_robot","visibility":"PRIVATE"}
```

If the repo does not exist, create it private:

```bash
gh repo create 675401943/20260601_tiny_chicken_coffee_robot --private --source=. --remote=origin
```

Expected: GitHub confirms a private repository. Do not create a public repository in phase 1.

- [ ] **Step 2: Re-run tests and secret scan immediately before push**

Run:

```bash
env PYTHONPATH=. python3 -m pytest \
  tests/test_tiny_project_safety.py \
  tests/test_tiny_healthz.py \
  tests/test_tiny_display_assets.py \
  tests/test_tiny_doubao_provider.py \
  tests/test_tiny_esp_assets.py \
  tests/test_tiny_release_gate.py \
  -q
scripts/security/secret_scan.sh
git status --short --branch
```

Expected: tests and secret scan pass; worktree is clean.

- [ ] **Step 3: Push main**

Run:

```bash
git push -u origin main
```

Expected: push succeeds to the private repository, and GitHub secret-scan workflow is configured for future pushes and pull requests.

### Task 13: Final Bootstrap Report

**Files:**
- Create: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/docs/tiny/validation-record.md`
- Create: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/docs/tiny/future-scope.md`

- [ ] **Step 1: Record validation**

Create `docs/tiny/validation-record.md`:

```markdown
# Phase 1 Validation Record

Required before first push:
- Tiny safety tests pass.
- Healthz no-secret tests pass.
- Display asset tests pass.
- Doubao provider tests pass.
- Tiny ESP asset tests pass.
- Tiny 32MB release gate tests pass.
- `git diff --check` passes.
- `scripts/security/secret_scan.sh` passes.
- Old production target references are absent from active tracked files.
- Religion-domain data, old hotword config, and old RAG module are absent from active tracked files.
- No cloud deployment, OTA publishing, artifact upload, SSH, or hardware operation has been performed.
```

- [ ] **Step 2: Record deferred features**

Create `docs/tiny/future-scope.md`:

```markdown
# Future Scope

The following items are outside phase 1:

- Coffee RAG.
- App and mini-program.
- BLE provisioning.
- Custom `小机仔` WakeNet model.
- OTA publishing.
- Alarm implementation.
- Domain and HTTPS production hardening.
- BK7258 and 128MB Flash hardware migration.

Reserved interfaces for later:
- Device registration and binding.
- Device status.
- Firmware version and OTA status.
- Volume setting.
- Wake word setting.
- Display animation state command.
- Alarm list and configuration.
```

- [ ] **Step 3: Commit validation docs and report**

Run:

```bash
git add docs/tiny/validation-record.md docs/tiny/future-scope.md
git commit -m "docs: record tiny validation and future scope"
git status --short --branch
git log --oneline --max-count=8
```

Report:

```text
New project directory: /mnt/data100/GMT/20260601_tiny_chicken_coffee_robot
Remote: https://github.com/675401943/20260601_tiny_chicken_coffee_robot.git
Repository visibility: private
Latest commit: <commit sha>
Tests: PASS
Secret scan: PASS
Old production target active refs: none
Religion-domain active refs: none
Deployment: not performed
SSH: not performed
OTA publishing: not performed
Artifact upload: not performed
Hardware operation: not performed
```

---

## Revision Coverage Notes

- C1 covered: Task 2 enumerates v6 residue pruning immediately after clean copy and before `git init` or first commit.
- C2 covered: Task 4 tests scan git-indexed files only, exclude `docs/migration/`, and avoid old server tokens in README/runbook examples.
- C3 covered: Task 11 includes path-only old production target checks, migration-doc exclusion, and file-type-specific fix rules.
- C4 covered: Task 7 removes/replaces the v6 16MB N16R8 release gate with tiny/32MB gates.
- C5 covered: Task 4 adds religion-domain regression guards over tracked active files only.
- C6 covered: Task 3 adds CI and local secret scan gates; Task 11 and Task 12 require them before first commit/push.
- C7 covered: Task 6 adds healthz no-secret tests with fake secret values.
- C8 covered: Task 8 adds early hardware MJPEG throughput metrics and pass/fallback criteria.
- C9 covered: all pytest commands use `env PYTHONPATH=. python3 -m pytest`.
- C10 covered: Task 1 checks current branch/status and recent commits without pinning an obsolete HEAD.
- C11 covered: Task 7 requires reading copied ESP files before writing GPIO/WakeNet/OTA assertions and provides patterns based on the current baseline.
- C-A covered: Task 2 explicitly replaces `佛说不可曰`, old LLM system/few-shot prompts, and `settings.py` `buddhism` defaults before `git init`; Task 4 tests these known leak paths.
- I-A covered: the shared religion-domain term list is used by Task 4 tests, Task 11 `git grep`, and `scripts/security/secret_scan.sh` over all active tracked text files, excluding only `docs/migration/`.
- I-B covered: Task 4 Step 2 is now an intentional TDD red checkpoint, with Task 5 and Task 11 as the green gates.
- M-A covered: Task 8 includes complete conversion CLI, `.idx` writer, manifest writer, tests, byte order, flags, animation names, and registry schema inline in this plan.
- M-B covered: Task 2 scans and deletes/migrates root-level `.md` and `.txt` files such as copied manuals, not only `docs/`.
- M-C covered: Task 6 adapts to the copied health route structure, uses scanner-safe fake values, and Task 3 documents generic sensitive-name audit output as non-blocking path-only noise.

## Self-Review

- Spec coverage: clean copy, new private repo history, `.gitignore`, secret scan, v6/religion pruning, `小机仔` naming, 32MB Flash + 8MB PSRAM partition design, display safe region, MJPEG conversion and `.idx` format, hardware MJPEG gate, Doubao scaffold, direct-audio fallback, Guangzhou runbook, and deferred app/RAG/custom wake/OTA/BLE/alarm scope are covered.
- Boundary scan: this plan performs no new project creation, no rsync, no git init, no remote binding, no deployment, no SSH, no OTA publishing, no artifact upload, no hardware operation, and no secret reading during the plan-revision turn.
- Secret-safety scan: file cleanup and scanner commands print paths or redacted scanner output only; no step opens secret-bearing files.
