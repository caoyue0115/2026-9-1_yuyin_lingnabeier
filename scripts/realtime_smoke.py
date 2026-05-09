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
STREAM_ACCEPT_AUDIO_FORMATS = "opus,pcm"


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


def submit_session(audio_path: str, timeout: float = 10.0) -> dict:
    pcm, headers = load_pcm_request(audio_path)
    response = httpx.post(f"{BASE_URL}/api/v3/realtime/sessions", content=pcm, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.json()


def poll_session_until_terminal(
    session_id: str,
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


def resolve_audio_stream_url(audio_stream_url: str) -> str:
    parsed_base = urlparse(BASE_URL)
    parsed_audio = urlparse(audio_stream_url)
    return f"{parsed_base.scheme}://{parsed_base.netloc}{parsed_audio.path}"


def build_stream_request_headers() -> dict[str, str]:
    return {"X-Accept-Audio-Format": STREAM_ACCEPT_AUDIO_FORMATS}


def _parse_framed_packets(buffer: bytearray) -> list[tuple[int, bytes]]:
    packets: list[tuple[int, bytes]] = []
    offset = 0
    while len(buffer) - offset >= 8:
        seq = int.from_bytes(buffer[offset : offset + 4], "big")
        payload_len = int.from_bytes(buffer[offset + 4 : offset + 8], "big")
        frame_len = 8 + payload_len
        if len(buffer) - offset < frame_len:
            break
        payload_start = offset + 8
        packets.append((seq, bytes(buffer[payload_start : payload_start + payload_len])))
        offset += frame_len
    if offset > 0:
        del buffer[:offset]
    return packets


def _audio_byte_rate(headers: dict[str, str | None]) -> int:
    sample_rate = int(headers.get("sample_rate") or 16000)
    sample_width_bits = int(headers.get("sample_width") or 16)
    channels = int(headers.get("channels") or 1)
    return sample_rate * (sample_width_bits // 8) * channels


def _virtual_player_stats(
    arrivals: list[tuple[float, int]],
    *,
    byte_rate: int,
    prebuffer_bytes: int,
) -> dict:
    if not arrivals or byte_rate <= 0:
        return {
            "prebuffer_bytes": prebuffer_bytes,
            "playback_start_ms": None,
            "underrun_count": 0,
            "underrun_ms": 0,
            "min_buffer_bytes": 0,
            "max_buffer_bytes": 0,
        }

    playing = False
    playback_start_ms: int | None = None
    buffer_bytes = 0.0
    min_buffer_bytes = 0.0
    max_buffer_bytes = 0.0
    underrun_count = 0
    underrun_ms = 0.0
    last_time = arrivals[0][0]

    for arrived_at, chunk_bytes in arrivals:
        if playing:
            elapsed_seconds = max(0.0, arrived_at - last_time)
            bytes_to_consume = elapsed_seconds * byte_rate
            if bytes_to_consume > buffer_bytes:
                underrun_count += 1
                underrun_ms += ((bytes_to_consume - buffer_bytes) / byte_rate) * 1000.0
                buffer_bytes = 0.0
            else:
                buffer_bytes -= bytes_to_consume
        buffer_bytes += chunk_bytes
        if not playing and buffer_bytes >= prebuffer_bytes:
            playing = True
            playback_start_ms = int(round(arrived_at * 1000))
        min_buffer_bytes = min(min_buffer_bytes, buffer_bytes)
        max_buffer_bytes = max(max_buffer_bytes, buffer_bytes)
        last_time = arrived_at

    return {
        "prebuffer_bytes": prebuffer_bytes,
        "playback_start_ms": playback_start_ms,
        "underrun_count": underrun_count,
        "underrun_ms": int(round(underrun_ms)),
        "min_buffer_bytes": int(round(min_buffer_bytes)),
        "max_buffer_bytes": int(round(max_buffer_bytes)),
    }


def stream_audio_metrics(
    audio_stream_url: str,
    timeout: float = 15.0,
    virtual_player_prebuffer_bytes: int = 8192,
) -> dict:
    started = time.perf_counter()
    with httpx.stream(
        "GET",
        resolve_audio_stream_url(audio_stream_url),
        headers=build_stream_request_headers(),
        timeout=timeout,
    ) as response:
        response.raise_for_status()
        first_chunk = b""
        total_bytes = 0
        chunk_count = 0
        arrivals: list[tuple[float, int]] = []
        packet_count = 0
        seq_gap_count = 0
        expected_seq: int | None = None
        audio_format = response.headers.get("X-Audio-Format") or "pcm"
        audio_packetization = response.headers.get("X-Audio-Packetization") or "legacy"
        framed_buffer = bytearray()
        for chunk in response.iter_bytes():
            if not chunk:
                continue
            now = time.perf_counter()
            elapsed_seconds = now - started
            if audio_packetization == "framed-v1":
                framed_buffer.extend(chunk)
                for seq, payload in _parse_framed_packets(framed_buffer):
                    if not first_chunk:
                        first_chunk = payload
                    if expected_seq is not None and seq != expected_seq:
                        seq_gap_count += 1
                    expected_seq = seq + 1
                    packet_count += 1
                    total_bytes += len(payload)
                    chunk_count += 1
                    arrivals.append((elapsed_seconds, len(payload)))
            else:
                if not first_chunk:
                    first_chunk = chunk
                total_bytes += len(chunk)
                chunk_count += 1
                arrivals.append((elapsed_seconds, len(chunk)))
        finished = time.perf_counter()
        gaps_ms = [
            int(round((arrivals[index][0] - arrivals[index - 1][0]) * 1000))
            for index in range(1, len(arrivals))
        ]
        audio_headers = {
            "sample_rate": response.headers.get("X-Audio-Sample-Rate"),
            "sample_width": response.headers.get("X-Audio-Sample-Width"),
            "channels": response.headers.get("X-Audio-Channels"),
            "endian": response.headers.get("X-Audio-Endian"),
        }
        byte_rate = _audio_byte_rate(audio_headers)
        stream_elapsed_ms = int(round((finished - started) * 1000))
        audio_duration_ms = int(round((total_bytes / byte_rate) * 1000)) if byte_rate > 0 else 0
        return {
            "http_status": response.status_code,
            "first_chunk_bytes": len(first_chunk),
            "first_chunk_local_ms": int(round(arrivals[0][0] * 1000)) if arrivals else None,
            "audio_format": audio_format,
            "audio_packetization": audio_packetization,
            "audio_headers": audio_headers,
            "chunk_count": chunk_count,
            "packet_count": packet_count if audio_packetization == "framed-v1" else chunk_count,
            "seq_gap_count": seq_gap_count,
            "total_audio_bytes": total_bytes,
            "byte_rate": byte_rate,
            "audio_duration_ms": audio_duration_ms,
            "stream_elapsed_ms": stream_elapsed_ms,
            "production_ratio": round(audio_duration_ms / stream_elapsed_ms, 3) if stream_elapsed_ms > 0 else None,
            "max_inter_chunk_gap_ms": max(gaps_ms) if gaps_ms else 0,
            "avg_inter_chunk_gap_ms": int(round(sum(gaps_ms) / len(gaps_ms))) if gaps_ms else 0,
            "virtual_player": _virtual_player_stats(
                arrivals,
                byte_rate=byte_rate,
                prebuffer_bytes=virtual_player_prebuffer_bytes,
            ),
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio_path")
    parser.add_argument(
        "--stream-mode",
        choices=("after_done", "immediate"),
        default="after_done",
        help="after_done measures buffered download speed; immediate simulates the ESP opening /audio right after POST.",
    )
    parser.add_argument("--poll-interval", type=float, default=0.3)
    parser.add_argument("--max-polls", type=int, default=40)
    parser.add_argument("--submit-timeout", type=float, default=10.0)
    parser.add_argument("--status-timeout", type=float, default=10.0)
    parser.add_argument("--audio-timeout", type=float, default=15.0)
    parser.add_argument("--virtual-player-prebuffer-bytes", type=int, default=8192)
    args = parser.parse_args()

    submit_started = time.perf_counter()
    accepted = submit_session(args.audio_path, timeout=args.submit_timeout)
    print(
        json.dumps(
            {
                "event": "submit",
                "session_id": accepted["session_id"],
                "status": accepted["status"],
                "submit_ms": int(round((time.perf_counter() - submit_started) * 1000)),
                "audio_stream_url": accepted["audio_stream_url"],
            },
            ensure_ascii=False,
        )
    )

    if args.stream_mode == "immediate":
        audio = stream_audio_metrics(
            accepted["audio_stream_url"],
            timeout=args.audio_timeout,
            virtual_player_prebuffer_bytes=args.virtual_player_prebuffer_bytes,
        )
        audio["event"] = "audio"
        audio["session_id"] = accepted["session_id"]
        audio["stream_mode"] = args.stream_mode
        print(json.dumps(audio, ensure_ascii=False))

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
                "error_code": status.get("error_code"),
                "error_message": status.get("error_message"),
                "trace": status.get("trace"),
            },
            ensure_ascii=False,
        )
    )

    if status["status"] == "failed":
        print(
            json.dumps(
                {
                    "event": "audio_skipped",
                    "session_id": accepted["session_id"],
                    "reason": "session_failed",
                    "error_code": status.get("error_code"),
                    "error_message": status.get("error_message"),
                },
                ensure_ascii=False,
            )
        )
        raise SystemExit(1)

    if args.stream_mode == "immediate":
        return

    audio = stream_audio_metrics(
        accepted["audio_stream_url"],
        timeout=args.audio_timeout,
        virtual_player_prebuffer_bytes=args.virtual_player_prebuffer_bytes,
    )
    audio["event"] = "audio"
    audio["session_id"] = accepted["session_id"]
    audio["stream_mode"] = args.stream_mode
    print(json.dumps(audio, ensure_ascii=False))


if __name__ == "__main__":
    main()
