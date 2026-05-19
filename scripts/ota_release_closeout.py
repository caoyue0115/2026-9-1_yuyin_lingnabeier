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
