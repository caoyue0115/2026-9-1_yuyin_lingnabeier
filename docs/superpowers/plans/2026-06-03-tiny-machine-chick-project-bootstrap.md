# Tiny Machine Chick Project Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bootstrap an independent private `20260601_tiny_chicken_coffee_robot` project for the `小机仔` v6_tiny product line from the current v6 baseline, without carrying v6 git history or production state.

**Architecture:** Start with a clean source copy of the proven v6 device/cloud baseline, then isolate repository history, secrets policy, product naming, prompts, runtime defaults, deployment layout, display/asset scaffolding, and Doubao provider boundaries. Phase 1 intentionally creates a safe scaffold and test plan; it does not deploy, publish OTA, operate devices, or implement deferred app, coffee RAG, custom wake word, BLE, or alarm features.

**Tech Stack:** ESP-IDF v5.5.x, ESP32-S3 32MB Flash + 8MB PSRAM target, WakeNet with current `小明同学` model, GPIO7 trigger, Python/FastAPI cloud, Redis/SQLite, Docker Compose, Volcengine Ark Doubao-Seed-2.0-mini text path, Volcengine TTS, FFmpeg asset conversion, gitleaks or trufflehog secret scanning.

---

## Source Of Truth

- Design spec: `/mnt/data100/GMT/20260521_16flash_8psram/docs/superpowers/specs/2026-06-02-tiny-chicken-coffee-robot-design.md`
- Source v6 repo: `/mnt/data100/GMT/20260521_16flash_8psram`
- New project directory: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot`
- New GitHub repository: `https://github.com/675401943/20260601_tiny_chicken_coffee_robot.git`
- Material root: `/mnt/data100/GMT/assets/20260602_tiny_chicken_materials/20260602_小机仔`
- Material archive: `/mnt/data100/20260602_小机仔.rar`
- Product name and future custom wake-word spelling: `小机仔`
- Phase 1 wake word remains: `小明同学`
- Phase 1 repository visibility: private

## Non-Negotiable Guardrails

- Keep all project, build, temporary, and delivery files under `/mnt/data100`.
- Do not read, print, modify, commit, or upload `.env`, token files, Wi-Fi passwords, private keys, certificates, or secret-bearing files.
- Do not fork v6 and do not carry v6 git history into the new repository.
- Do not deploy cloud services, SSH to Guangzhou, publish OTA, upload release artifacts, or operate hardware during bootstrap.
- Do not touch `greenunion-sh` production containers, databases, Redis, logs, or runtime configuration.
- Before every implementation phase, run `git status --short --branch` and preserve user-owned changes.
- Before every push, run a redacted secret scan and stop if findings are reported.

## File And Directory Responsibilities

- `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/.gitignore`: blocks secrets, local runtime state, build outputs, generated binaries, caches, and delivery archives.
- `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/README.md`: tiny project identity, local development entry points, and non-production phase status.
- `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/docs/tiny/repository-bootstrap.md`: clean-copy, new-history, remote, and secret-scan record.
- `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/docs/tiny/naming-and-product-boundaries.md`: `小机仔` naming, v6/religion removal rules, and future feature boundaries.
- `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/docs/tiny/partition-32m8m-design.md`: 32MB Flash + 8MB PSRAM partition budget and measurement gate.
- `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/docs/tiny/display-asset-format.md`: 320x240 display, 240x240 safe region, MJPEG conversion, `.idx` binary format, loop flags, animation names, and manifest schema.
- `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/docs/deployment/guangzhou-runbook.md`: Guangzhou deployment layout and approval-only execution procedure.
- `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/scripts/tiny_assets/convert_mjpeg_assets.py`: future FFmpeg wrapper for 240x240, 15fps, `-q:v 5` conversion.
- `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/scripts/tiny_assets/write_mjpeg_idx.py`: future `.idx` writer using the format defined in docs.
- `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/src/providers/tiny_doubao.py`: future isolated Doubao provider for text output and direct-audio capability probing.
- `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/tests/test_tiny_project_safety.py`: static guards for secrets policy, naming, greenunion/v6 production leakage, and deferred-scope boundaries.
- `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/tests/test_tiny_display_assets.py`: static/fixture tests for MJPEG manifest and `.idx` encoding.
- `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/tests/test_tiny_doubao_provider.py`: mocked provider tests without printing or storing credentials.

---

### Task 1: Verify Source Baseline And Prepare Clean Copy

**Files:**
- Read: `/mnt/data100/GMT/20260521_16flash_8psram/docs/superpowers/specs/2026-06-02-tiny-chicken-coffee-robot-design.md`
- Create directory: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot`

- [ ] **Step 1: Confirm source repo status**

Run:

```bash
cd /mnt/data100/GMT/20260521_16flash_8psram
git status --short --branch
git rev-parse HEAD
git log -1 --oneline
```

Expected:

```text
## main...origin/main
569093d docs: finalize tiny machine chick review notes
```

If extra local changes exist, stop and report them before copying.

- [ ] **Step 2: Confirm new target directory is available**

Run:

```bash
test ! -e /mnt/data100/GMT/20260601_tiny_chicken_coffee_robot
```

Expected: command exits with status `0`.

If the path already exists, run:

```bash
find /mnt/data100/GMT/20260601_tiny_chicken_coffee_robot -mindepth 1 -maxdepth 1 -print
```

Expected: no output. If it prints files, stop and ask for owner confirmation.

- [ ] **Step 3: Create clean source copy on the 100GB disk**

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

Expected: source files are copied; rebuildable build outputs and delivery archives are absent.

- [ ] **Step 4: Remove old v6 git history from the copy**

Run:

```bash
rm -rf /mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/.git
test ! -e /mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/.git
```

Expected: command exits with status `0`. The original v6 repo remains untouched.

### Task 2: Initialize New Private Repository History

**Files:**
- Modify: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/.gitignore`
- Create: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/docs/tiny/repository-bootstrap.md`

- [ ] **Step 1: Initialize a new git repository**

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

- [ ] **Step 2: Write secret-safe `.gitignore` before first commit**

Create or replace `.gitignore` with:

```gitignore
# Local secrets and credentials
.env
.env.*
!.env.example
*.pem
*.key
*.crt
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
data/
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

- [ ] **Step 3: Remove secret-bearing files from the clean copy by path only**

Run:

```bash
cd /mnt/data100/GMT/20260601_tiny_chicken_coffee_robot
find . \
  \( -name '.env' -o -name '.env.*' -o -name '*.pem' -o -name '*.key' -o -name '*.p12' -o -name '*.pfx' -o -name '*_token' -o -name '*_secret' -o -name '*_credentials.*' -o -name 'wifi_credentials.*' \) \
  -print
```

Expected: only path names are printed. Do not open these files.

If paths are listed, remove only those paths:

```bash
find . \
  \( -name '.env' -o -name '.env.*' -o -name '*.pem' -o -name '*.key' -o -name '*.p12' -o -name '*.pfx' -o -name '*_token' -o -name '*_secret' -o -name '*_credentials.*' -o -name 'wifi_credentials.*' \) \
  -delete
```

- [ ] **Step 4: Record repository isolation**

Create `docs/tiny/repository-bootstrap.md`:

```markdown
# Repository Bootstrap Record

Source baseline: `/mnt/data100/GMT/20260521_16flash_8psram`
New project: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot`
Remote: `https://github.com/675401943/20260601_tiny_chicken_coffee_robot.git`
Visibility requirement: private for phase 1.

Bootstrap rules:
- The new repository is initialized with a fresh git history.
- The v6 `.git` directory is removed before the first tiny commit.
- Local secrets and credential-like files are removed by path pattern without reading values.
- Secret scanning is required before every push.
- Cloud deployment, OTA publishing, artifact upload, and hardware operation require separate approval.
```

- [ ] **Step 5: Verify repository visibility before first push**

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

Expected: GitHub confirms a private repository.

### Task 3: Add Safety Tests Before Product Cleanup

**Files:**
- Create: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/tests/test_tiny_project_safety.py`

- [ ] **Step 1: Add static guard tests**

Create `tests/test_tiny_project_safety.py`:

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_gitignore_blocks_local_secrets_and_build_outputs():
    gitignore = read_text(".gitignore")
    required_patterns = [
        ".env",
        ".env.*",
        "*.pem",
        "*.key",
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


def test_product_name_uses_tiny_machine_chick_spelling():
    allowed = "小机仔"
    forbidden = "\u5c0f\u9e21\u4ed4"
    text_paths = [
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and ".git" not in path.parts
        and "build" not in path.parts
        and path.suffix in {".md", ".py", ".c", ".h", ".cc", ".yml", ".yaml", ".json", ".csv", ".txt"}
    ]
    joined = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in text_paths)
    assert allowed in joined
    assert forbidden not in joined


def test_phase1_does_not_target_greenunion_runtime():
    searchable = [
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and ".git" not in path.parts
        and "build" not in path.parts
        and path.suffix in {".md", ".py", ".c", ".h", ".cc", ".yml", ".yaml", ".json", ".txt"}
    ]
    disallowed = ["greenunion-sh", "greenunion_sh"]
    for path in searchable:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for value in disallowed:
            assert value not in text, f"{value} remains in {path.relative_to(ROOT)}"


def test_deferred_features_are_documented_not_enabled():
    docs = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in (ROOT / "docs").rglob("*.md")
    )
    for phrase in [
        "Coffee RAG is not enabled in phase 1",
        "App and mini-program are not implemented in phase 1",
        "BLE provisioning is future scope",
        "Custom 小机仔 wake word model is future scope",
        "Alarm implementation is future scope",
        "OTA publishing requires separate approval",
    ]:
        assert phrase in docs
```

- [ ] **Step 2: Run the new tests and confirm expected initial failures**

Run:

```bash
cd /mnt/data100/GMT/20260601_tiny_chicken_coffee_robot
env PYTHONPATH=/data/GMT-assets/testdeps/v5-realtime-opus-testdeps:. python3 -m pytest tests/test_tiny_project_safety.py -q
```

Expected: failures identify copied v6 names or missing tiny boundary docs. Keep these failures until cleanup tasks intentionally make them pass.

### Task 4: Remove v6 Religion Domain And Production Defaults

**Files:**
- Modify: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/README.md`
- Modify: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/src/settings.py`
- Modify: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/src/providers/*`
- Modify or delete: copied prompt/few-shot/RAG files found by path search
- Create: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/docs/tiny/naming-and-product-boundaries.md`

- [ ] **Step 1: Locate copied v6 domain files without scanning secrets**

Run:

```bash
cd /mnt/data100/GMT/20260601_tiny_chicken_coffee_robot
rg -l --glob '!.env*' --glob '!**/build*/**' --glob '!**/.git/**' \
  'religion|prayer|RAG|few_shot|few-shot|DashScope|Qwen|greenunion|v5_realtime|v6-n16r8|prayer|bible|sermon|佛|祷告|圣经|经文'
```

Expected: path list only. Review listed non-secret source and docs files.

- [ ] **Step 2: Replace product-facing README identity**

Update `README.md` so the first section contains:

```markdown
# 20260601 Tiny Chicken Coffee Robot

`小机仔` is a coffee-focused tiny robot assistant built from a clean v6 source copy with independent repository history, deployment state, runtime configuration, and product behavior.

Phase 1 status:
- Target hardware baseline: ESP32-S3 style board, 32MB Flash, 8MB PSRAM, display, v6 audio/Wi-Fi/WakeNet foundations.
- Product persona: Chinese coffee-savvy shop assistant, concise 1-3 sentence answers.
- Wake word for phase 1: `小明同学`.
- Future custom wake word spelling: `小机仔`.
- Cloud target: Guangzhou server after approval, not greenunion-sh.
- Coffee RAG is not enabled in phase 1.
- App and mini-program are not implemented in phase 1.
- BLE provisioning is future scope.
- Custom 小机仔 wake word model is future scope.
- Alarm implementation is future scope.
- OTA publishing requires separate approval.
```

- [ ] **Step 3: Add product boundary document**

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
- No coffee RAG.
- No app or mini-program implementation.
- No BLE provisioning.
- No custom 小机仔 WakeNet model.
- No alarm implementation.
- No OTA publishing.

Copied v6 content that must be removed or disabled:
- Religion-specific prompts.
- Religion-specific few-shot examples.
- Religion or prayer RAG data.
- Runtime defaults that route devices to v6 production cloud state.
- User-facing v6 release naming.

Deployment isolation:
- Guangzhou server only after separate approval.
- Separate SQLite file.
- Separate Redis container or strict tiny key prefix.
- Separate logs and runtime data directories.
- Separate tiny-specific environment variables.
```

- [ ] **Step 4: Replace runtime defaults with tiny-safe names**

In `src/settings.py`, introduce tiny-specific setting names and safe defaults:

```python
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

Do not add real keys or local server URLs. If the current settings model has a different style, map these fields into the existing settings class without changing unrelated ASR/OTA behavior.

- [ ] **Step 5: Run safety tests**

Run:

```bash
env PYTHONPATH=/data/GMT-assets/testdeps/v5-realtime-opus-testdeps:. python3 -m pytest tests/test_tiny_project_safety.py -q
```

Expected: tests pass after copied v6 domain defaults are removed or documented as disabled.

- [ ] **Step 6: Commit cleanup stage**

Run:

```bash
git status --short --branch
git add README.md src/settings.py docs/tiny/naming-and-product-boundaries.md tests/test_tiny_project_safety.py
git commit -m "chore: isolate tiny product identity"
```

Expected: one commit containing naming and product-boundary cleanup only.

### Task 5: Design 32MB Flash + 8MB PSRAM Partition Budget

**Files:**
- Create: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/docs/tiny/partition-32m8m-design.md`
- Modify later after measurement: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/esp_idf_demo/partitions.csv`
- Test later: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/tests/test_esp_assets.py`

- [ ] **Step 1: Record partition design constraints**

Create `docs/tiny/partition-32m8m-design.md`:

```markdown
# 32MB Flash + 8MB PSRAM Partition Design

Hardware target:
- Flash: 32MB.
- PSRAM: 8MB.
- MCU line: ESP32-S3 style board with display.

Required partitions:
- bootloader and partition table.
- nvs.
- otadata.
- phy_init.
- ota_0.
- ota_1.
- WakeNet/model partition.
- storage for prompt audio and display asset subset.
- reserved space for future configuration or additional assets.

Design rule:
- Keep two OTA app slots while OTA rollback scaffolding remains.
- Do not reuse the 16MB v6 partition table without measurement.
- Measure app binary, srmodels image, prompt audio, and converted MJPEG asset subset before finalizing offsets and sizes.
- App image must fit the selected OTA slot with at least 15 percent headroom.
- Storage must fit prompt audio plus selected display assets with at least 20 percent headroom.

Initial measurement commands:

```bash
idf.py -C esp_idf_demo -B /mnt/data100/GMT/builds/tiny_32m8m_measure build
stat -c '%n %s' /mnt/data100/GMT/builds/tiny_32m8m_measure/esp_idf_demo.bin
find assets/generated -type f \( -name '*.mjpeg' -o -name '*.idx' \) -printf '%s %p\n' | awk '{sum += $1} END {print sum}'
```

Candidate partition policy:
- `ota_0` and `ota_1` are larger than the current 3MB v6 slots if measured app size requires it.
- `model` uses the ESP-SR official partition type, subtype, and generation flow.
- `storage` remains present for SPIFFS prompts and display asset subset.
- Remaining flash is reserved rather than silently consumed.
```

- [ ] **Step 2: Add static partition tests when `partitions.csv` is changed**

In `tests/test_esp_assets.py`, add checks that assert:

```python
def test_tiny_partition_table_targets_32mb_flash_budget():
    text = (ROOT / "esp_idf_demo" / "partitions.csv").read_text(encoding="utf-8")
    assert "ota_0" in text
    assert "ota_1" in text
    assert "model" in text
    assert "storage" in text
```

Extend this test with exact offsets and sizes after measurement chooses the final layout.

- [ ] **Step 3: Commit the design document**

Run:

```bash
git add docs/tiny/partition-32m8m-design.md
git commit -m "docs: define tiny 32m8m partition budget"
```

Expected: partition design is documented before firmware partition edits.

### Task 6: Add Display And MJPEG Asset Conversion Scaffold

**Files:**
- Create: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/docs/tiny/display-asset-format.md`
- Create: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/scripts/tiny_assets/convert_mjpeg_assets.py`
- Create: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/scripts/tiny_assets/write_mjpeg_idx.py`
- Create: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/tests/test_tiny_display_assets.py`

- [ ] **Step 1: Define display safe region and asset format**

Create `docs/tiny/display-asset-format.md`:

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

- [ ] **Step 2: Add conversion script scaffold**

Create `scripts/tiny_assets/convert_mjpeg_assets.py`:

```python
import argparse
import subprocess
from pathlib import Path


def convert(input_path: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-vf",
        "fps=15,scale=240:240:force_original_aspect_ratio=decrease,pad=240:240:(ow-iw)/2:(oh-ih)/2:black",
        "-q:v",
        "5",
        "-an",
        "-f",
        "mjpeg",
        str(output_path),
    ]
    subprocess.run(cmd, check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    convert(args.input, args.output)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Add index writer scaffold**

Create `scripts/tiny_assets/write_mjpeg_idx.py`:

```python
import argparse
import struct
from pathlib import Path


MAGIC = b"TCMJIDX1"


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


def write_idx(mjpeg_path: Path, idx_path: Path, animation_name: str, loop: bool) -> None:
    data = mjpeg_path.read_bytes()
    frames = find_jpeg_frames(data)
    name_bytes = animation_name.encode("utf-8")
    flags = 1 if loop else 0
    header = MAGIC + struct.pack("<HHHHIII", 240, 240, 15, 1, len(frames), flags, len(name_bytes))
    table = b"".join(struct.pack("<II", offset, size) for offset, size in frames)
    idx_path.write_bytes(header + name_bytes + table)


def main() -> None:
    parser = argparse.ArgumentParser()
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
import struct
from pathlib import Path

from scripts.tiny_assets.write_mjpeg_idx import MAGIC, find_jpeg_frames, write_idx


def test_idx_writer_uses_little_endian_header(tmp_path: Path):
    mjpeg = tmp_path / "standby.mjpeg"
    idx = tmp_path / "standby.idx"
    mjpeg.write_bytes(b"\xff\xd8frame1\xff\xd9\xff\xd8frame2\xff\xd9")

    write_idx(mjpeg, idx, "standby", True)

    data = idx.read_bytes()
    assert data[:8] == MAGIC
    width, height, fps_num, fps_den, frame_count, flags, name_len = struct.unpack("<HHHHIII", data[8:32])
    assert (width, height, fps_num, fps_den, frame_count, flags, name_len) == (240, 240, 15, 1, 2, 1, 7)


def test_find_jpeg_frames_returns_offsets_and_sizes():
    data = b"pad\xff\xd8abc\xff\xd9gap\xff\xd8defg\xff\xd9"
    assert find_jpeg_frames(data) == [(3, 7), (13, 8)]
```

- [ ] **Step 5: Run tests and commit**

Run:

```bash
python3 -m pytest tests/test_tiny_display_assets.py -q
git add docs/tiny/display-asset-format.md scripts/tiny_assets tests/test_tiny_display_assets.py
git commit -m "feat: add tiny display asset scaffold"
```

Expected: display asset scaffold tests pass.

### Task 7: Add Doubao Provider Scaffold With Explicit Fallback

**Files:**
- Create: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/src/providers/tiny_doubao.py`
- Modify: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/src/settings.py`
- Create: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/tests/test_tiny_doubao_provider.py`

- [ ] **Step 1: Check official Volcengine API documentation before coding request shape**

Run a current documentation lookup restricted to official Volcengine documentation. Record the endpoint choice in `docs/tiny/doubao-provider-notes.md` without copying credentials or examples containing real keys.

Expected notes:

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

- [ ] **Step 2: Add provider interface**

Create `src/providers/tiny_doubao.py`:

```python
from dataclasses import dataclass
from typing import Any


class DoubaoCapabilityError(RuntimeError):
    pass


@dataclass(frozen=True)
class DoubaoTextResult:
    text: str
    path: str


class TinyDoubaoProvider:
    def __init__(self, api_key: str, model: str, base_url: str, endpoint: str) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._endpoint = endpoint

    def build_text_request(self, question_text: str, persona: str) -> dict[str, Any]:
        return {
            "model": self._model,
            "messages": [
                {"role": "system", "content": persona},
                {"role": "user", "content": question_text},
            ],
        }

    def build_audio_request(self, opus_bytes: bytes, persona: str) -> dict[str, Any]:
        raise DoubaoCapabilityError("direct audio input is not enabled until official API support is confirmed")
```

Do not implement network calls until the official endpoint and payload are confirmed.

- [ ] **Step 3: Add provider tests**

Create `tests/test_tiny_doubao_provider.py`:

```python
import pytest

from src.providers.tiny_doubao import DoubaoCapabilityError, TinyDoubaoProvider


def test_text_request_uses_tiny_model_and_persona_without_key():
    provider = TinyDoubaoProvider(
        api_key="redacted-test-key",
        model="doubao-seed-2-0-mini-260428",
        base_url="https://ark.cn-beijing.volces.com",
        endpoint="/api/test",
    )

    request = provider.build_text_request("手冲咖啡怎么调粗细？", "你是小机仔")

    assert request["model"] == "doubao-seed-2-0-mini-260428"
    assert request["messages"][0] == {"role": "system", "content": "你是小机仔"}
    assert "redacted-test-key" not in str(request)


def test_audio_request_is_explicitly_gated_until_supported():
    provider = TinyDoubaoProvider(
        api_key="redacted-test-key",
        model="doubao-seed-2-0-mini-260428",
        base_url="https://ark.cn-beijing.volces.com",
        endpoint="/api/test",
    )

    with pytest.raises(DoubaoCapabilityError):
        provider.build_audio_request(b"opus", "你是小机仔")
```

- [ ] **Step 4: Run provider tests and commit**

Run:

```bash
python3 -m pytest tests/test_tiny_doubao_provider.py -q
git add src/providers/tiny_doubao.py src/settings.py tests/test_tiny_doubao_provider.py docs/tiny/doubao-provider-notes.md
git commit -m "feat: scaffold tiny doubao provider"
```

Expected: provider tests pass; no real credentials are added.

### Task 8: Add Guangzhou Deployment Runbook Without Executing Deployment

**Files:**
- Create: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/docs/deployment/guangzhou-runbook.md`
- Modify: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/docker-compose.yml`

- [ ] **Step 1: Add runbook**

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
- Do not use greenunion-sh.
- Do not share v6 SQLite, Redis, logs, or `.env`.
- Start with IP + port bring-up.
- Domain and HTTPS are deferred until device/cloud smoke tests pass.

Approval gates:
1. Owner approves SSH to Guangzhou.
2. Secret owner provides runtime credentials on server.
3. Repository secret scan passes.
4. Tiny cloud tests pass.
5. Device target endpoint is confirmed.
```

- [ ] **Step 2: Rename Compose project and containers**

In `docker-compose.yml`, set:

```yaml
name: tiny_chicken_coffee_robot
```

Use service names that produce isolated containers:

```yaml
services:
  api:
    container_name: tiny_chicken_coffee_robot-api-1
  worker:
    container_name: tiny_chicken_coffee_robot-worker-1
  redis:
    container_name: tiny_chicken_coffee_robot-redis-1
```

If the current compose file does not have all three services, change only existing equivalent services and document missing services in the runbook.

- [ ] **Step 3: Commit deployment documentation**

Run:

```bash
git add docs/deployment/guangzhou-runbook.md docker-compose.yml
git commit -m "docs: add guangzhou deployment runbook"
```

Expected: documentation exists; no SSH or deployment command has run.

### Task 9: Preserve Device Foundations While Isolating Tiny Defaults

**Files:**
- Modify: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/esp_idf_demo/main/config.h`
- Modify: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/esp_idf_demo/main/main.c`
- Modify: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/esp_idf_demo/sdkconfig.defaults*`
- Test: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/tests/test_esp_assets.py`

- [ ] **Step 1: Add static tests for retained foundations**

Update `tests/test_esp_assets.py` to assert:

```python
def test_tiny_keeps_gpio7_and_wakenet_foundations():
    trigger = (ROOT / "esp_idf_demo" / "main" / "trigger_input.c").read_text(encoding="utf-8")
    config = (ROOT / "esp_idf_demo" / "main" / "config.h").read_text(encoding="utf-8")
    assert "GPIO_NUM_7" in trigger or "DEMO_TRIGGER_GPIO" in config
    assert "小明同学" in config or "wn9_xiaomingtongxue_tts2" in "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in (ROOT / "esp_idf_demo" / "main").glob("*")
        if path.suffix in {".c", ".h", ".cc"}
    )


def test_tiny_defaults_do_not_publish_ota():
    config = (ROOT / "esp_idf_demo" / "main" / "config.h").read_text(encoding="utf-8")
    assert "#define DEMO_OTA_BOOT_SWITCH_ENABLED 0" in config
    assert "#define DEMO_OTA_ROLLBACK_VALIDATION_ENABLED 0" in config
```

- [ ] **Step 2: Update runtime logs to tiny identity**

In `esp_idf_demo/main/main.c`, ensure runtime config logs include:

```c
ESP_LOGI(TAG, "product_name=小机仔 target_profile=v6_tiny flash=32MB psram=8MB");
```

Keep existing Wi-Fi provisioning, GPIO7 trigger, WakeNet, audio path, OTA safety gates, and rollback scaffolding intact.

- [ ] **Step 3: Run ESP static tests**

Run:

```bash
env PYTHONPATH=/data/GMT-assets/testdeps/v5-realtime-opus-testdeps:. python3 -m pytest tests/test_esp_assets.py -q
```

Expected: tests pass after tiny defaults are aligned.

- [ ] **Step 4: Commit device defaults**

Run:

```bash
git add esp_idf_demo/main/config.h esp_idf_demo/main/main.c esp_idf_demo/sdkconfig.defaults* tests/test_esp_assets.py
git commit -m "chore: isolate tiny device defaults"
```

Expected: GPIO7, WakeNet, Hotspot, ASR, and OTA scaffolding remain present.

### Task 10: Validate Phase 1 Boundaries And Secret Scan

**Files:**
- Read: entire new repository, excluding ignored/generated paths

- [ ] **Step 1: Run Python and ESP static tests**

Run:

```bash
cd /mnt/data100/GMT/20260601_tiny_chicken_coffee_robot
env PYTHONPATH=/data/GMT-assets/testdeps/v5-realtime-opus-testdeps:. python3 -m pytest tests/test_tiny_project_safety.py tests/test_tiny_display_assets.py tests/test_tiny_doubao_provider.py -q
env PYTHONPATH=/data/GMT-assets/testdeps/v5-realtime-opus-testdeps:. python3 -m pytest tests/test_esp_assets.py tests/test_v6_n16r8_release_gate.py -q
git diff --check
```

Expected: all selected tests pass and whitespace check reports no errors.

- [ ] **Step 2: Run a redacted secret scan before push**

Prefer gitleaks:

```bash
gitleaks detect --source . --redact --no-banner
```

Expected:

```text
no leaks found
```

If gitleaks is unavailable, use trufflehog:

```bash
trufflehog filesystem --only-verified --no-update .
```

Expected: no verified leaks.

If neither scanner is installed, stop before push and request approval to install one on the 100GB disk.

- [ ] **Step 3: Confirm no forbidden runtime target remains**

Run:

```bash
rg -n --glob '!.env*' --glob '!**/.git/**' --glob '!**/build*/**' 'greenunion-sh|greenunion_sh|106\.54\.240\.51'
```

Expected: no output except historical migration notes that explicitly say the target is not used. If output includes runtime config or code defaults, fix those files before pushing.

- [ ] **Step 4: Commit validation notes**

Create `docs/tiny/validation-record.md`:

```markdown
# Phase 1 Validation Record

Required before first push:
- Tiny safety tests pass.
- Display asset tests pass.
- Doubao provider tests pass.
- ESP static tests pass.
- Release gate tests pass.
- `git diff --check` passes.
- Redacted secret scan passes.
- No cloud deployment, OTA publishing, artifact upload, or hardware operation has been performed.
```

Run:

```bash
git add docs/tiny/validation-record.md
git commit -m "docs: record tiny bootstrap validation gates"
```

Expected: validation gates are documented.

### Task 11: First Push To Private New Repository

**Files:**
- Read: git status and remote config only

- [ ] **Step 1: Verify final status before push**

Run:

```bash
git status --short --branch
git log --oneline --max-count=8
git remote -v
```

Expected:

```text
## main
origin  https://github.com/675401943/20260601_tiny_chicken_coffee_robot.git (fetch)
origin  https://github.com/675401943/20260601_tiny_chicken_coffee_robot.git (push)
```

- [ ] **Step 2: Re-run secret scan immediately before push**

Run:

```bash
gitleaks detect --source . --redact --no-banner
```

Expected: no leaks found. If gitleaks is unavailable, use the trufflehog command from Task 10.

- [ ] **Step 3: Push main**

Run:

```bash
git push -u origin main
```

Expected: push succeeds to the private repository.

- [ ] **Step 4: Report bootstrap state**

Report:

```text
New project directory: /mnt/data100/GMT/20260601_tiny_chicken_coffee_robot
Remote: https://github.com/675401943/20260601_tiny_chicken_coffee_robot.git
Latest commit: <commit sha>
Secret scan: PASS
Tests: PASS
Deployment: not performed
OTA publishing: not performed
Hardware operation: not performed
```

### Task 12: Future-Scope Register

**Files:**
- Create: `/mnt/data100/GMT/20260601_tiny_chicken_coffee_robot/docs/tiny/future-scope.md`

- [ ] **Step 1: Document deferred features**

Create `docs/tiny/future-scope.md`:

```markdown
# Future Scope

The following items are intentionally outside phase 1:

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

- [ ] **Step 2: Commit future-scope register**

Run:

```bash
git add docs/tiny/future-scope.md
git commit -m "docs: record tiny future scope"
```

Expected: deferred scope is explicit and not implemented.

---

## Self-Review

- Spec coverage: this plan covers clean copy, new history, private remote, `.gitignore`, secret scan, v6 religion/domain cleanup, `小机仔` naming, 32MB Flash + 8MB PSRAM partition design, MJPEG conversion scaffold, `.idx` byte order and loop flags, display safe region rationale, Doubao provider scaffold, direct-audio fallback, Guangzhou runbook without execution, and deferred app/RAG/custom wake/OTA/BLE/alarm scope.
- Empty-detail scan: no unresolved markers or blank fill-in fields are intentionally left for implementers.
- Boundary scan: the plan performs no deployment, no OTA publication, no artifact upload, no hardware operation, no Guangzhou SSH, and no greenunion-sh access.
- Secret-safety scan: every file cleanup and scan step uses path names or redacted scanner output only; no step opens secret-bearing files.
