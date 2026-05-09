from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import httpx

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


def build_start_control(*, run_asr: bool, run_full_chain: bool, asr_provider: str = "dashscope") -> str:
    return json.dumps(
        {
            "type": "start",
            "run_asr": run_asr,
            "run_full_chain": run_full_chain,
            "asr_provider": asr_provider,
        }
    )


def poll_session_until_terminal(
    session_id: str,
    *,
    base_url: str,
    interval_seconds: float,
    max_polls: int,
    timeout: float,
) -> dict:
    for _ in range(max_polls):
        response = httpx.get(f"{base_url}/api/v3/realtime/sessions/{session_id}", timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        if payload["status"] in {"done", "failed"}:
            return payload
        time.sleep(interval_seconds)
    raise TimeoutError(f"session {session_id} did not finish after {max_polls} polls")


def _client_elapsed_ms(started: float) -> int:
    return int(round((time.perf_counter() - started) * 1000))


def _add_client_timeline(
    payload: dict,
    *,
    client_first_frame_sent_ms: int | None,
    client_last_frame_sent_ms: int | None,
    client_end_sent_ms: int | None,
    client_done_received_ms: int | None,
) -> dict:
    output = dict(payload)
    output.update(
        {
            "client_stream_start_ms": 0,
            "client_first_frame_sent_ms": client_first_frame_sent_ms,
            "client_last_frame_sent_ms": client_last_frame_sent_ms,
            "client_end_sent_ms": client_end_sent_ms,
            "client_done_received_ms": client_done_received_ms,
        }
    )
    return output


def _print_server_payload(
    payload: dict,
    *,
    started: float,
    extra: dict | None = None,
    emit_trace: bool = True,
) -> None:
    if not emit_trace:
        return
    output = dict(payload)
    output["event"] = output.get("type")
    output["client_elapsed_ms"] = _client_elapsed_ms(started)
    if extra:
        output.update(extra)
    print(json.dumps(output, ensure_ascii=False))


def _recv_until_ack(websocket, *, started: float, frame_index: int, emit_trace: bool) -> dict:
    while True:
        raw_payload = websocket.recv()
        payload = json.loads(raw_payload)
        _print_server_payload(
            payload,
            started=started,
            extra={"frame_index": frame_index} if payload.get("type") == "ack" else None,
            emit_trace=emit_trace,
        )
        if payload.get("type") in {"ack", "error"}:
            return payload


def run_stream_smoke(
    audio_path: str | Path,
    *,
    base_url: str,
    frame_ms: int,
    realtime: bool,
    timeout: float,
    run_session_after_stream: bool,
    run_asr: bool,
    run_full_chain: bool,
    asr_provider: str,
    poll_interval: float,
    max_polls: int,
    status_timeout: float,
    emit_trace: bool = True,
) -> dict:
    from websocket import create_connection

    messages, local_metrics = build_stream_uplink_messages(audio_path, frame_ms=frame_ms)
    headers = build_stream_headers(
        frame_ms=frame_ms,
        original_pcm_bytes=int(local_metrics["uplink_pcm_bytes"] or 0),
    )
    url = _websocket_url(base_url)
    if emit_trace:
        print(
            json.dumps(
                {
                    "event": "start",
                    "url": url,
                    "frame_ms": frame_ms,
                    "realtime": realtime,
                    "asr_provider": asr_provider if run_asr or run_full_chain else None,
                    "local_uplink": local_metrics,
                },
                ensure_ascii=False,
            )
        )
    started = time.perf_counter()
    last_payload: dict | None = None
    client_first_frame_sent_ms: int | None = None
    client_last_frame_sent_ms: int | None = None
    client_end_sent_ms: int | None = None
    client_done_received_ms: int | None = None
    websocket = create_connection(
        url,
        timeout=timeout,
        header=[f"{key}: {value}" for key, value in headers.items()],
    )
    try:
        if run_asr or run_full_chain:
            websocket.send(
                build_start_control(
                    run_asr=run_asr or run_full_chain,
                    run_full_chain=run_full_chain,
                    asr_provider=asr_provider,
                )
            )
        for frame_index, message in enumerate(messages):
            if client_first_frame_sent_ms is None:
                client_first_frame_sent_ms = _client_elapsed_ms(started)
            websocket.send_binary(message)
            client_last_frame_sent_ms = _client_elapsed_ms(started)
            ack = _recv_until_ack(websocket, started=started, frame_index=frame_index, emit_trace=emit_trace)
            last_payload = ack
            if ack.get("type") == "error":
                client_done_received_ms = _client_elapsed_ms(started)
                return _add_client_timeline(
                    ack,
                    client_first_frame_sent_ms=client_first_frame_sent_ms,
                    client_last_frame_sent_ms=client_last_frame_sent_ms,
                    client_end_sent_ms=client_end_sent_ms,
                    client_done_received_ms=client_done_received_ms,
                )
            if realtime:
                time.sleep(frame_ms / 1000)

        stream_done_at = time.perf_counter()
        client_end_sent_ms = _client_elapsed_ms(started)
        websocket.send(
            json.dumps(
                {
                    "type": "end",
                    "client_stream_duration_ms": int(round((stream_done_at - started) * 1000)),
                    "run_session_after_stream": run_session_after_stream,
                    "run_full_chain": run_full_chain,
                }
            )
        )
        while True:
            raw_payload = websocket.recv()
            payload = json.loads(raw_payload)
            if payload.get("type") in {"done", "error"}:
                client_done_received_ms = _client_elapsed_ms(started)
                payload = _add_client_timeline(
                    payload,
                    client_first_frame_sent_ms=client_first_frame_sent_ms,
                    client_last_frame_sent_ms=client_last_frame_sent_ms,
                    client_end_sent_ms=client_end_sent_ms,
                    client_done_received_ms=client_done_received_ms,
                )
            _print_server_payload(payload, started=started, emit_trace=emit_trace)
            last_payload = payload
            if payload.get("type") in {"done", "error"}:
                break
    finally:
        websocket.close()

    if last_payload is None:
        raise RuntimeError("stream ended without server payload")
    if run_full_chain and last_payload.get("type") == "done" and last_payload.get("session_id"):
        status = poll_session_until_terminal(
            last_payload["session_id"],
            base_url=base_url,
            interval_seconds=poll_interval,
            max_polls=max_polls,
            timeout=status_timeout,
        )
        if emit_trace:
            print(
                json.dumps(
                    {
                        "event": "status",
                        "session_id": status["session_id"],
                        "status": status["status"],
                        "step": status.get("step"),
                        "final_reason": status.get("final_reason"),
                        "question_text": status.get("question_text"),
                        "answer_text": status.get("answer_text"),
                        "error_code": status.get("error_code"),
                        "error_message": status.get("error_message"),
                        "trace": status.get("trace"),
                    },
                    ensure_ascii=False,
                )
            )
        last_payload = dict(last_payload)
        last_payload["session_status"] = status
        if status["status"] == "failed":
            last_payload["type"] = "error"
            last_payload["error_code"] = status.get("error_code")
    return last_payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio_path")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--frame-ms", type=int, default=60)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--status-timeout", type=float, default=10.0)
    parser.add_argument("--poll-interval", type=float, default=0.3)
    parser.add_argument("--max-polls", type=int, default=80)
    parser.add_argument("--run-session-after-stream", action="store_true")
    parser.add_argument("--run-asr", action="store_true")
    parser.add_argument("--run-full-chain", action="store_true")
    parser.add_argument("--asr-provider", choices=["dashscope", "volcengine"], default="dashscope")
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
        run_asr=args.run_asr,
        run_full_chain=args.run_full_chain,
        asr_provider=args.asr_provider,
        poll_interval=args.poll_interval,
        max_polls=args.max_polls,
        status_timeout=args.status_timeout,
    )
    if final_payload.get("type") == "error":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
