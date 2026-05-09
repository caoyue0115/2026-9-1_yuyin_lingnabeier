from __future__ import annotations

import argparse
import json
import os
import sys
import time
import wave
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.providers.opus import encode_pcm_stream_to_framed_opus, pack_framed_v1_packets

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8010")
DEVICE_ID = os.getenv("ESP_DEVICE_ID", "pc-opus-uplink-sim-001")
SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH_BYTES = 2
FRAME_DURATION_MS = 60
BITRATE = 24000


def load_wav_pcm(audio_path: str | Path) -> bytes:
    path = Path(audio_path)
    with wave.open(str(path), "rb") as wav_file:
        sample_rate = wav_file.getframerate()
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        if sample_rate != SAMPLE_RATE or channels != CHANNELS or sample_width != SAMPLE_WIDTH_BYTES:
            raise ValueError("expected 16kHz 16-bit mono WAV")
        return wav_file.readframes(wav_file.getnframes())


def build_opus_uplink_request(audio_path: str | Path) -> tuple[bytes, dict[str, str], dict[str, int | float | None]]:
    pcm = load_wav_pcm(audio_path)
    inner_packets = list(
        encode_pcm_stream_to_framed_opus(
            [pcm],
            sample_rate=SAMPLE_RATE,
            channels=CHANNELS,
            frame_duration_ms=FRAME_DURATION_MS,
            bitrate=BITRATE,
        )
    )
    body = b"".join(pack_framed_v1_packets(inner_packets))
    opus_bytes = sum(max(0, len(packet) - 2) for packet in inner_packets)
    compression_ratio = round(len(pcm) / opus_bytes, 3) if opus_bytes > 0 else None
    metrics = {
        "uplink_opus_bytes": opus_bytes,
        "uplink_pcm_bytes": len(pcm),
        "uplink_compression_ratio": compression_ratio,
        "uplink_frame_count": len(inner_packets),
        "reconstructed_audio_ms": int(round((len(pcm) / (SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH_BYTES)) * 1000)),
    }
    headers = {
        "content-type": "application/octet-stream",
        "x-device-id": DEVICE_ID,
        "x-audio-packetization": "framed-v1",
        "x-audio-format": "opus",
        "x-opus-sample-rate": str(SAMPLE_RATE),
        "x-opus-channels": str(CHANNELS),
        "x-opus-frame-duration-ms": str(FRAME_DURATION_MS),
        "x-original-pcm-bytes": str(len(pcm)),
    }
    return body, headers, metrics


def submit_opus_session(audio_path: str | Path, *, timeout: float = 10.0) -> tuple[dict, dict]:
    body, headers, local_metrics = build_opus_uplink_request(audio_path)
    started = time.perf_counter()
    response = httpx.post(
        f"{BASE_URL}/api/v5/realtime/opus-sessions",
        content=body,
        headers=headers,
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    payload["submit_ms"] = int(round((time.perf_counter() - started) * 1000))
    return payload, local_metrics


def poll_session_until_terminal(
    session_id: str,
    *,
    interval_seconds: float = 0.3,
    max_polls: int = 40,
    timeout: float = 10.0,
) -> dict:
    for _ in range(max_polls):
        response = httpx.get(f"{BASE_URL}/api/v3/realtime/sessions/{session_id}", timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        if payload["status"] in {"done", "failed"}:
            return payload
        time.sleep(interval_seconds)
    raise TimeoutError(f"session {session_id} did not finish after {max_polls} polls")


def main() -> None:
    global BASE_URL

    parser = argparse.ArgumentParser()
    parser.add_argument("audio_path")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--submit-timeout", type=float, default=10.0)
    parser.add_argument("--status-timeout", type=float, default=10.0)
    parser.add_argument("--poll-interval", type=float, default=0.3)
    parser.add_argument("--max-polls", type=int, default=40)
    args = parser.parse_args()

    BASE_URL = args.base_url.rstrip("/")

    accepted, local_metrics = submit_opus_session(args.audio_path, timeout=args.submit_timeout)
    print(
        json.dumps(
            {
                "event": "submit",
                "session_id": accepted["session_id"],
                "status": accepted["status"],
                "submit_ms": accepted["submit_ms"],
                "audio_stream_url": accepted["audio_stream_url"],
                "local_uplink": local_metrics,
            },
            ensure_ascii=False,
        )
    )

    status = poll_session_until_terminal(
        accepted["session_id"],
        interval_seconds=args.poll_interval,
        max_polls=args.max_polls,
        timeout=args.status_timeout,
    )
    print(
        json.dumps(
            {
                "event": "status",
                "session_id": status["session_id"],
                "status": status["status"],
                "step": status.get("step"),
                "final_reason": status.get("final_reason"),
                "question_text": status.get("question_text"),
                "error_code": status.get("error_code"),
                "error_message": status.get("error_message"),
                "trace": status.get("trace"),
            },
            ensure_ascii=False,
        )
    )
    if status["status"] == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
