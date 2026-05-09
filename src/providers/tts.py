from __future__ import annotations

import base64
import io
from pathlib import Path
from urllib.parse import urlparse
import wave

import requests

from src.settings import settings
from src.storage.files import output_audio_path


def tts_health() -> bool:
    return bool(settings.dashscope_api_key and settings.dashscope_tts_model and settings.tts_voice)


def _adjust_wav_playback_rate(wav_bytes: bytes) -> bytes:
    rate = settings.dashscope_playback_rate
    if (not wav_bytes) or abs(rate - 1.0) < 1e-6:
        return wav_bytes
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as reader:
            channels = reader.getnchannels()
            sample_width = reader.getsampwidth()
            frame_rate = reader.getframerate()
            frames = reader.readframes(reader.getnframes())
        new_rate = max(8000, int(frame_rate * rate))
        buf = io.BytesIO()
        with wave.open(buf, "wb") as writer:
            writer.setnchannels(channels)
            writer.setsampwidth(sample_width)
            writer.setframerate(new_rate)
            writer.writeframes(frames)
        return buf.getvalue()
    except Exception:
        return wav_bytes


def synthesize_audio(text: str) -> tuple[str | None, str | None]:
    if not text:
        return None, "empty_text"
    payload = {
        "model": settings.dashscope_tts_model,
        "input": {
            "text": text,
            "voice": settings.tts_voice,
            "language_type": settings.tts_language_type,
        },
        "parameters": {
            "instructions": settings.tts_instructions,
            "output_format": "wav",
        },
    }
    headers = {
        "Authorization": f"Bearer {settings.dashscope_api_key}",
        "Content-Type": "application/json",
    }
    api_url = settings.dashscope_base_url.rstrip("/") + "/api/v1/services/aigc/multimodal-generation/generation"
    try:
        resp = requests.post(api_url, headers=headers, json=payload, timeout=settings.tts_timeout_seconds)
        body = resp.json()
    except Exception:
        return None, "dashscope_request_failed"
    if resp.status_code != 200:
        return None, f"dashscope_http_{resp.status_code}"
    output_audio = (body.get("output") or {}).get("audio", {})
    remote_audio_url = output_audio.get("url")
    audio_base64 = output_audio.get("data")
    if (not remote_audio_url) and (not audio_base64):
        return None, "dashscope_missing_audio"
    audio_bytes: bytes
    suffix = ".wav"
    if remote_audio_url:
        parsed = urlparse(remote_audio_url)
        suffix = Path(parsed.path).suffix.lower() or ".wav"
        download = requests.get(remote_audio_url, timeout=settings.tts_timeout_seconds)
        if download.status_code != 200 or not download.content:
            return None, f"audio_download_failed_{download.status_code}"
        audio_bytes = download.content
    else:
        try:
            audio_bytes = base64.b64decode(audio_base64)
        except Exception:
            return None, "audio_base64_decode_failed"
    if suffix == ".wav":
        audio_bytes = _adjust_wav_playback_rate(audio_bytes)
    out_path = output_audio_path(suffix=suffix)
    tmp_path = out_path.with_suffix(f".tmp{suffix}")
    tmp_path.write_bytes(audio_bytes)
    if tmp_path.stat().st_size <= 0:
        tmp_path.unlink(missing_ok=True)
        return None, "empty_audio"
    tmp_path.replace(out_path)
    return str(out_path), None

