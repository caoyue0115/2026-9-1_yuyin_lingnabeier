from __future__ import annotations

from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory


FOCUSED_TESTS = (
    "tests/test_repo_ota_skill.py",
    "tests/test_v6_n16r8_release_gate.py",
    "tests/test_esp_assets.py",
    "tests/test_ota_release_cli.py",
    "tests/test_ota_release_closeout_cli.py",
    "tests/test_ota_api.py",
)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[4]
    test_paths = [str(repo_root / path) for path in FOCUSED_TESTS]
    with TemporaryDirectory(prefix="repo-ota-tests-") as isolated_cwd:
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--tb=no", *test_paths],
            cwd=isolated_cwd,
            capture_output=True,
            text=True,
            check=False,
        )
    if completed.returncode == 0:
        print("focused_tests=pass")
    else:
        print(
            f"focused_tests=fail exit_code={completed.returncode}", file=sys.stderr
        )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
