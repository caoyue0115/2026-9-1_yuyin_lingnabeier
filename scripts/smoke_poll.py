from __future__ import annotations

import argparse
import os
import time
import wave
from pathlib import Path

import httpx

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8010")
DEVICE_ID = os.getenv("SMOKE_DEVICE_ID", "esp-demo-001")


def resolve_audio_path(cli_audio_path: str | None) -> str | None:
    return cli_audio_path or os.getenv("SMOKE_WAV_PATH")


def should_expect_success(audio_path: str | None, expect_success: bool | None) -> bool:
    if expect_success is not None:
        return expect_success
    env_value = os.getenv("EXPECT_ASR_SUCCESS")
    if env_value is not None:
        return env_value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(audio_path)


def load_audio_request(audio_path: str | None) -> tuple[bytes, dict[str, str]]:
    if not audio_path:
        return (
            b"\x00\x00" * 16000,
            {
                "content-type": "application/octet-stream",
                "x-device-id": DEVICE_ID,
                "x-sample-rate": "16000",
                "x-sample-width": "16",
                "x-channels": "1",
            },
        )

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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio_path", nargs="?")
    parser.add_argument("--expect-success", dest="expect_success", action="store_true")
    parser.add_argument("--allow-failure", dest="expect_success", action="store_false")
    parser.set_defaults(expect_success=None)
    args = parser.parse_args()

    audio_path = resolve_audio_path(args.audio_path)
    expect_success = should_expect_success(audio_path, args.expect_success)
    pcm, headers = load_audio_request(audio_path)

    submit = httpx.post(
        f"{BASE_URL}/api/v2/tasks",
        content=pcm,
        headers=headers,
        timeout=10,
    )
    submit.raise_for_status()
    task_id = submit.json()["task_id"]
    print(f"task_id={task_id}")
    for _ in range(20):
        status = httpx.get(f"{BASE_URL}/api/v2/tasks/{task_id}", timeout=10).json()
        print(status)
        if status["status"] == "done":
            return
        if status["status"] == "failed":
            if expect_success:
                raise SystemExit(f"ASR smoke task failed unexpectedly: {status}")
            return
        time.sleep(1)
    raise SystemExit("ASR smoke task did not finish within polling window")


if __name__ == "__main__":
    main()
