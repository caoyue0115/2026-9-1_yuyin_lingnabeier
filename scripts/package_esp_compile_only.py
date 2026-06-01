#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import tarfile
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ESP_SYSTEM_EVENT_TASK_STACK_CONFIG = "CONFIG_ESP_SYSTEM_EVENT_TASK_STACK_SIZE=4096"
SYSTEM_EVENT_TASK_STACK_CONFIG = "CONFIG_SYSTEM_EVENT_TASK_STACK_SIZE=4096"
TRIGGER_SOURCE_MACROS = {
    "button": "BUTTON",
    "touch": "TOUCH",
    "wake_word": "WAKE_WORD",
    "button_and_wake_word": "BUTTON_AND_WAKE_WORD",
}


BASE_EXCLUDED_DIRS = {
    ".git",
    "build",
    "__pycache__",
    "tmp",
    "data",
    "indices",
}


def _copy_source_tree(source_root: Path, staging_root: Path, *, include_managed_components: bool) -> Path:
    esp_source = source_root / "esp_idf_demo"
    if not esp_source.is_dir():
        raise SystemExit(f"missing esp_idf_demo directory under {source_root}")

    esp_dest = staging_root / "esp_idf_demo"
    excluded_dirs = set(BASE_EXCLUDED_DIRS)
    if not include_managed_components:
        excluded_dirs.add("managed_components")

    def ignore(_: str, names: list[str]) -> set[str]:
        ignored = {name for name in names if name in excluded_dirs}
        ignored.update(name for name in names if name.endswith(".pyc"))
        ignored.update(name for name in names if name.endswith(".bin"))
        ignored.update(name for name in names if name.startswith(".env"))
        return ignored

    shutil.copytree(esp_source, esp_dest, ignore=ignore, symlinks=False)
    return esp_dest


def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")


def _replace_required(text: str, old: str, new: str, *, path: Path) -> str:
    if old not in text:
        raise SystemExit(f"missing expected text in {path}: {old}")
    return text.replace(old, new, 1)


def _set_sdkconfig_value(text: str, key: str, value: str) -> str:
    line = f"{key}={value}"
    lines = text.splitlines()
    for index, existing in enumerate(lines):
        if existing.startswith(f"{key}="):
            lines[index] = line
            return "\n".join(lines).rstrip() + "\n"
    return text.rstrip() + f"\n{line}\n"


def _set_trigger_source(text: str, trigger_source: str, *, path: Path) -> str:
    macro_suffix = TRIGGER_SOURCE_MACROS[trigger_source]
    pattern = re.compile(
        r"^#define\s+DEMO_TRIGGER_SOURCE\s+DEMO_TRIGGER_SOURCE_[A-Z_]+$",
        re.MULTILINE,
    )
    replacement = f"#define DEMO_TRIGGER_SOURCE DEMO_TRIGGER_SOURCE_{macro_suffix}"
    updated, count = pattern.subn(replacement, text, count=1)
    if count != 1:
        raise SystemExit(f"missing expected DEMO_TRIGGER_SOURCE define in {path}")
    return updated


def _inject_p3d_canary_config(
    esp_dest: Path,
    *,
    wifi_ssid: str,
    server_base_url: str,
    device_id: str,
    trigger_source: str,
    button_gpio: int,
) -> None:
    config_path = esp_dest / "main" / "config.h"
    if not config_path.exists():
        return

    config = config_path.read_text(encoding="utf-8")
    config = _replace_required(
        config,
        '#define DEMO_WIFI_SSID           ""',
        f'#define DEMO_WIFI_SSID           "{wifi_ssid}"',
        path=config_path,
    )
    config = _replace_required(
        config,
        '#define DEMO_SERVER_BASE_URL     ""',
        f'#define DEMO_SERVER_BASE_URL     "{server_base_url}"',
        path=config_path,
    )
    config = _replace_required(
        config,
        '#define DEMO_DEVICE_ID           ""',
        f'#define DEMO_DEVICE_ID           "{device_id}"',
        path=config_path,
    )
    config = _replace_required(
        config,
        "#define DEMO_OTA_BOOT_SWITCH_ENABLED 0",
        "#define DEMO_OTA_BOOT_SWITCH_ENABLED 1",
        path=config_path,
    )
    config = _replace_required(
        config,
        "#define DEMO_OTA_ROLLBACK_VALIDATION_ENABLED 0",
        "#define DEMO_OTA_ROLLBACK_VALIDATION_ENABLED 1",
        path=config_path,
    )
    config = _set_trigger_source(config, trigger_source, path=config_path)
    config = _replace_required(
        config,
        "#define DEMO_BUTTON_GPIO         GPIO_NUM_7",
        f"#define DEMO_BUTTON_GPIO         GPIO_NUM_{button_gpio}",
        path=config_path,
    )
    config_path.write_text(config, encoding="utf-8", newline="\n")

    sdkconfig = esp_dest / "sdkconfig"
    if sdkconfig.exists():
        config_text = sdkconfig.read_text(encoding="utf-8")
        key, value = ESP_SYSTEM_EVENT_TASK_STACK_CONFIG.split("=", 1)
        config_text = _set_sdkconfig_value(config_text, key, value)
        key, value = SYSTEM_EVENT_TASK_STACK_CONFIG.split("=", 1)
        config_text = _set_sdkconfig_value(config_text, key, value)
        if "CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y" not in config_text:
            if "# CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE is not set" in config_text:
                config_text = config_text.replace(
                    "# CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE is not set",
                    "CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y",
                    1,
                )
            else:
                config_text = config_text.rstrip() + "\nCONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y\n"
            sdkconfig.write_text(config_text, encoding="utf-8", newline="\n")

    sdkconfig_defaults = esp_dest / "sdkconfig.defaults"
    if not sdkconfig_defaults.exists():
        return

    defaults = sdkconfig_defaults.read_text(encoding="utf-8")
    if "CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y" not in defaults:
        defaults = defaults.rstrip() + "\nCONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y\n"
    key, value = ESP_SYSTEM_EVENT_TASK_STACK_CONFIG.split("=", 1)
    defaults = _set_sdkconfig_value(defaults, key, value)
    sdkconfig_defaults.write_text(defaults, encoding="utf-8", newline="\n")


def _inject_hardware_entrypoints(
    esp_dest: Path,
    *,
    project_version: str,
    device_id: str,
    default_port: str,
) -> None:
    _write_text(
        esp_dest / "BUILD_INFO.txt",
        f"""ESP compile-only handoff

device_id={device_id}
project_version={project_version}
default_windows_port={default_port}

Hardware Windows PowerShell:
  .\\build_flash_p3d_002.ps1 {default_port}

Hardware Windows CMD:
  build_flash_p3d_002.cmd {default_port}

Linux/macOS ESP-IDF shell:
  ./build_flash_p3d_002.sh /dev/ttyUSB0

Acceptance log lines:
  App version:      {project_version}
  stage=ota_manifest_dry_run ... app_version={project_version}

Do not use the VSCode build button for this canary unless it is configured to pass PROJECT_VER={project_version}.
""",
    )

    _write_text(
        esp_dest / "build_flash_p3d_002.ps1",
        f"""param(
    [string]$Port = "{default_port}",
    [switch]$NoFlash
)

$ErrorActionPreference = "Stop"
$ProjectVer = "{project_version}"
$env:PROJECT_VER = $ProjectVer

function Invoke-Idf {{
    $idfCommand = Get-Command idf.py -ErrorAction Stop
    python $idfCommand.Source @args
    if ($LASTEXITCODE -ne 0) {{
        throw "idf.py failed with exit code $LASTEXITCODE"
    }}
}}

Write-Host "PROJECT_VER=$ProjectVer"
Invoke-Idf fullclean
Invoke-Idf -D "PROJECT_VER=$ProjectVer" build

$descriptionPath = Join-Path "build" "project_description.json"
if (!(Test-Path $descriptionPath)) {{
    throw "Missing build/project_description.json after build"
}}

$description = Get-Content $descriptionPath -Raw | ConvertFrom-Json
if ($description.project_version -ne $ProjectVer) {{
    throw "Wrong project_version: expected $ProjectVer got $($description.project_version)"
}}

Write-Host "Verified project_version=$ProjectVer"

if ($NoFlash) {{
    exit 0
}}

Invoke-Idf -p $Port flash monitor
""",
    )

    _write_text(
        esp_dest / "build_flash_p3d_002.cmd",
        f"""@echo off
setlocal
set PORT=%1
if "%PORT%"=="" set PORT={default_port}
powershell -ExecutionPolicy Bypass -File "%~dp0build_flash_p3d_002.ps1" %PORT%
endlocal
""",
    )

    _write_text(
        esp_dest / "build_flash_p3d_002.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail

PORT="${{1:-/dev/ttyUSB0}}"
PROJECT_VER="${{PROJECT_VER:-{project_version}}}"
export PROJECT_VER

echo "PROJECT_VER=${{PROJECT_VER}}"
idf.py fullclean
idf.py -D "PROJECT_VER=${{PROJECT_VER}}" build

python3 - <<'PY'
import json
from pathlib import Path

expected = "{project_version}"
description = json.loads(Path("build/project_description.json").read_text())
actual = description.get("project_version")
if actual != expected:
    raise SystemExit(f"Wrong project_version: expected {{expected}} got {{actual}}")
print(f"Verified project_version={{actual}}")
PY

idf.py -p "${{PORT}}" flash monitor
""",
    )
    (esp_dest / "build_flash_p3d_002.sh").chmod(0o755)


def _create_archive(staging_root: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "w:gz") as tar:
        tar.add(staging_root / "esp_idf_demo", arcname="esp_idf_demo")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Create ESP compile-only source handoff package.")
    parser.add_argument("--source", type=Path, default=ROOT, help="Directory containing esp_idf_demo/")
    parser.add_argument("--output", type=Path, required=True, help="Output .tar.gz path")
    parser.add_argument("--project-version", default="v37-p3d-canary")
    parser.add_argument("--device-id", default="miaoban-v1p2-002")
    parser.add_argument("--wifi-ssid", default="GMT-G60")
    parser.add_argument("--server-base-url", default="http://106.54.240.51")
    parser.add_argument("--trigger-source", choices=tuple(TRIGGER_SOURCE_MACROS), default="button")
    parser.add_argument("--button-gpio", type=int, default=7)
    parser.add_argument("--default-port", default="COM3")
    parser.add_argument(
        "--include-managed-components",
        action="store_true",
        help="Include resolved ESP-IDF managed components for hardware handoff packages that must build without registry access.",
    )
    args = parser.parse_args()

    source_root = args.source.resolve()
    output = args.output.resolve()

    with tempfile.TemporaryDirectory(prefix="esp_compile_only_") as tmp:
        staging_root = Path(tmp)
        esp_dest = _copy_source_tree(
            source_root,
            staging_root,
            include_managed_components=args.include_managed_components,
        )
        _inject_p3d_canary_config(
            esp_dest,
            wifi_ssid=args.wifi_ssid,
            server_base_url=args.server_base_url,
            device_id=args.device_id,
            trigger_source=args.trigger_source,
            button_gpio=args.button_gpio,
        )
        _inject_hardware_entrypoints(
            esp_dest,
            project_version=args.project_version,
            device_id=args.device_id,
            default_port=args.default_port,
        )
        _create_archive(staging_root, output)

    print(f"path={output}")
    print(f"bytes={output.stat().st_size}")
    print(f"sha256={_sha256(output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
