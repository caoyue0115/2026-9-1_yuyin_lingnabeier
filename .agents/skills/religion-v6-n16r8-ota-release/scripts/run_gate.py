from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlparse


VERSION_RE = re.compile(r"v6-n16r8-\d+-ota-canary")
SHA256_RE = re.compile(r"[0-9a-fA-F]{64}")


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        raise ValueError("invalid arguments")


def build_parser() -> SafeArgumentParser:
    parser = SafeArgumentParser(
        description="Run the repository V1.0 N16R8 OTA gate with fixed safety bounds."
    )
    parser.add_argument("--artifact")
    parser.add_argument("--expected-sha256")
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--expected-release-id")
    parser.add_argument("--manifest-base-url")
    parser.add_argument(
        "--allowed-device-mode", choices=("update", "no-update"), default="update"
    )
    parser.add_argument("--log")
    parser.add_argument("--require-ota-success", action="store_true")
    return parser


def _reject(reason: str) -> int:
    print(f"gate_error={reason}", file=sys.stderr)
    return 2


def _validated_gate_args(args: list[str]) -> list[str] | None:
    try:
        parsed = build_parser().parse_args(args)
    except ValueError:
        _reject("invalid_arguments")
        return None

    if not VERSION_RE.fullmatch(parsed.expected_version):
        _reject("invalid_version")
        return None

    for name in ("artifact", "manifest_base_url", "log"):
        value = getattr(parsed, name)
        if value is not None and not value.strip():
            _reject(f"empty_{name}")
            return None

    if not any((parsed.artifact, parsed.manifest_base_url, parsed.log)):
        _reject("no_check_selected")
        return None

    if parsed.artifact:
        if not parsed.expected_sha256 or not SHA256_RE.fullmatch(parsed.expected_sha256):
            _reject("invalid_expected_sha256")
            return None
    elif parsed.expected_sha256:
        _reject("sha_without_artifact")
        return None

    if parsed.manifest_base_url:
        url = urlparse(parsed.manifest_base_url)
        if url.scheme not in {"http", "https"} or not url.netloc:
            _reject("invalid_manifest_base_url")
            return None
        if not parsed.artifact:
            _reject("manifest_requires_artifact")
            return None
        if not parsed.expected_release_id or not parsed.expected_release_id.strip():
            _reject("manifest_requires_release_id")
            return None
    elif parsed.allowed_device_mode != "update":
        _reject("device_mode_without_manifest")
        return None

    if parsed.log and not parsed.require_ota_success:
        _reject("log_requires_ota_success")
        return None
    if parsed.require_ota_success and not parsed.log:
        _reject("ota_success_without_log")
        return None

    delegated = ["--expected-version", parsed.expected_version]
    for option, value in (
        ("--artifact", parsed.artifact),
        ("--expected-sha256", parsed.expected_sha256),
        ("--expected-release-id", parsed.expected_release_id),
        ("--manifest-base-url", parsed.manifest_base_url),
        ("--log", parsed.log),
    ):
        if value is not None:
            delegated.extend((option, value))
    if parsed.allowed_device_mode != "update":
        delegated.extend(("--allowed-device-mode", parsed.allowed_device_mode))
    if parsed.require_ota_success:
        delegated.append("--require-ota-success")
    return delegated


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--self-test"]:
        print("output_policy=summary_only")
        return 0
    if any(arg in {"-h", "--help"} for arg in args):
        build_parser().print_help()
        return 0

    delegated = _validated_gate_args(args)
    if delegated is None:
        return 2

    repo_root = Path(__file__).resolve().parents[4]
    gate = repo_root / "scripts" / "v6_n16r8_release_gate.py"
    if not gate.is_file():
        return _reject("missing_gate")

    completed = subprocess.run(
        [sys.executable, str(gate), *delegated],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode == 0:
        print("gate_result=pass")
    else:
        print(f"gate_result=fail exit_code={completed.returncode}", file=sys.stderr)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
