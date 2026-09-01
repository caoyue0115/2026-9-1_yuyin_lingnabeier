from __future__ import annotations

from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from http import HTTPStatus
import os
from pathlib import Path
import signal
import threading
from typing import Any

from src.settings import settings


@dataclass(frozen=True)
class ASRResult:
    text: str | None
    error_code: str | None
    error_message: str | None = None


def _is_asr_configured() -> bool:
    provider = (settings.asr_provider or "dashscope").strip().lower()
    if provider == "dashscope":
        return bool(settings.dashscope_api_key and settings.asr_model)
    if provider == "volcengine":
        return bool(
            os.getenv("VOLCENGINE_SPEECH_APP_ID")
            and os.getenv("VOLCENGINE_SPEECH_ACCESS_TOKEN")
            and os.getenv("VOLCENGINE_ASR_RESOURCE_ID")
        )
    return False


def asr_health() -> bool:
    if not _is_asr_configured():
        return False
    if (settings.asr_provider or "dashscope").strip().lower() == "volcengine":
        return True
    try:
        _load_recognition_class()
    except ImportError:
        return False
    return True


def _configure_dashscope_sdk() -> None:
    import dashscope

    dashscope.api_key = settings.dashscope_api_key
    if hasattr(dashscope, "base_http_api_url") and settings.dashscope_base_url:
        dashscope.base_http_api_url = settings.dashscope_base_url.rstrip("/")


def _load_recognition_class():
    from dashscope.audio.asr import Recognition

    return Recognition


class _ASRTimeout(Exception):
    pass


def _alarm_handler(signum: int, frame: Any) -> None:
    del signum, frame
    raise _ASRTimeout("ASR call exceeded timeout")


def _is_main_thread() -> bool:
    return threading.current_thread() is threading.main_thread()


def _run_with_timeout(recognition: Any, audio_path: str) -> Any:
    if not _is_main_thread():
        return recognition.call(audio_path)
    timeout_seconds = max(float(settings.asr_timeout_seconds), 0.001)
    signal_timeout_supported = all(
        hasattr(signal, name) for name in ("SIGALRM", "ITIMER_REAL", "setitimer")
    )
    if not signal_timeout_supported:
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="asr-timeout")
        future = executor.submit(recognition.call, audio_path)
        try:
            return future.result(timeout=timeout_seconds)
        except FutureTimeoutError as exc:
            future.cancel()
            raise TimeoutError(f"ASR timed out after {timeout_seconds:.3f}s") from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
    previous_handler = signal.getsignal(signal.SIGALRM)
    try:
        signal.signal(signal.SIGALRM, _alarm_handler)
        signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
        return recognition.call(audio_path)
    except _ASRTimeout as exc:
        raise TimeoutError(f"ASR timed out after {timeout_seconds:.3f}s") from exc
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, previous_handler)


def _build_recognition_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": settings.asr_model,
        "format": "wav",
        "sample_rate": settings.default_sample_rate,
        "language_hints": settings.asr_language_hints_list,
        "callback": None,
    }
    if settings.asr_vocabulary_id:
        kwargs["vocabulary_id"] = settings.asr_vocabulary_id
    return kwargs


def _collect_text_parts(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, dict):
        parts: list[str] = []
        for key in ("sentence", "text", "transcript", "content"):
            parts.extend(_collect_text_parts(value.get(key)))
        for key in ("sentences", "results", "output", "data"):
            parts.extend(_collect_text_parts(value.get(key)))
        return parts
    if isinstance(value, (list, tuple)):
        parts: list[str] = []
        for item in value:
            parts.extend(_collect_text_parts(item))
        return parts

    parts: list[str] = []
    for attr in ("sentence", "text", "transcript", "content", "sentences", "results", "output", "data"):
        if hasattr(value, attr):
            parts.extend(_collect_text_parts(getattr(value, attr)))
    return parts


def _extract_result_text(result: Any) -> str:
    # DashScope SDK result objects can vary by version, so keep parsing shallow and defensive.
    getter = getattr(result, "get_sentence", None)
    if callable(getter):
        parts = _collect_text_parts(getter())
        if parts:
            return " ".join(parts).strip()

    parts = _collect_text_parts(result)
    return " ".join(parts).strip()


def _status_error_code(status_code: Any) -> str:
    try:
        return f"asr_http_{int(status_code)}"
    except (TypeError, ValueError):
        return "asr_request_failed"


def _error_message_from_exception(exc: Exception) -> str:
    detail = str(exc).strip()
    return f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__


def _status_error_message(result: Any) -> str | None:
    for key in ("message", "msg"):
        value = getattr(result, key, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if isinstance(result, dict):
        for key in ("message", "msg"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def transcribe_wav_result(wav_path: str | Path) -> ASRResult:
    if not _is_asr_configured():
        return ASRResult(None, "asr_not_configured", "DashScope ASR is not fully configured")

    path = Path(wav_path)
    if not path.exists():
        return ASRResult(None, "asr_file_not_found", f"Audio file not found: {path}")

    try:
        _configure_dashscope_sdk()
        recognition_class = _load_recognition_class()
        recognition = recognition_class(**_build_recognition_kwargs())
        result = _run_with_timeout(recognition, str(path))
    except ImportError as exc:
        return ASRResult(None, "asr_sdk_unavailable", _error_message_from_exception(exc))
    except TimeoutError as exc:
        return ASRResult(None, "asr_timeout", _error_message_from_exception(exc))
    except FileNotFoundError:
        return ASRResult(None, "asr_file_not_found", f"Audio file not found: {path}")
    except Exception as exc:
        return ASRResult(None, "asr_request_failed", _error_message_from_exception(exc))

    status_code = getattr(result, "status_code", None)
    if status_code != HTTPStatus.OK:
        return ASRResult(None, _status_error_code(status_code), _status_error_message(result))

    text = _extract_result_text(result)
    if not text:
        return ASRResult(None, "asr_empty_text", "DashScope ASR returned empty text")
    return ASRResult(text, None, None)


def transcribe_wav(wav_path: str | Path) -> tuple[str | None, str | None]:
    result = transcribe_wav_result(wav_path)
    return result.text, result.error_code
