# OTA P3d Rollback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add customer-safe OTA rollback validation for `miaoban-v1p2-002`, so a P3d app is marked valid only after Wi-Fi, cloud confirmation, and business initialization all reach idle.

**Architecture:** Keep the existing P3c write/switch/reboot flow intact and add a separate default-off P3d validation gate. The new app reports `post_reboot_confirm`, waits until trigger/business initialization reaches idle, calls `esp_ota_mark_app_valid_cancel_rollback()`, reports `app_validated`, and only then allows P3d closeout. A validation timeout restarts the board without marking valid, allowing ESP-IDF rollback to return to the previous valid partition.

**Tech Stack:** ESP-IDF v5.5.4 C firmware, Python CLI scripts, unittest/pytest static and API tests, existing OTA SQLite storage.

---

## File Map

- `esp_idf_demo/main/config.h`: Add default-off rollback validation macros and timeout defaults.
- `esp_idf_demo/main/main.c`: Add P3d validation state, timeout task, mark-valid path, and `app_validated` report.
- `scripts/build_esp_p3d_canary_artifact.sh`: Force the copied build source to use `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y` and fail if the generated app source still has rollback disabled.
- `scripts/build_esp_p3d_canary_artifact.sh`: Create controlled v36 P3d artifact builder for 002 only.
- `scripts/ota_release_closeout.py`: Add `--p3d` mode requiring `app_validated`.
- `tests/test_esp_assets.py`: Static tests for rollback guards, mark-valid ordering, no invalid rollback call, timeout edge case.
- `tests/test_ota_release_closeout_cli.py`: Closeout tests for P3d four-stage requirement.
- `docs/deploy/greenunion-sh-ota-p3c-runbook.md`: Add P3d handoff note or link once implementation passes.
- `docs/superpowers/specs/2026-05-19-ota-p3d-rollback-design.md`: Keep as source of truth; update only if implementation reveals a mismatch.

---

### Task 1: Add Failing Static Tests For P3d Firmware Guards

**Files:**
- Modify: `tests/test_esp_assets.py`

- [ ] **Step 1: Write failing static tests**

Append these tests after `test_ota_p3c_post_reboot_confirm_runs_in_dedicated_task`:

```python
    def test_ota_p3d_rollback_validation_is_default_off_and_gated(self) -> None:
        config = (ESP_DIR / "main" / "config.h").read_text(encoding="utf-8")
        main_source = (ESP_DIR / "main" / "main.c").read_text(encoding="utf-8")
        combined = "\n".join((config, main_source))

        self.assertIn("DEMO_OTA_ROLLBACK_VALIDATION_ENABLED", config)
        self.assertEqual("0", _read_macro_value(config, "DEMO_OTA_ROLLBACK_VALIDATION_ENABLED"))
        self.assertIn("DEMO_OTA_ROLLBACK_VALIDATION_TIMEOUT_MS", config)
        self.assertIn("#if DEMO_OTA_ROLLBACK_VALIDATION_ENABLED", main_source)
        self.assertIn("esp_ota_mark_app_valid_cancel_rollback", main_source)
        self.assertNotIn("esp_ota_mark_app_invalid_rollback_and_reboot", combined)

    def test_ota_p3d_marks_valid_only_after_business_ready(self) -> None:
        main_source = (ESP_DIR / "main" / "main.c").read_text(encoding="utf-8")

        post_confirm_pos = main_source.index("report_stage=post_reboot_confirm")
        business_ready_pos = main_source.index("app_ota_rollback_note_business_ready")
        mark_valid_pos = main_source.index("esp_ota_mark_app_valid_cancel_rollback")
        app_validated_report_pos = main_source.index("report_stage=app_validated")

        self.assertLess(post_confirm_pos, business_ready_pos)
        self.assertLess(business_ready_pos, mark_valid_pos)
        self.assertLess(mark_valid_pos, app_validated_report_pos)

    def test_ota_p3d_business_hang_edge_case_has_timeout_without_mark_valid(self) -> None:
        main_source = (ESP_DIR / "main" / "main.c").read_text(encoding="utf-8")

        self.assertIn("app_ota_rollback_validation_timeout_task", main_source)
        self.assertIn("stage=ota_app_validation event=timeout", main_source)
        self.assertIn("DEMO_OTA_ROLLBACK_VALIDATION_TIMEOUT_MS", main_source)
        self.assertIn("esp_restart()", main_source)
        timeout_pos = main_source.index("stage=ota_app_validation event=timeout")
        mark_valid_pos = main_source.index("esp_ota_mark_app_valid_cancel_rollback")
        self.assertLess(mark_valid_pos, timeout_pos)
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
env PYTHONPATH=/data/GMT-assets/testdeps/v5-realtime-opus-testdeps:. python3 -m pytest -q tests/test_esp_assets.py
```

Expected: fails because `DEMO_OTA_ROLLBACK_VALIDATION_ENABLED`, timeout task, business-ready hook, and mark-valid path do not exist.

- [ ] **Step 3: Commit tests**

Do not commit yet if the project convention avoids red commits. If keeping red commits is undesirable, leave the failing tests staged only for Task 2.

---

### Task 2: Implement Firmware Rollback Validation Gate

**Files:**
- Modify: `esp_idf_demo/main/config.h`
- Modify: `esp_idf_demo/main/main.c`
- Test: `tests/test_esp_assets.py`

- [ ] **Step 1: Add config defaults**

In `esp_idf_demo/main/config.h`, directly after `DEMO_OTA_POST_REBOOT_TASK_STACK_SIZE`, add:

```c
#ifndef DEMO_OTA_ROLLBACK_VALIDATION_ENABLED
#define DEMO_OTA_ROLLBACK_VALIDATION_ENABLED 0
#endif

#ifndef DEMO_OTA_ROLLBACK_VALIDATION_TIMEOUT_MS
#define DEMO_OTA_ROLLBACK_VALIDATION_TIMEOUT_MS 30000
#endif
```

- [ ] **Step 2: Add runtime config logging**

In `app_log_runtime_config()`, after `ota_post_reboot_task_stack_size`, add:

```c
    ESP_LOGI(TAG, "  ota_rollback_validation_enabled=%d", DEMO_OTA_ROLLBACK_VALIDATION_ENABLED);
    ESP_LOGI(TAG, "  ota_rollback_validation_timeout_ms=%d", DEMO_OTA_ROLLBACK_VALIDATION_TIMEOUT_MS);
```

- [ ] **Step 3: Add rollback validation state**

Inside the existing `#if DEMO_OTA_BOOT_SWITCH_ENABLED` region near pending OTA helpers, add:

```c
#if DEMO_OTA_ROLLBACK_VALIDATION_ENABLED
static volatile bool s_ota_rollback_validation_pending = false;
static volatile bool s_ota_rollback_business_ready = false;
static TaskHandle_t s_ota_rollback_timeout_task_handle = NULL;
static app_ota_p3c_pending_t s_ota_rollback_pending = {0};
#endif
```

If `app_ota_p3c_pending_t` is not yet declared at that insertion point, place these declarations immediately after the typedef.

- [ ] **Step 4: Add app validation report helper**

Inside the existing `#if DEMO_OTA_BOOT_SWITCH_ENABLED` region, after `app_submit_ota_boot_report`, add:

```c
#if DEMO_OTA_ROLLBACK_VALIDATION_ENABLED
static esp_err_t app_submit_ota_app_validated_report(const app_ota_p3c_pending_t *pending,
                                                     const char *app_version,
                                                     bool ok,
                                                     const char *error_code,
                                                     int *http_status)
{
    cloud_ota_update_t update = {0};
    snprintf(update.target, sizeof(update.target), "%s", "esp32s3");
    if (pending != NULL) {
        snprintf(update.version, sizeof(update.version), "%s", pending->version);
        snprintf(update.release_id, sizeof(update.release_id), "%s", pending->release_id);
    }
    return app_submit_ota_boot_report("app_validated",
                                      ok,
                                      &update,
                                      app_version,
                                      ok ? NULL : error_code,
                                      ok ? NULL : "ota app validation failed",
                                      NULL,
                                      NULL,
                                      NULL,
                                      app_reset_reason_to_string(esp_reset_reason()),
                                      http_status);
}
#endif
```

- [ ] **Step 5: Add validation timeout task**

Inside the same rollback-enabled block, add:

```c
#if DEMO_OTA_ROLLBACK_VALIDATION_ENABLED
static void app_ota_rollback_validation_timeout_task(void *arg)
{
    (void)arg;
    vTaskDelay(pdMS_TO_TICKS(DEMO_OTA_ROLLBACK_VALIDATION_TIMEOUT_MS));
    if (s_ota_rollback_validation_pending && !s_ota_rollback_business_ready) {
        ESP_LOGW(TAG,
                 "stage=ota_app_validation event=timeout release_id=%s timeout_ms=%d",
                 s_ota_rollback_pending.release_id,
                 DEMO_OTA_ROLLBACK_VALIDATION_TIMEOUT_MS);
        esp_restart();
    }
    s_ota_rollback_timeout_task_handle = NULL;
    vTaskDelete(NULL);
}
#endif
```

- [ ] **Step 6: Add validation start after post reboot confirm report succeeds**

In `app_ota_post_reboot_confirm_if_pending`, in the `report_ret == ESP_OK` block, change the clear-pending behavior:

```c
#if DEMO_OTA_ROLLBACK_VALIDATION_ENABLED
        if (ok) {
            s_ota_rollback_pending = pending;
            s_ota_rollback_validation_pending = true;
            s_ota_rollback_business_ready = false;
            BaseType_t timeout_ok = xTaskCreate(app_ota_rollback_validation_timeout_task,
                                                "ota_valid_timeout",
                                                DEMO_OTA_POST_REBOOT_TASK_STACK_SIZE,
                                                NULL,
                                                tskIDLE_PRIORITY + 1,
                                                &s_ota_rollback_timeout_task_handle);
            if (timeout_ok != pdPASS) {
                ESP_LOGW(TAG, "stage=ota_app_validation event=timeout_task_start_failed release_id=%s", pending.release_id);
            }
        } else {
            (void)app_ota_p3c_clear_pending();
        }
#else
        (void)app_ota_p3c_clear_pending();
#endif
```

Keep the existing warning path unchanged when `report_ret != ESP_OK`; do not mark valid if the report was not accepted.

- [ ] **Step 7: Add business-ready hook and mark-valid path**

Inside the existing `#if DEMO_OTA_BOOT_SWITCH_ENABLED` region, add:

```c
#if DEMO_OTA_ROLLBACK_VALIDATION_ENABLED
static void app_ota_rollback_note_business_ready(const char *app_version)
{
    if (!s_ota_rollback_validation_pending || s_ota_rollback_business_ready) {
        return;
    }
    s_ota_rollback_business_ready = true;
    ESP_LOGI(TAG,
             "stage=ota_app_validation event=start release_id=%s running_partition=%s",
             s_ota_rollback_pending.release_id,
             app_partition_label_or_empty(esp_ota_get_running_partition()));

    esp_err_t ret = esp_ota_mark_app_valid_cancel_rollback();
    int report_http_status = 0;
    esp_err_t report_ret = app_submit_ota_app_validated_report(&s_ota_rollback_pending,
                                                               app_version,
                                                               ret == ESP_OK,
                                                               esp_err_to_name(ret),
                                                               &report_http_status);
    if (ret == ESP_OK) {
        ESP_LOGI(TAG,
                 "stage=ota_app_validation event=done release_id=%s running_partition=%s",
                 s_ota_rollback_pending.release_id,
                 app_partition_label_or_empty(esp_ota_get_running_partition()));
    } else {
        ESP_LOGW(TAG,
                 "stage=ota_app_validation event=failed release_id=%s error_code=%s",
                 s_ota_rollback_pending.release_id,
                 esp_err_to_name(ret));
    }
    if (report_ret == ESP_OK) {
        ESP_LOGI(TAG,
                 "stage=ota_report event=done report_stage=app_validated http_status=%d ok=%d release_id=%s",
                 report_http_status,
                 ret == ESP_OK ? 1 : 0,
                 s_ota_rollback_pending.release_id);
    } else {
        ESP_LOGW(TAG,
                 "stage=ota_report event=failed report_stage=app_validated err=%s http_status=%d ok=%d release_id=%s",
                 esp_err_to_name(report_ret),
                 report_http_status,
                 ret == ESP_OK ? 1 : 0,
                 s_ota_rollback_pending.release_id);
    }
    if (ret == ESP_OK && report_ret == ESP_OK) {
        (void)app_ota_p3c_clear_pending();
        s_ota_rollback_validation_pending = false;
    }
}
#endif
```

- [ ] **Step 8: Call business-ready hook after trigger init and idle state**

In `app_main`, immediately after `app_set_state(&s_app_state, APP_STATE_IDLE);`, add:

```c
#if DEMO_OTA_BOOT_SWITCH_ENABLED && DEMO_OTA_ROLLBACK_VALIDATION_ENABLED
    const esp_app_desc_t *rollback_app_desc = esp_app_get_description();
    app_ota_rollback_note_business_ready(rollback_app_desc != NULL ? rollback_app_desc->version : "");
#endif
```

This ensures a hang before trigger init cannot mark valid.

- [ ] **Step 9: Run static tests to verify GREEN**

Run:

```bash
env PYTHONPATH=/data/GMT-assets/testdeps/v5-realtime-opus-testdeps:. python3 -m pytest -q tests/test_esp_assets.py
```

Expected: all tests in `tests/test_esp_assets.py` pass.

- [ ] **Step 10: Commit firmware rollback validation**

Run:

```bash
git add esp_idf_demo/main/config.h esp_idf_demo/main/main.c tests/test_esp_assets.py
git commit -m "Add OTA P3d rollback validation gate"
```

---

### Task 3: Add P3d Closeout Four-Stage Requirement

**Files:**
- Modify: `scripts/ota_release_closeout.py`
- Modify: `tests/test_ota_release_closeout_cli.py`

- [ ] **Step 1: Write failing closeout tests**

Add these tests to `tests/test_ota_release_closeout_cli.py`:

```python
    def test_p3d_closeout_rejects_missing_app_validated(self) -> None:
        self._record_report("partition_write")
        self._record_report("boot_switch_scheduled")
        self._record_report("post_reboot_confirm")
        cli = _load_cli_module()

        exit_code = cli.main([
            "--release-id",
            "2026-05-19-v35-002-p3c",
            "--device-id",
            "miaoban-v1p2-002",
            "--p3d",
        ])

        self.assertEqual(exit_code, 2)

    def test_p3d_closeout_disables_release_after_app_validated(self) -> None:
        self._record_report("partition_write")
        self._record_report("boot_switch_scheduled")
        self._record_report("post_reboot_confirm")
        self._record_report("app_validated")
        cli = _load_cli_module()

        exit_code = cli.main([
            "--release-id",
            "2026-05-19-v35-002-p3c",
            "--device-id",
            "miaoban-v1p2-002",
            "--p3d",
        ])

        self.assertEqual(exit_code, 0)
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
env PYTHONPATH=/data/GMT-assets/testdeps/v5-realtime-opus-testdeps:. python3 -m pytest -q tests/test_ota_release_closeout_cli.py
```

Expected: fails because `--p3d` does not exist.

- [ ] **Step 3: Implement `--p3d` closeout mode**

In `scripts/ota_release_closeout.py`, replace the single `REQUIRED_STAGES` constant with:

```python
P3C_REQUIRED_STAGES = ["partition_write", "boot_switch_scheduled", "post_reboot_confirm"]
P3D_REQUIRED_STAGES = [*P3C_REQUIRED_STAGES, "app_validated"]
```

In `build_parser()`, add:

```python
    parser.add_argument("--p3d", action="store_true", help="Require P3d app validation before closeout")
```

In `main()`, replace:

```python
    missing = [stage for stage in REQUIRED_STAGES if not _has_ok_report(args.release_id, args.device_id, stage)]
```

with:

```python
    required_stages = P3D_REQUIRED_STAGES if args.p3d else P3C_REQUIRED_STAGES
    missing = [stage for stage in required_stages if not _has_ok_report(args.release_id, args.device_id, stage)]
```

- [ ] **Step 4: Run closeout tests to verify GREEN**

Run:

```bash
env PYTHONPATH=/data/GMT-assets/testdeps/v5-realtime-opus-testdeps:. python3 -m pytest -q tests/test_ota_release_closeout_cli.py
```

Expected: all closeout tests pass.

- [ ] **Step 5: Commit closeout mode**

Run:

```bash
git add scripts/ota_release_closeout.py tests/test_ota_release_closeout_cli.py
git commit -m "Require app validation for P3d closeout"
```

---

### Task 4: Add Controlled P3d Artifact Build Script

**Files:**
- Create: `scripts/build_esp_p3d_canary_artifact.sh`
- Test: `tests/test_esp_assets.py`

- [ ] **Step 1: Add failing static test for script**

Add this test to `tests/test_esp_assets.py`:

```python
    def test_p3d_canary_build_script_enables_rollback_without_password(self) -> None:
        script = (ROOT / "scripts" / "build_esp_p3d_canary_artifact.sh").read_text(encoding="utf-8")

        self.assertIn("PROJECT_VER=${PROJECT_VER:-v36-p3d-canary}", script)
        self.assertIn("DEMO_OTA_BOOT_SWITCH_ENABLED 1", script)
        self.assertIn("DEMO_OTA_ROLLBACK_VALIDATION_ENABLED 1", script)
        self.assertIn("CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y", script)
        self.assertIn("# CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE is not set", script)
        self.assertIn("SDKCONFIG=", script)
        self.assertIn("rollback config was not enabled", script)
        self.assertIn("CANARY_DEVICE_ID=${CANARY_DEVICE_ID:-miaoban-v1p2-002}", script)
        self.assertNotIn("DEMO_WIFI_PASSWORD", script)
```

- [ ] **Step 2: Run test to verify RED**

Run:

```bash
env PYTHONPATH=/data/GMT-assets/testdeps/v5-realtime-opus-testdeps:. python3 -m pytest -q tests/test_esp_assets.py::EspAssetTests::test_p3d_canary_build_script_enables_rollback_without_password
```

Expected: fails because script does not exist.

- [ ] **Step 3: Create P3d build script**

Create `scripts/build_esp_p3d_canary_artifact.sh` based on `scripts/build_esp_p3c_canary_artifact.sh`, with these differences:

```bash
SRC_DIR="${SRC_DIR:-/tmp/v36_p3d_artifact_src}"
BUILD_DIR="${BUILD_DIR:-/tmp/v36_p3d_artifact_build}"
OUT_BIN="${OUT_BIN:-${ROOT_DIR}/tmp/esp_idf_demo_v36_p3d_002_20260519.bin}"
PROJECT_VER="${PROJECT_VER:-v36-p3d-canary}"
```

After enabling `DEMO_OTA_BOOT_SWITCH_ENABLED`, add:

```bash
SDKCONFIG="${SRC_DIR}/esp_idf_demo/sdkconfig"
perl -0pi -e 's/#define DEMO_OTA_ROLLBACK_VALIDATION_ENABLED 0/#define DEMO_OTA_ROLLBACK_VALIDATION_ENABLED 1/' "${CONFIG_H}"
perl -0pi -e 's/# CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE is not set/CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y/' "${SDKCONFIG}"
cat >> "${SRC_DIR}/esp_idf_demo/sdkconfig.defaults" <<'EOF'
CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y
EOF
```

After `idf.py ... build`, add:

```bash
if ! rg -q '^CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y$' "${SRC_DIR}/esp_idf_demo/sdkconfig"; then
  echo "rollback config was not enabled in ${SRC_DIR}/esp_idf_demo/sdkconfig" >&2
  exit 1
fi
```

Keep the existing no-password behavior: set SSID, server URL, and device id only. Do not add `DEMO_WIFI_PASSWORD`.

- [ ] **Step 4: Make script executable**

Run:

```bash
chmod +x scripts/build_esp_p3d_canary_artifact.sh
```

- [ ] **Step 5: Run static test to verify GREEN**

Run:

```bash
env PYTHONPATH=/data/GMT-assets/testdeps/v5-realtime-opus-testdeps:. python3 -m pytest -q tests/test_esp_assets.py::EspAssetTests::test_p3d_canary_build_script_enables_rollback_without_password
```

Expected: test passes.

- [ ] **Step 6: Commit build script**

Run:

```bash
git add scripts/build_esp_p3d_canary_artifact.sh tests/test_esp_assets.py
git commit -m "Add P3d rollback canary artifact builder"
```

---

### Task 5: Document P3d Runbook Delta

**Files:**
- Modify: `docs/deploy/greenunion-sh-ota-p3c-runbook.md`
- Modify: `handoff/README.md`

- [ ] **Step 1: Add P3d customer gate note**

In `docs/deploy/greenunion-sh-ota-p3c-runbook.md`, add a new section:

```markdown
## P3d Rollback Gate Before Customer Handoff

Do not ship `miaoban-v1p2-002` to a customer on a new OTA artifact unless P3d rollback validation has passed.

P3d requires:

- rollback-enabled bootloader on `miaoban-v1p2-002`; app-only OTA cannot retrofit bootloader rollback support
- rollback-enabled artifact, not the completed v35 P3c artifact
- new release id, for example `2026-05-19-v36-002-p3d`
- whitelist only `miaoban-v1p2-002`
- successful reports for `partition_write`, `boot_switch_scheduled`, `post_reboot_confirm`, and `app_validated`
- `scripts/ota_release_closeout.py --p3d`
- a fault-injection or timeout validation showing that no `app_validated` report is emitted when business initialization hangs

Do not include `miaoban-v1p2-003` in P3d.
```

- [ ] **Step 2: Add handoff note**

In `handoff/README.md`, add a concise note that P3c is complete but customer handoff requires P3d rollback validation.

- [ ] **Step 3: Run docs checks**

Run:

```bash
git diff --check
rg -n "P3d|app_validated|--p3d|003" docs/deploy/greenunion-sh-ota-p3c-runbook.md handoff/README.md
```

Expected: `git diff --check` has no output; `rg` shows the P3d notes and 003 exclusion.

- [ ] **Step 4: Commit docs**

Run:

```bash
git add docs/deploy/greenunion-sh-ota-p3c-runbook.md handoff/README.md
git commit -m "Document P3d rollback handoff gate"
```

---

### Task 6: Full Verification

**Files:**
- No source edits unless verification reveals a defect.

- [ ] **Step 1: Run focused tests**

Run:

```bash
env PYTHONPATH=/data/GMT-assets/testdeps/v5-realtime-opus-testdeps:. python3 -m pytest -q tests/test_esp_assets.py tests/test_ota_release_closeout_cli.py
```

Expected: all focused tests pass.

- [ ] **Step 2: Run full pytest**

Run:

```bash
env PYTHONPATH=/data/GMT-assets/testdeps/v5-realtime-opus-testdeps:. python3 -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 3: Run whitespace check**

Run:

```bash
git diff --check
```

Expected: no output.

- [ ] **Step 4: Build default firmware**

Run:

```bash
. /data/esp/esp-idf-v5.5.4-full/export.sh
idf.py -C esp_idf_demo build
```

Expected: default build completes with rollback validation disabled in source defaults.

- [ ] **Step 5: Build P3d artifact**

Run:

```bash
PROJECT_VER=v36-p3d-canary \
OUT_BIN=/home/hanxiao_zhu_us/GMT/20260508_v5_realtime_opus/tmp/esp_idf_demo_v36_p3d_002_20260519.bin \
SRC_DIR=/tmp/v36_p3d_artifact_src \
BUILD_DIR=/tmp/v36_p3d_artifact_build \
CANARY_WIFI_SSID=GMT-G60 \
CANARY_SERVER_BASE_URL=http://106.54.240.51 \
CANARY_DEVICE_ID=miaoban-v1p2-002 \
scripts/build_esp_p3d_canary_artifact.sh
```

Expected: binary is produced, size is below the 3 MB OTA slot, and `sha256sum` prints the artifact hash.

If `idf.py` hangs after the binary is produced, verify whether `/tmp/v36_p3d_artifact_build/esp_idf_demo.bin` exists before interrupting. Do not claim build success unless the artifact path exists and `sha256sum` succeeds.

- [ ] **Step 6: Verify artifact strings**

Run:

```bash
strings tmp/esp_idf_demo_v36_p3d_002_20260519.bin | rg "v36-p3d-canary|miaoban-v1p2-002|GMT-G60|http://106\.54\.240\.51|using stored Wi-Fi station credentials from NVS"
```

Expected: all listed strings are present. No password string should be introduced.

- [ ] **Step 7: Commit verification-only fixes if needed**

If any verification step required source changes, commit those changes with a focused message. If no changes were needed, do not create an empty commit.

---

## Execution Handoff

Recommended execution mode: Subagent-driven or a fresh execution Codex session, one task at a time, with review after each task.

Do not deploy, create a P3d release, upload artifacts, or operate the real board during implementation. Those actions require a separate explicit authorization after local tests and builds pass.
