from __future__ import annotations

import argparse
import base64
import json
import queue
import sys
import time
from pathlib import Path

import dashscope
from dashscope.audio.qwen_tts_realtime.qwen_tts_realtime import AudioFormat, QwenTtsRealtime, QwenTtsRealtimeCallback

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.settings import settings


DEFAULT_MODEL = "qwen3-tts-vc-realtime-2026-01-15"


def _decode_audio_delta(event: dict) -> bytes:
    if not isinstance(event, dict):
        return b""
    if event.get("type") != "response.audio.delta":
        return b""
    delta = event.get("delta")
    if not delta:
        return b""
    try:
        return base64.b64decode(delta)
    except Exception:
        return b""


def _event_summary(event: dict) -> dict:
    summary = {"type": event.get("type")}
    if "session" in event and isinstance(event["session"], dict):
        summary["session_id"] = event["session"].get("id")
    if "response" in event and isinstance(event["response"], dict):
        summary["response_id"] = event["response"].get("id")
        summary["response_status"] = event["response"].get("status")
    if event.get("type") == "response.audio.delta":
        summary["delta_b64_len"] = len(event.get("delta") or "")
        summary["delta_bytes"] = len(_decode_audio_delta(event))
    if event.get("type") == "error":
        summary["error"] = event.get("error")
    return summary


class ProbeCallback(QwenTtsRealtimeCallback):
    def __init__(self) -> None:
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()

    def on_open(self) -> None:
        self.events.put(("open", None))

    def on_close(self, close_status_code, close_msg) -> None:
        self.events.put(
            (
                "close",
                {
                    "close_status_code": close_status_code,
                    "close_msg": close_msg,
                },
            )
        )

    def on_event(self, message: dict) -> None:
        self.events.put(("event", message))


def run_probe(
    text: str,
    model: str,
    voice: str,
    timeout_seconds: float,
    sample_rate: int,
    output_format: str,
    mode: str,
    instructions: str | None,
    save_raw: Path | None,
) -> int:
    callback = ProbeCallback()
    started = time.perf_counter()
    first_audio_delta_ms: int | None = None
    first_audio_delta_bytes: int | None = None
    observed_types: list[str] = []
    response_done: dict | None = None
    audio_bytes = bytearray()

    dashscope.api_key = settings.dashscope_api_key
    client = QwenTtsRealtime(model=model, callback=callback)
    client.connect()
    session_kwargs = {
        "voice": voice,
        "mode": mode,
        "response_format": AudioFormat.PCM_24000HZ_MONO_16BIT,
        "sample_rate": sample_rate,
        "audio_format": output_format,
        "language_type": settings.tts_language_type,
    }
    if instructions:
        session_kwargs["instructions"] = instructions
    client.update_session(**session_kwargs)
    client.append_text(text)
    if mode == "commit":
        client.commit()
    client.finish()

    deadline = time.perf_counter() + timeout_seconds
    while time.perf_counter() < deadline:
        remaining = max(0.1, deadline - time.perf_counter())
        try:
            item_type, payload = callback.events.get(timeout=remaining)
        except queue.Empty:
            break
        if item_type == "open":
            print(json.dumps({"event": "open"}, ensure_ascii=False))
            continue
        if item_type == "close":
            print(json.dumps({"event": "close", **(payload or {})}, ensure_ascii=False))
            continue
        if item_type != "event":
            continue
        event = payload if isinstance(payload, dict) else {}
        event_type = event.get("type")
        if event_type:
            observed_types.append(event_type)
        summary = _event_summary(event)
        summary["event"] = "sdk_event"
        summary["elapsed_ms"] = int(round((time.perf_counter() - started) * 1000))
        print(json.dumps(summary, ensure_ascii=False))
        if event_type == "response.audio.delta":
            audio_bytes.extend(_decode_audio_delta(event))
        if event_type == "response.audio.delta" and first_audio_delta_ms is None:
            first_audio_delta_ms = summary["elapsed_ms"]
            first_audio_delta_bytes = summary.get("delta_bytes", 0)
        if event_type == "response.done":
            response_done = event
            break

    client.close()
    if save_raw is not None and audio_bytes:
        save_raw.parent.mkdir(parents=True, exist_ok=True)
        save_raw.write_bytes(bytes(audio_bytes))
    print(
        json.dumps(
            {
                "event": "summary",
                "model": model,
                "voice": voice,
                "mode": mode,
                "instructions_enabled": bool(instructions),
                "sample_rate": sample_rate,
                "output_format": output_format,
                "saved_raw_path": str(save_raw) if save_raw is not None else None,
                "saved_raw_bytes": len(audio_bytes),
                "first_audio_delta_ms": first_audio_delta_ms,
                "first_audio_delta_bytes": first_audio_delta_bytes,
                "observed_types": observed_types,
                "response_done": _event_summary(response_done or {}),
            },
            ensure_ascii=False,
        )
    )
    return 0 if response_done else 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", default="什么是无相。")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--voice", default=settings.realtime_tts_voice or settings.tts_voice)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--sample-rate", type=int, default=24000)
    parser.add_argument("--output-format", default="pcm")
    parser.add_argument("--mode", default="server_commit", choices=["server_commit", "commit"])
    parser.add_argument("--instructions")
    parser.add_argument("--save-raw")
    args = parser.parse_args()

    if not settings.dashscope_api_key:
        raise SystemExit("missing dashscope api key")
    if not args.voice:
        raise SystemExit("missing realtime voice")

    raise SystemExit(
        run_probe(
            text=args.text,
            model=args.model,
            voice=args.voice,
            timeout_seconds=args.timeout,
            sample_rate=args.sample_rate,
            output_format=args.output_format,
            mode=args.mode,
            instructions=args.instructions,
            save_raw=Path(args.save_raw) if args.save_raw else None,
        )
    )


if __name__ == "__main__":
    main()
