from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import sys
import wave
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.settings import settings


def default_voice_sample_path() -> Path:
    return ROOT / "data" / "voice_samples" / "judy_demo.wav"


def inspect_audio_file(path: str | Path) -> dict:
    audio_path = Path(path)
    with wave.open(str(audio_path), "rb") as wav_file:
        frames = wav_file.getnframes()
        sample_rate = wav_file.getframerate()
        return {
            "channels": wav_file.getnchannels(),
            "sample_width_bits": wav_file.getsampwidth() * 8,
            "sample_rate": sample_rate,
            "duration_s": round(frames / max(1, sample_rate), 3),
            "size_bytes": audio_path.stat().st_size,
        }


def encode_audio_data_uri(path: str | Path) -> str:
    audio_path = Path(path)
    mime_type, _ = mimetypes.guess_type(audio_path.name)
    mime_type = mime_type or "audio/wav"
    payload = base64.b64encode(audio_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{payload}"


def build_summary(voice_id: str, target_model: str, sample_path: str | Path, prefix: str) -> dict:
    return {
        "voice_id": voice_id,
        "target_model": target_model,
        "prefix": prefix,
        "sample_path": str(Path(sample_path)),
        "audio_info": inspect_audio_file(sample_path),
    }


def build_create_voice_payload(sample_path: str | Path, *, target_model: str, prefix: str) -> dict:
    return {
        "model": "qwen-voice-enrollment",
        "input": {
            "action": "create",
            "target_model": target_model,
            "preferred_name": prefix,
            "audio": {
                "data": encode_audio_data_uri(sample_path),
            },
        },
    }


def create_realtime_voice(sample_path: str | Path, *, target_model: str, prefix: str) -> str:
    url = settings.dashscope_base_url.rstrip("/") + "/api/v1/services/audio/tts/customization"
    response = requests.post(
        url,
        json=build_create_voice_payload(sample_path, target_model=target_model, prefix=prefix),
        headers={
            "Authorization": f"Bearer {settings.dashscope_api_key}",
            "Content-Type": "application/json",
        },
        timeout=float(settings.request_timeout_seconds),
    )
    if response.status_code != 200:
        raise RuntimeError(f"create realtime voice failed: {response.status_code}, {response.text}")
    body = response.json()
    try:
        return body["output"]["voice"]
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"parse realtime voice response failed: {body}") from exc


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", default=str(default_voice_sample_path()))
    parser.add_argument("--target-model", default=settings.realtime_tts_model)
    parser.add_argument("--prefix", default="judydemo")
    args = parser.parse_args()

    summary = inspect_audio_file(args.sample)
    if summary["sample_rate"] < 24000:
        raise SystemExit("voice sample must be at least 24kHz")

    voice_id = create_realtime_voice(
        args.sample,
        target_model=args.target_model,
        prefix=args.prefix,
    )
    payload = build_summary(voice_id, args.target_model, args.sample, args.prefix)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"REALTIME_TTS_VOICE={voice_id}")


if __name__ == "__main__":
    main()
