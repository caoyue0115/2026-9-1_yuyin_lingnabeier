from __future__ import annotations

import uuid
import wave
from pathlib import Path

from src.settings import settings


def ensure_data_dirs() -> None:
    for path in (
        settings.data_dir,
        settings.incoming_dir,
        settings.output_dir,
        settings.ota_artifact_path,
        settings.kb_dir,
        settings.logs_dir,
        settings.indices_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)


def save_pcm_as_wav(pcm_bytes: bytes, sample_rate: int, sample_width_bits: int, channels: int) -> Path:
    ensure_data_dirs()
    out_path = settings.incoming_dir / f"{uuid.uuid4()}.wav"
    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width_bits // 8)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return out_path


def output_audio_path(suffix: str = ".wav") -> Path:
    ensure_data_dirs()
    return settings.output_dir / f"{uuid.uuid4()}{suffix}"


def safe_audio_path(filename: str) -> Path:
    return settings.output_dir / Path(filename).name
