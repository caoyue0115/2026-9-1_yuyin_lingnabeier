from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.settings import settings
from src.storage.files import ensure_data_dirs


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    ensure_data_dirs()
    conn = sqlite3.connect(settings.sqlite_file)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = connect()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                device_id TEXT NOT NULL,
                status TEXT NOT NULL,
                step TEXT,
                progress REAL NOT NULL DEFAULT 0,
                input_wav_path TEXT,
                output_audio_path TEXT,
                question_text TEXT,
                answer_text TEXT,
                references_json TEXT,
                trace_json TEXT,
                tts_status TEXT,
                error_code TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ota_releases (
                release_id TEXT PRIMARY KEY,
                target TEXT NOT NULL,
                version TEXT NOT NULL,
                artifact_name TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                size INTEGER NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                force INTEGER NOT NULL DEFAULT 0,
                min_version TEXT,
                board TEXT,
                hw_rev TEXT,
                priority INTEGER NOT NULL DEFAULT 100,
                notes TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ota_release_devices (
                release_id TEXT NOT NULL,
                device_id TEXT NOT NULL,
                PRIMARY KEY (release_id, device_id),
                FOREIGN KEY (release_id) REFERENCES ota_releases(release_id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ota_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                target TEXT NOT NULL,
                from_version TEXT,
                to_version TEXT,
                release_id TEXT,
                stage TEXT NOT NULL,
                ok INTEGER NOT NULL,
                error_code TEXT,
                error_message TEXT,
                free_heap INTEGER,
                rssi INTEGER,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def create_task(task_id: str, device_id: str, input_wav_path: str) -> str:
    conn = connect()
    try:
        ts = now_iso()
        conn.execute(
            """
            INSERT INTO tasks(
                task_id, device_id, status, step, progress, input_wav_path, created_at, updated_at
            )
            VALUES (?, ?, 'accepted', 'queued', 0.0, ?, ?, ?)
            """,
            (task_id, device_id, input_wav_path, ts, ts),
        )
        conn.commit()
        return ts
    finally:
        conn.close()


def fetch_task(task_id: str) -> dict[str, Any] | None:
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_task_status(task_id: str, status: str, step: str, progress: float) -> None:
    conn = connect()
    try:
        conn.execute(
            "UPDATE tasks SET status = ?, step = ?, progress = ?, updated_at = ? WHERE task_id = ?",
            (status, step, progress, now_iso(), task_id),
        )
        conn.commit()
    finally:
        conn.close()


def mark_task_done(
    task_id: str,
    question_text: str,
    answer_text: str,
    output_audio_path: str | None,
    references: list[dict[str, Any]],
    trace: dict[str, Any],
    tts_status: str | None,
) -> None:
    conn = connect()
    try:
        conn.execute(
            """
            UPDATE tasks
            SET status = 'done',
                step = 'done',
                progress = 1.0,
                question_text = ?,
                answer_text = ?,
                output_audio_path = ?,
                references_json = ?,
                trace_json = ?,
                tts_status = ?,
                updated_at = ?
            WHERE task_id = ?
            """,
            (
                question_text,
                answer_text,
                output_audio_path,
                json.dumps(references, ensure_ascii=False),
                json.dumps(trace, ensure_ascii=False),
                tts_status,
                now_iso(),
                task_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def mark_task_failed(task_id: str, step: str, error_code: str, error_message: str, trace: dict[str, Any]) -> None:
    conn = connect()
    try:
        conn.execute(
            """
            UPDATE tasks
            SET status = 'failed',
                step = ?,
                error_code = ?,
                error_message = ?,
                trace_json = ?,
                updated_at = ?
            WHERE task_id = ?
            """,
            (step, error_code, error_message, json.dumps(trace, ensure_ascii=False), now_iso(), task_id),
        )
        conn.commit()
    finally:
        conn.close()


def create_ota_release(
    *,
    release_id: str,
    target: str,
    version: str,
    artifact_name: str,
    sha256: str,
    size: int,
    min_version: str | None = None,
    device_ids: list[str] | None = None,
    enabled: bool = True,
    force: bool = False,
    board: str | None = None,
    hw_rev: str | None = None,
    priority: int = 100,
    notes: str | None = None,
) -> None:
    conn = connect()
    try:
        ts = now_iso()
        conn.execute(
            """
            INSERT INTO ota_releases(
                release_id, target, version, artifact_name, sha256, size, enabled, force,
                min_version, board, hw_rev, priority, notes, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                release_id,
                target,
                version,
                artifact_name,
                sha256,
                size,
                1 if enabled else 0,
                1 if force else 0,
                min_version,
                board,
                hw_rev,
                priority,
                notes,
                ts,
            ),
        )
        for device_id in device_ids or []:
            conn.execute(
                "INSERT INTO ota_release_devices(release_id, device_id) VALUES (?, ?)",
                (release_id, device_id),
            )
        conn.commit()
    finally:
        conn.close()


def list_ota_release_candidates() -> list[dict[str, Any]]:
    conn = connect()
    try:
        rows = conn.execute(
            """
            SELECT
                release_id, target, version, artifact_name, sha256, size, enabled, force,
                min_version, board, hw_rev, priority, notes, created_at
            FROM ota_releases
            ORDER BY priority ASC, created_at ASC, release_id ASC
            """
        ).fetchall()
        releases = [dict(row) for row in rows]
        for release in releases:
            device_rows = conn.execute(
                "SELECT device_id FROM ota_release_devices WHERE release_id = ? ORDER BY device_id",
                (release["release_id"],),
            ).fetchall()
            release["device_ids"] = [row["device_id"] for row in device_rows]
        return releases
    finally:
        conn.close()


def has_successful_ota_report_stage(device_id: str, release_id: str, stages: list[str]) -> bool:
    if not stages:
        return False
    conn = connect()
    try:
        placeholders = ", ".join("?" for _ in stages)
        row = conn.execute(
            f"""
            SELECT 1
            FROM ota_reports
            WHERE device_id = ?
              AND release_id = ?
              AND ok = 1
              AND stage IN ({placeholders})
            LIMIT 1
            """,
            (device_id, release_id, *stages),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def record_ota_report(payload: dict[str, Any]) -> str:
    conn = connect()
    try:
        ts = now_iso()
        conn.execute(
            """
            INSERT INTO ota_reports(
                device_id, target, from_version, to_version, release_id, stage, ok,
                error_code, error_message, free_heap, rssi, payload_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["device_id"],
                payload["target"],
                payload.get("from_version"),
                payload.get("to_version"),
                payload.get("release_id"),
                payload["stage"],
                1 if payload["ok"] else 0,
                payload.get("error_code"),
                payload.get("error_message"),
                payload.get("free_heap"),
                payload.get("rssi"),
                json.dumps(payload, ensure_ascii=False),
                ts,
            ),
        )
        conn.commit()
        return ts
    finally:
        conn.close()


def fetch_latest_ota_report(device_id: str) -> dict[str, Any] | None:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM ota_reports WHERE device_id = ? ORDER BY id DESC LIMIT 1",
            (device_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def sqlite_ok() -> bool:
    try:
        conn = connect()
        conn.execute("SELECT 1").fetchone()
        conn.close()
        return True
    except Exception:
        return False
