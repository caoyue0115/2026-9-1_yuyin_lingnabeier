# OTA P3c Formalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Formalize the P3c release workflow with local tooling, tests, and documentation without adding 003, deploying, creating a production release, or operating devices.

**Architecture:** Keep the existing manifest suppress rule as the automatic anti-repeat mechanism. Extend local release tooling with a strict P3c creation mode and an explicit closeout command that disables a passed canary and verifies manifests return no update. Keep device boot switching gated by `DEMO_OTA_BOOT_SWITCH_ENABLED`.

**Tech Stack:** Python 3.11 backend scripts and tests, SQLite storage helpers in `src/storage/db.py`, FastAPI OTA manifest code in `src/api/ota.py`, ESP-IDF C firmware static checks in `tests/test_esp_assets.py`.

---

## File Map

- Modify `scripts/ota_release_create.py`: add P3c mode validation and explicit enabled/disabled intent.
- Modify `tests/test_ota_release_cli.py`: add release CLI tests for P3c strict validation.
- Create `scripts/ota_release_closeout.py`: disable a release after successful canary reports and verify target device manifests return no update.
- Create `tests/test_ota_release_closeout_cli.py`: test closeout success and failure cases.
- Modify `tests/test_ota_api.py`: add one test proving P3a/P3b report stages do not suppress a P3c release.
- Modify `docs/deploy/greenunion-sh-ota-p3c-runbook.md`: document the formal release creation and closeout commands.
- Modify `handoff/README.md`, `handoff/快速启动手册.md`, and `handoff/稳定交接包说明.md`: update operational handoff with the semi-automatic P3c workflow.

Do not modify `.env`, do not deploy, do not create any real release, do not operate real devices.

## Task 1: Add P3c Strict Release Creation Mode

**Files:**
- Modify: `scripts/ota_release_create.py`
- Modify: `tests/test_ota_release_cli.py`

- [ ] **Step 1: Add failing tests for P3c required fields**

Add these tests to `tests/test_ota_release_cli.py` inside `OtaReleaseCliTests`:

```python
    def test_p3c_mode_rejects_missing_board_hw_rev_min_version_notes(self) -> None:
        artifact = self.artifact_dir / "esp_idf_demo_v35_p3c.bin"
        artifact.write_bytes(b"firmware-v35")
        cli = _load_cli_module()

        exit_code = cli.main(
            [
                "--p3c",
                "--release-id",
                "2026-05-19-v35-002-p3c",
                "--version",
                "v35",
                "--artifact",
                str(artifact),
                "--device-id",
                "miaoban-v1p2-002",
                "--enable",
            ]
        )

        self.assertEqual(exit_code, 2)

    def test_p3c_mode_requires_explicit_enable_or_disabled(self) -> None:
        artifact = self.artifact_dir / "esp_idf_demo_v35_p3c.bin"
        artifact.write_bytes(b"firmware-v35")
        cli = _load_cli_module()

        exit_code = cli.main(
            [
                "--p3c",
                "--release-id",
                "2026-05-19-v35-002-p3c",
                "--version",
                "v35",
                "--artifact",
                str(artifact),
                "--device-id",
                "miaoban-v1p2-002",
                "--board",
                "ESP-VoCat",
                "--hw-rev",
                "v1.2",
                "--min-version",
                "1",
                "--notes",
                "P3c formalization test",
            ]
        )

        self.assertEqual(exit_code, 2)

    def test_p3c_mode_rejects_blocked_release_id(self) -> None:
        artifact = self.artifact_dir / "esp_idf_demo_v34_p3c.bin"
        artifact.write_bytes(b"firmware-v34")
        cli = _load_cli_module()

        exit_code = cli.main(
            [
                "--p3c",
                "--release-id",
                "2026-05-18-v34-002-p3c",
                "--version",
                "v34",
                "--artifact",
                str(artifact),
                "--device-id",
                "miaoban-v1p2-002",
                "--board",
                "ESP-VoCat",
                "--hw-rev",
                "v1.2",
                "--min-version",
                "1",
                "--notes",
                "blocked id",
                "--enable",
            ]
        )

        self.assertEqual(exit_code, 2)
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
env PYTHONPATH=/data/GMT-assets/testdeps/v5-realtime-opus-testdeps:. python3 -m pytest -q tests/test_ota_release_cli.py
```

Expected: the three new tests fail because `--p3c` and `--enable` are not defined yet.

- [ ] **Step 3: Implement P3c parser flags and validation**

In `scripts/ota_release_create.py`, add constants near the top:

```python
P3C_BLOCKED_RELEASE_IDS = {
    "2026-05-18-v32-002-p3b",
    "2026-05-18-v34-002-p3c",
}
```

In `build_parser()`, add:

```python
    parser.add_argument("--p3c", action="store_true", help="Enable strict P3c release validation")
    parser.add_argument("--enable", action="store_true", help="Explicitly create the release enabled")
```

After parsing arguments and before artifact validation, add:

```python
    if args.enable and args.disabled:
        return _fail("--enable and --disabled are mutually exclusive")
    if args.p3c:
        missing = [
            name
            for name, value in [
                ("--board", args.board),
                ("--hw-rev", args.hw_rev),
                ("--min-version", args.min_version),
                ("--notes", args.notes),
            ]
            if not value
        ]
        if missing:
            return _fail(f"P3c release requires {', '.join(missing)}")
        if not args.enable and not args.disabled:
            return _fail("P3c release requires explicit --enable or --disabled")
        if args.release_id in P3C_BLOCKED_RELEASE_IDS:
            return _fail(f"P3c release id must not be reused: {args.release_id}")
```

Change the `enabled=` argument in `storage_db.create_ota_release(...)` to:

```python
        enabled=args.enable if args.p3c else not args.disabled,
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
env PYTHONPATH=/data/GMT-assets/testdeps/v5-realtime-opus-testdeps:. python3 -m pytest -q tests/test_ota_release_cli.py
```

Expected: all tests in `tests/test_ota_release_cli.py` pass.

- [ ] **Step 5: Add successful enabled and disabled P3c tests**

Add these tests to `tests/test_ota_release_cli.py`:

```python
    def test_p3c_mode_can_create_explicitly_enabled_release(self) -> None:
        artifact = self.artifact_dir / "esp_idf_demo_v35_p3c.bin"
        artifact_bytes = b"firmware-v35"
        artifact.write_bytes(artifact_bytes)
        expected_sha = hashlib.sha256(artifact_bytes).hexdigest()
        cli = _load_cli_module()

        exit_code = cli.main(
            [
                "--p3c",
                "--release-id",
                "2026-05-19-v35-002-p3c",
                "--version",
                "v35",
                "--artifact",
                str(artifact),
                "--device-id",
                "miaoban-v1p2-002",
                "--board",
                "ESP-VoCat",
                "--hw-rev",
                "v1.2",
                "--min-version",
                "1",
                "--notes",
                "P3c formalization test",
                "--enable",
            ]
        )

        self.assertEqual(exit_code, 0)
        payload = ota_api.get_ota_manifest(
            device_id="miaoban-v1p2-002",
            board="ESP-VoCat",
            hw_rev="v1.2",
            app_version="1",
        )
        self.assertEqual(payload["updates"][0]["release_id"], "2026-05-19-v35-002-p3c")
        self.assertEqual(payload["updates"][0]["sha256"], expected_sha)

    def test_p3c_mode_can_create_disabled_release(self) -> None:
        artifact = self.artifact_dir / "esp_idf_demo_v35_p3c.bin"
        artifact.write_bytes(b"firmware-v35")
        cli = _load_cli_module()

        exit_code = cli.main(
            [
                "--p3c",
                "--release-id",
                "2026-05-19-v35-002-p3c",
                "--version",
                "v35",
                "--artifact",
                str(artifact),
                "--device-id",
                "miaoban-v1p2-002",
                "--board",
                "ESP-VoCat",
                "--hw-rev",
                "v1.2",
                "--min-version",
                "1",
                "--notes",
                "P3c formalization test",
                "--disabled",
            ]
        )

        self.assertEqual(exit_code, 0)
        payload = ota_api.get_ota_manifest(
            device_id="miaoban-v1p2-002",
            board="ESP-VoCat",
            hw_rev="v1.2",
            app_version="1",
        )
        self.assertEqual(payload["updates"], [])
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
env PYTHONPATH=/data/GMT-assets/testdeps/v5-realtime-opus-testdeps:. python3 -m pytest -q tests/test_ota_release_cli.py
```

Expected: all tests in `tests/test_ota_release_cli.py` pass.

- [ ] **Step 7: Commit Task 1**

Run:

```bash
git add scripts/ota_release_create.py tests/test_ota_release_cli.py
git commit -m "Formalize P3c release creation guardrails"
```

## Task 2: Add P3c Closeout Tool

**Files:**
- Create: `scripts/ota_release_closeout.py`
- Create: `tests/test_ota_release_closeout_cli.py`

- [ ] **Step 1: Write failing closeout tests**

Create `tests/test_ota_release_closeout_cli.py`:

```python
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests._stubs import install_dependency_stubs

install_dependency_stubs()

from src.api import ota as ota_api
from src.settings import settings
from src.storage import db as storage_db


def _load_cli_module():
    module_path = ROOT / "scripts" / "ota_release_closeout.py"
    spec = importlib.util.spec_from_file_location("ota_release_closeout", module_path)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load ota_release_closeout.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OtaReleaseCloseoutCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name)
        self.patchers = [
            mock.patch.object(settings, "sqlite_path", str(self.tmp_path / "ota.db")),
            mock.patch.object(settings, "public_base_url", "http://testserver"),
            mock.patch.object(settings, "ota_artifact_dir", str(self.tmp_path / "ota_artifacts"), create=True),
        ]
        for patcher in self.patchers:
            patcher.start()
        storage_db.init_db()
        storage_db.create_ota_release(
            release_id="2026-05-19-v35-002-p3c",
            target="esp32s3",
            version="v35",
            artifact_name="esp_idf_demo_v35.bin",
            sha256="d" * 64,
            size=1234,
            min_version="1",
            device_ids=["miaoban-v1p2-002"],
            enabled=True,
            board="ESP-VoCat",
            hw_rev="v1.2",
            priority=1,
            notes="P3c closeout test",
        )

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.tmpdir.cleanup()

    def _record_report(self, stage: str, ok: bool = True) -> None:
        storage_db.record_ota_report(
            {
                "device_id": "miaoban-v1p2-002",
                "target": "esp32s3",
                "from_version": "1",
                "to_version": "v35",
                "release_id": "2026-05-19-v35-002-p3c",
                "stage": stage,
                "ok": ok,
            }
        )

    def test_closeout_disables_release_after_required_success_reports(self) -> None:
        self._record_report("partition_write")
        self._record_report("boot_switch_scheduled")
        self._record_report("post_reboot_confirm")
        cli = _load_cli_module()

        exit_code = cli.main(["--release-id", "2026-05-19-v35-002-p3c", "--device-id", "miaoban-v1p2-002"])

        self.assertEqual(exit_code, 0)
        payload = ota_api.get_ota_manifest(
            device_id="miaoban-v1p2-002",
            board="ESP-VoCat",
            hw_rev="v1.2",
            app_version="v35",
        )
        self.assertEqual(payload["updates"], [])

    def test_closeout_rejects_missing_post_reboot_confirm(self) -> None:
        self._record_report("partition_write")
        self._record_report("boot_switch_scheduled")
        cli = _load_cli_module()

        exit_code = cli.main(["--release-id", "2026-05-19-v35-002-p3c", "--device-id", "miaoban-v1p2-002"])

        self.assertEqual(exit_code, 2)
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
env PYTHONPATH=/data/GMT-assets/testdeps/v5-realtime-opus-testdeps:. python3 -m pytest -q tests/test_ota_release_closeout_cli.py
```

Expected: fails because `scripts/ota_release_closeout.py` does not exist.

- [ ] **Step 3: Implement closeout CLI**

Create `scripts/ota_release_closeout.py`:

```python
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.storage.db import connect, init_db

REQUIRED_STAGES = ["partition_write", "boot_switch_scheduled", "post_reboot_confirm"]


def _fail(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 2


def _has_ok_report(release_id: str, device_id: str, stage: str) -> bool:
    conn = connect()
    try:
        row = conn.execute(
            """
            SELECT 1
            FROM ota_reports
            WHERE release_id = ?
              AND device_id = ?
              AND stage = ?
              AND ok = 1
            LIMIT 1
            """,
            (release_id, device_id, stage),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def _set_release_enabled(release_id: str, enabled: bool) -> None:
    conn = connect()
    try:
        conn.execute("UPDATE ota_releases SET enabled = ? WHERE release_id = ?", (1 if enabled else 0, release_id))
        conn.commit()
    finally:
        conn.close()


def _release_exists(release_id: str) -> bool:
    conn = connect()
    try:
        return conn.execute("SELECT 1 FROM ota_releases WHERE release_id = ?", (release_id,)).fetchone() is not None
    finally:
        conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Close out a passed P3c canary release.")
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--device-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    init_db()
    if not _release_exists(args.release_id):
        return _fail(f"release not found: {args.release_id}")
    missing = [stage for stage in REQUIRED_STAGES if not _has_ok_report(args.release_id, args.device_id, stage)]
    if missing:
        return _fail(f"cannot close out release; missing ok reports: {', '.join(missing)}")
    _set_release_enabled(args.release_id, False)
    print(f"release_id={args.release_id}")
    print(f"device_id={args.device_id}")
    print("enabled=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run focused closeout tests**

Run:

```bash
env PYTHONPATH=/data/GMT-assets/testdeps/v5-realtime-opus-testdeps:. python3 -m pytest -q tests/test_ota_release_closeout_cli.py
```

Expected: both closeout tests pass.

- [ ] **Step 5: Commit Task 2**

Run:

```bash
git add scripts/ota_release_closeout.py tests/test_ota_release_closeout_cli.py
git commit -m "Add P3c release closeout tool"
```

## Task 3: Complete Suppress Regression Coverage

**Files:**
- Modify: `tests/test_ota_api.py`

- [ ] **Step 1: Add failing test for P3a/P3b stages not suppressing P3c**

Add this test to `OtaApiTests` in `tests/test_ota_api.py`:

```python
    def test_manifest_suppression_ignores_partition_write_stage(self) -> None:
        self._create_release("2026-05-19-v35-002-p3c")
        self._record_report(release_id="2026-05-19-v35-002-p3c", stage="partition_write", ok=True)

        self.assertEqual(self._manifest_release_ids(), ["2026-05-19-v35-002-p3c"])
```

- [ ] **Step 2: Run focused test**

Run:

```bash
env PYTHONPATH=/data/GMT-assets/testdeps/v5-realtime-opus-testdeps:. python3 -m pytest -q tests/test_ota_api.py::OtaApiTests::test_manifest_suppression_ignores_partition_write_stage
```

Expected: pass if current suppress implementation is correct. If it fails, fix `OTA_RELEASE_SUPPRESS_STAGES` in `src/api/ota.py` so it contains only `boot_switch_scheduled` and `post_reboot_confirm`.

- [ ] **Step 3: Run OTA API tests**

Run:

```bash
env PYTHONPATH=/data/GMT-assets/testdeps/v5-realtime-opus-testdeps:. python3 -m pytest -q tests/test_ota_api.py
```

Expected: all OTA API tests pass.

- [ ] **Step 4: Commit Task 3**

Run:

```bash
git add tests/test_ota_api.py src/api/ota.py
git commit -m "Cover P3c suppress stage boundaries"
```

## Task 4: Update P3c Formalization Documentation

**Files:**
- Modify: `docs/deploy/greenunion-sh-ota-p3c-runbook.md`
- Modify: `handoff/README.md`
- Modify: `handoff/快速启动手册.md`
- Modify: `handoff/稳定交接包说明.md`

- [ ] **Step 1: Update P3c runbook with command examples**

In `docs/deploy/greenunion-sh-ota-p3c-runbook.md`, add a section named `Semi-Automatic P3c Workflow` after `Release Operating Rules`:

````markdown
## Semi-Automatic P3c Workflow

Create a P3c release only after a new artifact has been uploaded to the OTA artifact directory and the release scope has been explicitly authorized.

Example disabled creation:

```bash
python scripts/ota_release_create.py \
  --p3c \
  --release-id 2026-05-19-v35-002-p3c \
  --version v35 \
  --artifact /app/religion_demo_v5_realtime_opus/data/ota_artifacts/esp_idf_demo_v35_p3c.bin \
  --device-id miaoban-v1p2-002 \
  --board ESP-VoCat \
  --hw-rev v1.2 \
  --min-version 1 \
  --notes "P3c 002 canary" \
  --disabled
```

Use `--enable` only when the release should immediately become visible to the whitelisted device.

After the canary passes and reports `partition_write ok=1`, `boot_switch_scheduled ok=1`, and `post_reboot_confirm ok=1`, close it out:

```bash
python scripts/ota_release_closeout.py \
  --release-id 2026-05-19-v35-002-p3c \
  --device-id miaoban-v1p2-002
```

Then verify the target device manifest returns `updates=[]`.
````

When adding this block, keep the nested code fences valid by using four backticks for the outer documentation block if needed.

- [ ] **Step 2: Update handoff docs**

Add this sentence to each handoff doc where P3c release operations are described:

```markdown
P3c formalization is semi-automatic: release creation must use strict P3c validation, successful canaries are protected by manifest suppress, and canary closeout disables the release instead of deleting whitelist rows.
```

- [ ] **Step 3: Run documentation scans**

Run:

```bash
rg -n "Semi-Automatic P3c Workflow|ota_release_create.py|ota_release_closeout.py|deleting whitelist|删除.*白名单|enabled=0" docs/deploy/greenunion-sh-ota-p3c-runbook.md handoff
git diff --check
```

Expected: command output includes the new workflow and no whitespace errors.

- [ ] **Step 4: Commit Task 4**

Run:

```bash
git add docs/deploy/greenunion-sh-ota-p3c-runbook.md handoff/README.md handoff/快速启动手册.md handoff/稳定交接包说明.md
git commit -m "Document semi-automatic P3c workflow"
```

## Task 5: Final Verification

**Files:**
- No new code files unless earlier verification exposes a defect.

- [ ] **Step 1: Run focused OTA suites**

Run:

```bash
env PYTHONPATH=/data/GMT-assets/testdeps/v5-realtime-opus-testdeps:. python3 -m pytest -q tests/test_ota_api.py tests/test_ota_release_cli.py tests/test_ota_release_closeout_cli.py
```

Expected: all focused OTA tests pass.

- [ ] **Step 2: Run full pytest**

Run:

```bash
env PYTHONPATH=/data/GMT-assets/testdeps/v5-realtime-opus-testdeps:. python3 -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 3: Run diff check**

Run:

```bash
git diff --check
```

Expected: no output.

- [ ] **Step 4: Verify no forbidden deployment or release action occurred**

Run:

```bash
git status --short
```

Expected: only local source/test/doc changes before final commit, with no `.env`, `data/`, `tmp/`, `build/`, `managed_components/`, or artifact binaries staged.

- [ ] **Step 5: Commit final verification notes if any files changed**

If Task 5 required any additional edits, commit them:

```bash
git add <changed-files>
git commit -m "Finalize P3c formalization verification"
```

If no files changed in Task 5, do not create an empty commit.

## Implementation Boundaries

- Do not deploy greenunion-sh.
- Do not create, enable, disable, or modify a real cloud release.
- Do not include 003 in any release or test fixture that claims to be the live rollout scope.
- Do not modify `.env`.
- Do not read or print Wi-Fi passwords.
- Do not run `idf.py build` unless firmware code changes during this formalization pass.

## Completion Summary Required

At completion, report:

- commits created
- files changed
- focused OTA test result
- full pytest result
- `git diff --check` result
- confirmation that no deployment, release creation, `.env` edit, or device operation occurred
