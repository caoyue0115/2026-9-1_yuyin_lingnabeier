#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import shutil
import tarfile
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


EXCLUDED_DIRS = {
    ".git",
    "build",
    "managed_components",
    "__pycache__",
    "tmp",
    "data",
    "indices",
}


def _copy_source_tree(source_root: Path, staging_root: Path) -> Path:
    esp_source = source_root / "esp_idf_demo"
    if not esp_source.is_dir():
        raise SystemExit(f"missing esp_idf_demo directory under {source_root}")

    esp_dest = staging_root / "esp_idf_demo"

    def ignore(_: str, names: list[str]) -> set[str]:
        ignored = {name for name in names if name in EXCLUDED_DIRS}
        ignored.update(name for name in names if name.endswith(".pyc"))
        ignored.update(name for name in names if name.endswith(".bin"))
        ignored.update(name for name in names if name.startswith(".env"))
        return ignored

    shutil.copytree(esp_source, esp_dest, ignore=ignore, symlinks=False)
    return esp_dest


def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")


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

Write-Host "PROJECT_VER=$ProjectVer"
idf.py fullclean
idf.py -D "PROJECT_VER=$ProjectVer" build

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

idf.py -p $Port flash monitor
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
    parser.add_argument("--default-port", default="COM3")
    args = parser.parse_args()

    source_root = args.source.resolve()
    output = args.output.resolve()

    with tempfile.TemporaryDirectory(prefix="esp_compile_only_") as tmp:
        staging_root = Path(tmp)
        esp_dest = _copy_source_tree(source_root, staging_root)
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
