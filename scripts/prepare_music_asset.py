from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from src.providers.opus import encode_pcm_stream_to_framed_opus, pack_framed_v1_packets


SAMPLE_RATE = 16_000
CHANNELS = 1
FRAME_DURATION_MS = 60
BITRATE = 24_000
READ_BYTES = SAMPLE_RATE * CHANNELS * 2 * FRAME_DURATION_MS // 1000 * 20


def _ffmpeg_pcm_chunks(input_path: Path):
    process = subprocess.Popen(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(input_path),
            "-vn",
            "-ac",
            str(CHANNELS),
            "-ar",
            str(SAMPLE_RATE),
            "-c:a",
            "pcm_s16le",
            "-f",
            "s16le",
            "pipe:1",
        ],
        stdout=subprocess.PIPE,
    )
    if process.stdout is None:
        raise RuntimeError("ffmpeg_stdout_unavailable")
    try:
        while chunk := process.stdout.read(READ_BYTES):
            yield chunk
    finally:
        process.stdout.close()
        return_code = process.wait()
        if return_code != 0:
            raise RuntimeError(f"ffmpeg_failed:{return_code}")


def prepare_music_asset(input_path: Path, output_path: Path) -> dict[str, int]:
    if not input_path.is_file():
        raise FileNotFoundError(input_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    inner_packets = encode_pcm_stream_to_framed_opus(
        _ffmpeg_pcm_chunks(input_path),
        sample_rate=SAMPLE_RATE,
        channels=CHANNELS,
        frame_duration_ms=FRAME_DURATION_MS,
        bitrate=BITRATE,
    )
    packet_count = 0
    with output_path.open("wb") as output:
        for framed_packet in pack_framed_v1_packets(inner_packets):
            output.write(framed_packet)
            packet_count += 1
    return {"packet_count": packet_count, "output_bytes": output_path.stat().st_size}


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a framed Opus music asset for ESP32 playback")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = prepare_music_asset(args.input, args.output)
    print(
        f"prepared {args.output} packets={result['packet_count']} "
        f"bytes={result['output_bytes']} bitrate={BITRATE}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
