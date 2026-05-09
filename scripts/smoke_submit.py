from __future__ import annotations

import argparse
import os
import wave
from pathlib import Path

import httpx

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8010")
DEVICE_ID = os.getenv("SMOKE_DEVICE_ID", "esp-demo-001")


def resolve_audio_path(cli_audio_path: str | None) -> str | None:
    return cli_audio_path or os.getenv("SMOKE_WAV_PATH")


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
    args = parser.parse_args()

    pcm, headers = load_audio_request(resolve_audio_path(args.audio_path))
    resp = httpx.post(
        f"{BASE_URL}/api/v2/tasks",
        content=pcm,
        headers=headers,
        timeout=10,
    )
    print(resp.status_code)
    print(resp.text)


if __name__ == "__main__":
    main()
