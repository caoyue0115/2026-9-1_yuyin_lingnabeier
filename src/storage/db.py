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


def sqlite_ok() -> bool:
    try:
        conn = connect()
        conn.execute("SELECT 1").fetchone()
        conn.close()
        return True
    except Exception:
        return False

