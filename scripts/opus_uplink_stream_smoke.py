from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.opus_uplink_smoke import (
    BITRATE,
    CHANNELS,
    DEVICE_ID,
    SAMPLE_RATE,
    SAMPLE_WIDTH_BYTES,
    load_wav_pcm,
)
from src.providers.opus import encode_pcm_stream_to_framed_opus, pack_framed_v1_packets

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8010")


def _websocket_url(base_url: str) -> str:
    parsed = urlparse(base_url.rstrip("/"))
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunparse((scheme, parsed.netloc, "/api/v5/realtime/opus-stream", "", "", ""))


def build_stream_uplink_messages(
    audio_path: str | Path,
    *,
    frame_ms: int,
) -> tuple[list[bytes], dict[str, int | float | None]]:
    pcm = load_wav_pcm(audio_path)
    inner_packets = list(
        encode_pcm_stream_to_framed_opus(
            [pcm],
            sample_rate=SAMPLE_RATE,
            channels=CHANNELS,
            frame_duration_ms=frame_ms,
            bitrate=BITRATE,
        )
    )
    messages = list(pack_framed_v1_packets(inner_packets))
    opus_bytes = sum(max(0, len(packet) - 2) for packet in inner_packets)
    metrics = {
        "uplink_opus_bytes": opus_bytes,
        "uplink_pcm_bytes": len(pcm),
        "uplink_compression_ratio": round(len(pcm) / opus_bytes, 3) if opus_bytes > 0 else None,
        "uplink_frame_count": len(inner_packets),
        "reconstructed_audio_ms": int(round((len(pcm) / (SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH_BYTES)) * 1000)),
    }
    return messages, metrics


def build_stream_headers(*, frame_ms: int, original_pcm_bytes: int) -> dict[str, str]:
    return {
        "x-device-id": DEVICE_ID,
        "x-audio-packetization": "framed-v1",
        "x-audio-format": "opus",
        "x-opus-sample-rate": str(SAMPLE_RATE),
        "x-opus-channels": str(CHANNELS),
        "x-opus-frame-duration-ms": str(frame_ms),
        "x-original-pcm-bytes": str(original_pcm_bytes),
    }


def run_stream_smoke(
    audio_path: str | Path,
    *,
    base_url: str,
    frame_ms: int,
    realtime: bool,
    timeout: float,
    run_session_after_stream: bool,
) -> dict:
    from websocket import create_connection

    messages, local_metrics = build_stream_uplink_messages(audio_path, frame_ms=frame_ms)
    headers = build_stream_headers(
        frame_ms=frame_ms,
        original_pcm_bytes=int(local_metrics["uplink_pcm_bytes"] or 0),
    )
    url = _websocket_url(base_url)
    print(
        json.dumps(
            {
                "event": "start",
                "url": url,
                "frame_ms": frame_ms,
                "realtime": realtime,
                "local_uplink": local_metrics,
            },
            ensure_ascii=False,
        )
    )
    started = time.perf_counter()
    last_payload: dict | None = None
    websocket = create_connection(
        url,
        timeout=timeout,
        header=[f"{key}: {value}" for key, value in headers.items()],
    )
    try:
        for frame_index, message in enumerate(messages):
            websocket.send_binary(message)
            raw_ack = websocket.recv()
            ack = json.loads(raw_ack)
            ack["event"] = "ack"
            ack["frame_index"] = frame_index
            ack["client_elapsed_ms"] = int(round((time.perf_counter() - started) * 1000))
            print(json.dumps(ack, ensure_ascii=False))
            last_payload = ack
            if ack.get("type") == "error":
                break
            if realtime:
                time.sleep(frame_ms / 1000)

        stream_done_at = time.perf_counter()
        websocket.send(
            json.dumps(
                {
                    "type": "end",
                    "client_stream_duration_ms": int(round((stream_done_at - started) * 1000)),
                    "run_session_after_stream": run_session_after_stream,
                }
            )
        )
        while True:
            raw_payload = websocket.recv()
            payload = json.loads(raw_payload)
            payload["event"] = payload.get("type")
            payload["client_elapsed_ms"] = int(round((time.perf_counter() - started) * 1000))
            print(json.dumps(payload, ensure_ascii=False))
            last_payload = payload
            if payload.get("type") in {"done", "error"}:
                break
    finally:
        websocket.close()

    if last_payload is None:
        raise RuntimeError("stream ended without server payload")
    return last_payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio_path")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--frame-ms", type=int, default=60)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--run-session-after-stream", action="store_true")
    parser.add_argument("--realtime", dest="realtime", action="store_true")
    parser.add_argument("--no-realtime", dest="realtime", action="store_false")
    parser.set_defaults(realtime=True)
    args = parser.parse_args()

    final_payload = run_stream_smoke(
        args.audio_path,
        base_url=args.base_url.rstrip("/"),
        frame_ms=args.frame_ms,
        realtime=args.realtime,
        timeout=args.timeout,
        run_session_after_stream=args.run_session_after_stream,
    )
    if final_payload.get("type") == "error":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
