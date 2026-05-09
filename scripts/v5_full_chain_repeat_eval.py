from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.opus_uplink_stream_smoke import run_stream_smoke


CASES = [
    ("阿弥陀佛", "amitabha.wav"),
    ("四十八愿", "forty_eight_vows.wav"),
    ("净土宗", "pure_land.wav"),
    ("无量寿经", "infinite_life_sutra.wav"),
    ("金刚经", "diamond_sutra.wav"),
    ("般若", "prajna.wav"),
    ("慧远", "huiyuan.wav"),
    ("善导", "shandao.wav"),
    ("东林寺", "donglin_temple.wav"),
]

PROVIDER_CHOICES = {"dashscope", "volcengine"}
ANSWER_MODE_CHOICES = {"default", "short"}
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


def discover_cases(audio_dir: str | Path) -> list[tuple[str, Path]]:
    base = Path(audio_dir)
    return [(term, base / filename) for term, filename in CASES if (base / filename).exists()]


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


def _answer_chars(answer_text: str | None) -> int:
    return len("".join(str(answer_text or "").split()))


def _record_value(done_payload: dict[str, Any], status_payload: dict[str, Any], key: str) -> Any:
    trace = status_payload.get("trace")
    if isinstance(trace, dict) and key in trace:
        return trace.get(key)
    if key in done_payload:
        return done_payload.get(key)
    return None


def build_full_chain_record(
    *,
    term: str,
    audio_path: str,
    repeat_index: int,
    provider: str,
    answer_mode: str,
    done_payload: dict[str, Any],
) -> dict[str, Any]:
    status_payload = done_payload.get("session_status")
    if not isinstance(status_payload, dict):
        status_payload = {}
    question_text = status_payload.get("question_text") or done_payload.get("question_text")
    answer_text = status_payload.get("answer_text") or ""
    provider_log_id = (
        done_payload.get("provider_log_id")
        or done_payload.get("asr_log_id")
        or done_payload.get("realtime_asr_request_id")
        or done_payload.get("request_id")
    )
    record: dict[str, Any] = {
        "provider": done_payload.get("asr_provider") or provider,
        "asr_primary_provider": done_payload.get("asr_primary_provider") or provider,
        "asr_fallback_provider": done_payload.get("asr_fallback_provider"),
        "asr_provider_used": done_payload.get("asr_provider_used") or done_payload.get("asr_provider") or provider,
        "asr_fallback_used": bool(done_payload.get("asr_fallback_used")),
        "asr_primary_error_code": done_payload.get("asr_primary_error_code"),
        "asr_primary_error_message": done_payload.get("asr_primary_error_message"),
        "term": term,
        "repeat_index": repeat_index,
        "audio_path": audio_path,
        "answer_mode": answer_mode,
        "question_text": question_text,
        "recognized_text": question_text,
        "term_hit": _term_hit(term, question_text),
        "answer_chars": _answer_chars(answer_text),
        "session_id": status_payload.get("session_id") or done_payload.get("session_id"),
        "provider_log_id": provider_log_id,
        "error_code": status_payload.get("error_code") or done_payload.get("error_code"),
        "error_message": status_payload.get("error_message") or done_payload.get("error_message"),
    }
    for field in FULL_CHAIN_FIELDS:
        record[field] = _record_value(done_payload, status_payload, field)
    return record


def build_error_record(
    *,
    term: str,
    audio_path: str,
    repeat_index: int,
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
        "term": term,
        "repeat_index": repeat_index,
        "audio_path": audio_path,
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


def run_full_chain_case(
    *,
    term: str,
    audio_path: Path,
    repeat_index: int,
    provider: str,
    base_url: str,
    frame_ms: int,
    realtime: bool,
    timeout: float,
    status_timeout: float,
    poll_interval: float,
    max_polls: int,
    answer_mode: str,
    asr_fallback_provider: str | None = None,
) -> dict[str, Any]:
    try:
        done_payload = run_stream_smoke(
            audio_path,
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
            term=term,
            audio_path=str(audio_path),
            repeat_index=repeat_index,
            provider=provider,
            answer_mode=answer_mode,
            error_code="smoke_failed",
            error_message=str(exc),
        )
    if done_payload.get("type") == "error":
        return build_error_record(
            term=term,
            audio_path=str(audio_path),
            repeat_index=repeat_index,
            provider=provider,
            answer_mode=answer_mode,
            error_code=done_payload.get("error_code") or "full_chain_error",
            error_message=done_payload.get("error_message") or "full-chain smoke failed",
        )
    return build_full_chain_record(
        term=term,
        audio_path=str(audio_path),
        repeat_index=repeat_index,
        provider=provider,
        answer_mode=answer_mode,
        done_payload=done_payload,
    )


def run_eval(args: argparse.Namespace) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    cases = discover_cases(args.audio_dir)
    providers = providers_from_args(args)
    for provider in providers:
        for repeat_index in range(1, args.repeats + 1):
            for term, audio_path in cases:
                records.append(
                    run_full_chain_case(
                        term=term,
                        audio_path=audio_path,
                        repeat_index=repeat_index,
                        provider=provider,
                        base_url=args.base_url,
                        frame_ms=args.frame_ms,
                        realtime=args.realtime,
                        timeout=args.timeout,
                        status_timeout=args.status_timeout,
                        poll_interval=args.poll_interval,
                        max_polls=args.max_polls,
                        answer_mode=args.answer_mode,
                        asr_fallback_provider=None
                        if args.asr_fallback_provider == "none"
                        else args.asr_fallback_provider,
                    )
                )
    return records


def write_jsonl(records: list[dict[str, Any]], output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as writer:
        for record in records:
            writer.write(json.dumps(record, ensure_ascii=False) + "\n")


def _numeric_values(records: list[dict[str, Any]], key: str) -> list[float]:
    return [
        float(record[key])
        for record in records
        if not record.get("error_code") and isinstance(record.get(key), (int, float))
    ]


def _mean(records: list[dict[str, Any]], key: str) -> float | None:
    values = _numeric_values(records, key)
    return round(statistics.mean(values), 1) if values else None


def _median(records: list[dict[str, Any]], key: str) -> float | None:
    values = _numeric_values(records, key)
    return round(statistics.median(values), 1) if values else None


def _p95(records: list[dict[str, Any]], key: str) -> float | None:
    values = sorted(_numeric_values(records, key))
    if not values:
        return None
    index = max(0, math.ceil(len(values) * 0.95) - 1)
    return round(values[index], 1)


def _value_range(records: list[dict[str, Any]], key: str) -> str:
    values = _numeric_values(records, key)
    if not values:
        return ""
    return f"{min(values):.0f}-{max(values):.0f}"


def _format_text_counts(texts: list[str]) -> str:
    if not texts:
        return ""
    counts = Counter(texts)
    return "<br>".join(f"{text} ({count})" for text, count in counts.most_common())


def write_markdown(records: list[dict[str, Any]], markdown_path: str | Path) -> None:
    path = Path(markdown_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    provider_names = sorted({str(record.get("provider") or "") for record in records if record.get("provider")})
    lines = [
        "# v5 Full-chain ASR Provider Repeat Eval",
        "",
        "口径：`WS /api/v5/realtime/opus-stream` 使用 `run_asr=true`、`run_full_chain=true`，并传入固定 `answer_mode`。本矩阵用于比较同一后段输出约束下的端到端首音频和 total。",
        "",
        "## Provider Summary",
        "",
        "| provider | success_count / total | term_hits / total | mean_asr_final_abs_ms | median_asr_final_abs_ms | p95_asr_final_abs_ms | mean_first_audio_byte_abs_ms | median_first_audio_byte_abs_ms | p95_first_audio_byte_abs_ms | mean_done_abs_ms | median_done_abs_ms | p95_done_abs_ms | mean_answer_chars | mean_audio_duration_ms |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for provider in provider_names:
        provider_records = [record for record in records if record.get("provider") == provider]
        successful = [record for record in provider_records if not record.get("error_code")]
        hits = [record for record in successful if record.get("term_hit")]
        lines.append(
            "| {provider} | {success}/{total} | {hits}/{total} | {mean_asr} | {median_asr} | {p95_asr} | {mean_audio} | {median_audio} | {p95_audio} | {mean_done} | {median_done} | {p95_done} | {mean_chars} | {mean_duration} |".format(
                provider=provider,
                success=len(successful),
                total=len(provider_records),
                hits=len(hits),
                mean_asr=_mean(provider_records, "asr_final_abs_ms"),
                median_asr=_median(provider_records, "asr_final_abs_ms"),
                p95_asr=_p95(provider_records, "asr_final_abs_ms"),
                mean_audio=_mean(provider_records, "first_audio_byte_abs_ms"),
                median_audio=_median(provider_records, "first_audio_byte_abs_ms"),
                p95_audio=_p95(provider_records, "first_audio_byte_abs_ms"),
                mean_done=_mean(provider_records, "done_abs_ms"),
                median_done=_median(provider_records, "done_abs_ms"),
                p95_done=_p95(provider_records, "done_abs_ms"),
                mean_chars=_mean(provider_records, "answer_chars"),
                mean_duration=_mean(provider_records, "audio_duration_ms"),
            )
        )

    lines.extend(
        [
            "",
            "## Term Summary",
            "",
            "| provider | term | hit_count / repeats | unique question_texts | mean_first_audio_byte_abs_ms | mean_done_abs_ms | answer_chars range | audio_duration_ms range |",
            "| --- | --- | ---: | --- | ---: | ---: | --- | --- |",
        ]
    )
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[(str(record.get("provider") or ""), str(record.get("term") or ""))].append(record)
    for provider, term in sorted(grouped):
        group_records = grouped[(provider, term)]
        ok_records = [record for record in group_records if not record.get("error_code")]
        hit_records = [record for record in ok_records if record.get("term_hit")]
        texts = [str(record.get("question_text") or "") for record in ok_records if record.get("question_text")]
        lines.append(
            "| {provider} | {term} | {hits}/{repeats} | {texts} | {mean_audio} | {mean_done} | {chars_range} | {duration_range} |".format(
                provider=provider,
                term=term,
                hits=len(hit_records),
                repeats=len(group_records),
                texts=_format_text_counts(texts),
                mean_audio=_mean(group_records, "first_audio_byte_abs_ms"),
                mean_done=_mean(group_records, "done_abs_ms"),
                chars_range=_value_range(group_records, "answer_chars"),
                duration_range=_value_range(group_records, "audio_duration_ms"),
            )
        )

    lines.extend(
        [
            "",
            "## Details",
            "",
            "| provider | primary_provider | fallback_provider | provider_used | fallback_used | term | repeat | hit | question_text | asr_final_abs_ms | first_audio_byte_abs_ms | done_abs_ms | answer_chars | audio_duration_ms | primary_error | error_code | session_id | provider_log_id |",
            "| --- | --- | --- | --- | --- | --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- |",
        ]
    )
    for record in records:
        lines.append(
            "| {provider} | {primary} | {fallback_provider} | {provider_used} | {fallback_used} | {term} | {repeat} | {hit} | {text} | {asr} | {first_audio} | {done} | {chars} | {duration} | {primary_error} | {error} | {session} | {log_id} |".format(
                provider=record.get("provider") or "",
                primary=record.get("asr_primary_provider") or "",
                fallback_provider=record.get("asr_fallback_provider") or "",
                provider_used=record.get("asr_provider_used") or "",
                fallback_used="Y" if record.get("asr_fallback_used") else "N",
                term=record.get("term") or "",
                repeat=record.get("repeat_index"),
                hit="Y" if record.get("term_hit") else "N",
                text=str(record.get("question_text") or "").replace("|", "\\|"),
                asr=record.get("asr_final_abs_ms"),
                first_audio=record.get("first_audio_byte_abs_ms"),
                done=record.get("done_abs_ms"),
                chars=record.get("answer_chars"),
                duration=record.get("audio_duration_ms"),
                primary_error=record.get("asr_primary_error_code") or "",
                error=record.get("error_code") or "",
                session=record.get("session_id") or "",
                log_id=record.get("provider_log_id") or "",
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio-dir", default="/tmp/volc_asr_eval")
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--providers", default="dashscope,volcengine")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--frame-ms", type=int, default=60)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--status-timeout", type=float, default=20.0)
    parser.add_argument("--poll-interval", type=float, default=0.3)
    parser.add_argument("--max-polls", type=int, default=120)
    parser.add_argument("--answer-mode", choices=sorted(ANSWER_MODE_CHOICES), default="short")
    parser.add_argument("--asr-fallback-provider", choices=sorted(PROVIDER_CHOICES | {"none"}), default=None)
    parser.add_argument("--output", default="/tmp/v5_full_chain_repeat_eval.jsonl")
    parser.add_argument("--markdown", default="/tmp/v5_full_chain_repeat_eval.md")
    parser.add_argument("--realtime", dest="realtime", action="store_true")
    parser.add_argument("--no-realtime", dest="realtime", action="store_false")
    parser.set_defaults(realtime=True)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.repeats <= 0:
        raise SystemExit("--repeats must be positive")
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
