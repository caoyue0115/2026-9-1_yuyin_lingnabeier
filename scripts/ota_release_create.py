from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.settings import settings
from src.storage import db as storage_db


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_device_ids(repeated: list[str], comma_separated: str | None) -> list[str]:
    values: list[str] = []
    values.extend(repeated)
    if comma_separated:
        values.extend(part.strip() for part in comma_separated.split(","))
    clean = [value for value in values if value]
    return sorted(dict.fromkeys(clean))


def _artifact_under_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _fail(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create an OTA release row for an existing artifact.")
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--artifact", required=True, help="Path to an existing artifact under ota_artifact_dir")
    parser.add_argument("--target", default="esp32s3")
    parser.add_argument("--device-id", action="append", default=[])
    parser.add_argument("--device-ids")
    parser.add_argument("--min-version")
    parser.add_argument("--board")
    parser.add_argument("--hw-rev")
    parser.add_argument("--priority", type=int, default=100)
    parser.add_argument("--notes")
    parser.add_argument("--disabled", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    artifact_root = settings.ota_artifact_path.resolve()
    artifact_path = Path(args.artifact).expanduser().resolve()
    if not artifact_path.is_file():
        return _fail(f"artifact is not a file: {artifact_path}")
    if not _artifact_under_root(artifact_path, artifact_root):
        return _fail(f"artifact must be under ota_artifact_dir: {artifact_root}")

    device_ids = _parse_device_ids(args.device_id, args.device_ids)
    if not device_ids:
        return _fail("at least one --device-id or --device-ids value is required")

    storage_db.init_db()
    storage_db.create_ota_release(
        release_id=args.release_id,
        target=args.target,
        version=args.version,
        artifact_name=artifact_path.name,
        sha256=_sha256_file(artifact_path),
        size=artifact_path.stat().st_size,
        min_version=args.min_version,
        device_ids=device_ids,
        enabled=not args.disabled,
        force=args.force,
        board=args.board,
        hw_rev=args.hw_rev,
        priority=args.priority,
        notes=args.notes,
    )
    print(f"release_id={args.release_id}")
    print(f"artifact={artifact_path.name}")
    print(f"bytes={artifact_path.stat().st_size}")
    print(f"sha256={_sha256_file(artifact_path)}")
    print(f"devices={','.join(device_ids)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
