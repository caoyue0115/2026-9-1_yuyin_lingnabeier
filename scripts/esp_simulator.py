from __future__ import annotations

import argparse
import json
import os
import time
import wave
from pathlib import Path
from urllib.parse import urlparse

import httpx

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8010")
DEVICE_ID = os.getenv("ESP_DEVICE_ID", "esp32-s3-sim-001")


def load_pcm_request(audio_path: str) -> tuple[bytes, dict[str, str]]:
    path = Path(audio_path)
    with wave.open(str(path), "rb") as wav_file:
        frames = wav_file.readframes(wav_file.getnframes())
        headers = {
            "content-type": "application/octet-stream",
            "x-device-id": DEVICE_ID,
            "x-sample-rate": str(wav_file.getframerate()),
            "x-sample-width": str(wav_file.getsampwidth() * 8),
            "x-channels": str(wav_file.getnchannels()),
        }
    return frames, headers


def submit_task(audio_path: str, timeout: float = 10.0) -> dict:
    pcm, headers = load_pcm_request(audio_path)
    response = httpx.post(f"{BASE_URL}/api/v2/tasks", content=pcm, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.json()


def poll_task(task_id: str, interval_seconds: float = 1.0, max_polls: int = 30, timeout: float = 10.0) -> dict:
    for _ in range(max_polls):
        response = httpx.get(f"{BASE_URL}/api/v2/tasks/{task_id}", timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        if payload["status"] in {"done", "failed"}:
            return payload
        time.sleep(interval_seconds)
    raise TimeoutError(f"task {task_id} did not finish after {max_polls} polls")


def download_audio(audio_url: str, output_dir: str | None = None, timeout: float = 20.0) -> Path:
    response = httpx.get(audio_url, timeout=timeout)
    response.raise_for_status()
    target_dir = Path(output_dir or ".").resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = Path(urlparse(audio_url).path).name or "response.wav"
    target_path = target_dir / filename
    target_path.write_bytes(response.content)
    return target_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio_path")
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--max-polls", type=int, default=30)
    parser.add_argument("--download-audio", action="store_true")
    parser.add_argument("--output-dir")
    args = parser.parse_args()

    accepted = submit_task(args.audio_path)
    task_id = accepted["task_id"]
    print(json.dumps({"event": "accepted", "task_id": task_id}, ensure_ascii=False))

    result = poll_task(task_id, interval_seconds=args.poll_interval, max_polls=args.max_polls)
    summary = {
        "event": "finished",
        "task_id": task_id,
        "status": result["status"],
        "step": result.get("step"),
        "question_text": result.get("question_text"),
        "answer_text": result.get("answer_text"),
        "audio_url": result.get("audio_url"),
        "error_code": result.get("error_code"),
        "trace": result.get("trace"),
    }

    if args.download_audio and result.get("audio_url"):
        summary["downloaded_audio"] = str(download_audio(result["audio_url"], output_dir=args.output_dir))

    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if result["status"] == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
