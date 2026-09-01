from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "dev"
    host: str = "0.0.0.0"
    port: int = 8010
    redis_url: str = "redis://redis:6379/0"
    sqlite_path: str = "./data/tasks.db"
    public_base_url: str = "http://localhost:8010"
    ota_artifact_dir: str = "./data/ota_artifacts"
    queue_name: str = "disney_tasks"
    max_upload_mb: int = 3
    max_audio_seconds: int = 8
    chunk_size: int = 300
    chunk_overlap: int = 50
    top_k: int = 2
    bm25_weight: float = 0.55
    min_top_score: float = 0.35
    min_top_score_no_keyword: float = 0.5
    embedding_model: str = "hash-jieba-768"
    embedding_dim: int = 768
    llm_provider: str = "dashscope"
    llm_model: str = "qwen3.5-flash-2026-02-23"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 256
    asr_provider: str = "dashscope"
    asr_fallback_provider: str = ""
    asr_provider_override_device_ids: str = ""
    asr_provider_override_provider: str = ""
    asr_model: str = "paraformer-realtime-v2"
    asr_timeout_seconds: float = 30.0
    asr_language_hints: str = "zh"
    asr_vocabulary_id: str = ""
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com"
    dashscope_tts_model: str = "qwen3-tts-vc-2026-01-22"
    tts_voice: str = ""
    realtime_tts_model: str = "qwen3-tts-vc-realtime-2026-01-15"
    realtime_tts_voice: str = ""
    tts_language_type: str = "Chinese"
    tts_instructions: str = "请使用明快、机灵、温暖的年轻女性中文声线，语速自然，表达友好。"
    tts_timeout_seconds: int = 20
    dashscope_playback_rate: float = 1.0
    request_timeout_seconds: int = 30
    default_sample_rate: int = 16000
    default_sample_width_bits: int = 16
    default_channels: int = 1
    audio_content_type: str = "audio/wav"
    realtime_enabled: bool = False
    realtime_session_ttl_seconds: int = 900
    realtime_stream_first_chunk_timeout_ms: int = 5000
    realtime_stream_idle_timeout_ms: int = 8000
    realtime_audio_sample_rate: int = 16000
    realtime_audio_sample_width_bits: int = 16
    realtime_audio_channels: int = 1
    realtime_audio_endian: str = "little"
    realtime_audio_enable_opus: bool = False
    realtime_audio_opus_sample_rate: int = 16000
    realtime_audio_opus_channels: int = 1
    realtime_audio_opus_frame_duration_ms: int = 60
    realtime_audio_opus_bitrate: int = 24000
    realtime_tts_min_chars: int = 8
    realtime_tts_max_chars: int = 40
    realtime_tts_first_segment_min_chars: int = 6
    realtime_tts_first_segment_max_chars: int = 10
    realtime_tts_warmup_enabled: bool = True
    realtime_llm_compact_top_k: int = 1
    realtime_llm_compact_snippet_chars: int = 36
    conversation_v6_audio_queue_bytes: int = 256 * 1024
    conversation_v6_cancel_timeout_seconds: float = 2.0
    conversation_v6_close_timeout_seconds: float = 2.0
    conversation_v6_question_chars: int = 512
    conversation_v6_answer_chars: int = 4096
    project_name: str = "Disney Voice Assistant Demo"
    version: str = "0.1.0"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def project_root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    @property
    def data_dir(self) -> Path:
        return self.project_root / "data"

    @property
    def incoming_dir(self) -> Path:
        return self.data_dir / "incoming"

    @property
    def output_dir(self) -> Path:
        return self.data_dir / "output"

    @property
    def ota_artifact_path(self) -> Path:
        raw = Path(self.ota_artifact_dir)
        if raw.is_absolute():
            return raw
        return (self.project_root / raw).resolve()

    @property
    def kb_dir(self) -> Path:
        return self.data_dir / "disney"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def indices_dir(self) -> Path:
        return self.project_root / "indices"

    @property
    def sqlite_file(self) -> Path:
        raw = Path(self.sqlite_path)
        if raw.is_absolute():
            return raw
        return (self.project_root / raw).resolve()

    @property
    def asr_language_hints_list(self) -> list[str]:
        return [part.strip() for part in self.asr_language_hints.split(",") if part.strip()]


settings = Settings()
