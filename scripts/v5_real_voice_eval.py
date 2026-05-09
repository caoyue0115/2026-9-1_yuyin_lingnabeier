from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.opus_uplink_stream_smoke import run_stream_smoke
from scripts.v5_full_chain_repeat_eval import (
    ANSWER_MODE_CHOICES,
    PROVIDER_CHOICES,
    _answer_chars,
    _record_value,
    write_jsonl,
)


REAL_VOICE_CASES = [
    ("阿弥陀佛", "amitabha"),
    ("四十八愿", "forty_eight_vows"),
    ("净土宗", "pure_land"),
    ("无量寿经", "infinite_life_sutra"),
    ("金刚经", "diamond_sutra"),
    ("般若", "prajna"),
    ("慧远", "huiyuan"),
    ("善导", "shandao"),
    ("东林寺", "donglin_temple"),
]

FULL_CHAIN_FIELDS = [
    "provider_start_duration_ms",
    "first_provider_result_abs_ms",
    "asr_final_abs_ms",
    "retrieval_done_abs_ms",
    "first_llm_chunk_abs_ms",
    "first_tts_chunk_abs_ms",
    "first_audio_byte_abs_ms",
    "done_abs_ms",
    "audio_duration_ms",
    "audio_bytes",
]


def discover_real_voice_cases(audio_dir: str | Path) -> list[dict[str, Any]]:
    base = Path(audio_dir)
    cases: list[dict[str, Any]] = []
    for term, slug in REAL_VOICE_CASES:
        for path in sorted(base.glob(f"{slug}_*.wav")):
            suffix = path.stem.removeprefix(f"{slug}_")
            try:
                speaker_index = int(suffix)
            except ValueError:
                speaker_index = None
            cases.append(
                {
                    "term": term,
                    "slug": slug,
                    "speaker_index": speaker_index,
                    "audio_path": path,
                }
            )
    return cases


def providers_from_args(args: argparse.Namespace) -> list[str]:
    providers = [provider.strip() for provider in args.providers.split(",") if provider.strip()]
    invalid = [provider for provider in providers if provider not in PROVIDER_CHOICES]
    if invalid:
        raise ValueError(f"invalid ASR provider(s): {', '.join(invalid)}")
    if not providers:
        raise ValueError("at least one ASR provider is required")
    return providers


def _term_hit(term: str, text: str | None) -> bool:
    return bool(term and text and term in text)


def build_real_voice_record(
    *,
    case: dict[str, Any],
    provider: str,
    answer_mode: str,
    done_payload: dict[str, Any],
) -> dict[str, Any]:
    status_payload = done_payload.get("session_status")
    if not isinstance(status_payload, dict):
        status_payload = {}
    question_text = status_payload.get("question_text") or done_payload.get("question_text")
    answer_text = status_payload.get("answer_text") or ""
    record: dict[str, Any] = {
        "provider": done_payload.get("asr_provider") or provider,
        "asr_primary_provider": done_payload.get("asr_primary_provider") or provider,
        "asr_fallback_provider": done_payload.get("asr_fallback_provider"),
        "asr_provider_used": done_payload.get("asr_provider_used") or done_payload.get("asr_provider") or provider,
        "asr_fallback_used": bool(done_payload.get("asr_fallback_used")),
        "asr_primary_error_code": done_payload.get("asr_primary_error_code"),
        "asr_primary_error_message": done_payload.get("asr_primary_error_message"),
        "term": case["term"],
        "slug": case["slug"],
        "speaker_index": case["speaker_index"],
        "audio_path": str(case["audio_path"]),
        "answer_mode": answer_mode,
        "question_text": question_text,
        "recognized_text": question_text,
        "term_hit": _term_hit(str(case["term"]), question_text),
        "answer_chars": _answer_chars(answer_text),
        "session_id": status_payload.get("session_id") or done_payload.get("session_id"),
        "provider_log_id": done_payload.get("provider_log_id") or done_payload.get("asr_log_id"),
        "error_code": status_payload.get("error_code") or done_payload.get("error_code"),
        "error_message": status_payload.get("error_message") or done_payload.get("error_message"),
    }
    for field in FULL_CHAIN_FIELDS:
        record[field] = _record_value(done_payload, status_payload, field)
    return record


def build_error_record(
    *,
    case: dict[str, Any],
    provider: str,
    answer_mode: str,
    error_code: str,
    error_message: str,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "provider": provider,
        "asr_primary_provider": provider,
        "asr_fallback_provider": None,
        "asr_provider_used": None,
        "asr_fallback_used": False,
        "asr_primary_error_code": None,
        "asr_primary_error_message": None,
        "term": case["term"],
        "slug": case["slug"],
        "speaker_index": case["speaker_index"],
        "audio_path": str(case["audio_path"]),
        "answer_mode": answer_mode,
        "question_text": None,
        "recognized_text": None,
        "term_hit": False,
        "answer_chars": 0,
        "session_id": None,
        "provider_log_id": None,
        "error_code": error_code,
        "error_message": error_message,
    }
    for field in FULL_CHAIN_FIELDS:
        record[field] = None
    return record


def run_case(
    *,
    case: dict[str, Any],
    provider: str,
    base_url: str,
    frame_ms: int,
    realtime: bool,
    timeout: float,
    status_timeout: float,
    poll_interval: float,
    max_polls: int,
    answer_mode: str,
    asr_fallback_provider: str | None,
) -> dict[str, Any]:
    try:
        done_payload = run_stream_smoke(
            case["audio_path"],
            base_url=base_url.rstrip("/"),
            frame_ms=frame_ms,
            realtime=realtime,
            timeout=timeout,
            run_session_after_stream=False,
            run_asr=True,
            run_full_chain=True,
            asr_provider=provider,
            asr_fallback_provider=asr_fallback_provider,
            poll_interval=poll_interval,
            max_polls=max_polls,
            status_timeout=status_timeout,
            answer_mode=answer_mode,
            emit_trace=False,
        )
    except Exception as exc:
        return build_error_record(
            case=case,
            provider=provider,
            answer_mode=answer_mode,
            error_code="smoke_failed",
            error_message=str(exc),
        )
    if done_payload.get("type") == "error":
        return build_error_record(
            case=case,
            provider=provider,
            answer_mode=answer_mode,
            error_code=done_payload.get("error_code") or "real_voice_error",
            error_message=done_payload.get("error_message") or "real voice smoke failed",
        )
    return build_real_voice_record(
        case=case,
        provider=provider,
        answer_mode=answer_mode,
        done_payload=done_payload,
    )


def run_eval(args: argparse.Namespace) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    cases = discover_real_voice_cases(args.audio_dir)
    providers = providers_from_args(args)
    fallback = None if args.asr_fallback_provider == "none" else args.asr_fallback_provider
    for provider in providers:
        for case in cases:
            records.append(
                run_case(
                    case=case,
                    provider=provider,
                    base_url=args.base_url,
                    frame_ms=args.frame_ms,
                    realtime=args.realtime,
                    timeout=args.timeout,
                    status_timeout=args.status_timeout,
                    poll_interval=args.poll_interval,
                    max_polls=args.max_polls,
                    answer_mode=args.answer_mode,
                    asr_fallback_provider=fallback,
                )
            )
    return records


def write_markdown(records: list[dict[str, Any]], markdown_path: str | Path) -> None:
    path = Path(markdown_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# v5 Real Voice Eval",
        "",
        "口径：真实人声或板端录音放在 `/tmp/v5_real_voice_eval/`，文件不入库。每条 WAV 通过 v5 streaming Opus 上行，并可按 provider 做 A/B。",
        "",
        "| provider | term | speaker | hit | question_text | asr_final_abs_ms | first_audio_byte_abs_ms | done_abs_ms | fallback_used | error_code |",
        "| --- | --- | ---: | --- | --- | ---: | ---: | ---: | --- | --- |",
    ]
    for record in records:
        lines.append(
            "| {provider} | {term} | {speaker} | {hit} | {text} | {asr} | {audio} | {done} | {fallback} | {error} |".format(
                provider=record.get("provider") or "",
                term=record.get("term") or "",
                speaker=record.get("speaker_index") or "",
                hit="Y" if record.get("term_hit") else "N",
                text=str(record.get("question_text") or "").replace("|", "\\|"),
                asr=record.get("asr_final_abs_ms"),
                audio=record.get("first_audio_byte_abs_ms"),
                done=record.get("done_abs_ms"),
                fallback="Y" if record.get("asr_fallback_used") else "N",
                error=record.get("error_code") or "",
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio-dir", default="/tmp/v5_real_voice_eval")
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--providers", default="dashscope,volcengine")
    parser.add_argument("--frame-ms", type=int, default=60)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--status-timeout", type=float, default=20.0)
    parser.add_argument("--poll-interval", type=float, default=0.3)
    parser.add_argument("--max-polls", type=int, default=120)
    parser.add_argument("--answer-mode", choices=sorted(ANSWER_MODE_CHOICES), default="short")
    parser.add_argument("--asr-fallback-provider", choices=sorted(PROVIDER_CHOICES | {"none"}), default=None)
    parser.add_argument("--output", default="/tmp/v5_real_voice_eval.jsonl")
    parser.add_argument("--markdown", default="/tmp/v5_real_voice_eval.md")
    parser.add_argument("--realtime", dest="realtime", action="store_true")
    parser.add_argument("--no-realtime", dest="realtime", action="store_false")
    parser.set_defaults(realtime=True)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    records = run_eval(args)
    write_jsonl(records, args.output)
    write_markdown(records, args.markdown)
    print(
        json.dumps(
            {
                "event": "summary",
                "records": len(records),
                "errors": sum(1 for record in records if record.get("error_code")),
                "output": args.output,
                "markdown": args.markdown,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
