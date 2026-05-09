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
ASR_ONLY_FIELDS = [
    "first_frame_server_abs_ms",
    "provider_start_duration_ms",
    "first_pcm_sent_to_provider_abs_ms",
    "first_provider_result_abs_ms",
    "first_asr_partial_abs_ms",
    "asr_final_abs_ms",
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


def _record_value(payload: dict[str, Any], key: str) -> Any:
    if key in payload:
        return payload.get(key)
    trace = payload.get("trace")
    if isinstance(trace, dict):
        return trace.get(key)
    return None


def build_asr_only_record(
    *,
    term: str,
    audio_path: str,
    repeat_index: int,
    provider: str,
    done_payload: dict[str, Any],
) -> dict[str, Any]:
    question_text = done_payload.get("question_text")
    provider_log_id = (
        done_payload.get("provider_log_id")
        or done_payload.get("asr_log_id")
        or done_payload.get("realtime_asr_request_id")
        or done_payload.get("request_id")
    )
    record: dict[str, Any] = {
        "provider": done_payload.get("asr_provider") or provider,
        "term": term,
        "repeat_index": repeat_index,
        "audio_path": audio_path,
        "question_text": question_text,
        "recognized_text": question_text,
        "term_hit": _term_hit(term, question_text),
        "provider_log_id": provider_log_id,
        "error_code": done_payload.get("error_code"),
        "error_message": done_payload.get("error_message"),
    }
    for field in ASR_ONLY_FIELDS:
        record[field] = _record_value(done_payload, field)
    return record


def build_error_record(
    *,
    term: str,
    audio_path: str,
    repeat_index: int,
    provider: str,
    error_code: str,
    error_message: str,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "provider": provider,
        "term": term,
        "repeat_index": repeat_index,
        "audio_path": audio_path,
        "question_text": None,
        "recognized_text": None,
        "term_hit": False,
        "provider_log_id": None,
        "error_code": error_code,
        "error_message": error_message,
    }
    for field in ASR_ONLY_FIELDS:
        record[field] = None
    return record


def run_asr_only_case(
    *,
    term: str,
    audio_path: Path,
    repeat_index: int,
    provider: str,
    base_url: str,
    frame_ms: int,
    realtime: bool,
    timeout: float,
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
            run_full_chain=False,
            asr_provider=provider,
            poll_interval=0.3,
            max_polls=1,
            status_timeout=timeout,
            emit_trace=False,
        )
    except Exception as exc:
        return build_error_record(
            term=term,
            audio_path=str(audio_path),
            repeat_index=repeat_index,
            provider=provider,
            error_code="smoke_failed",
            error_message=str(exc),
        )
    if done_payload.get("type") == "error":
        return build_error_record(
            term=term,
            audio_path=str(audio_path),
            repeat_index=repeat_index,
            provider=provider,
            error_code=done_payload.get("error_code") or "asr_only_error",
            error_message=done_payload.get("error_message") or "ASR-only smoke failed",
        )
    return build_asr_only_record(
        term=term,
        audio_path=str(audio_path),
        repeat_index=repeat_index,
        provider=provider,
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
                    run_asr_only_case(
                        term=term,
                        audio_path=audio_path,
                        repeat_index=repeat_index,
                        provider=provider,
                        base_url=args.base_url,
                        frame_ms=args.frame_ms,
                        realtime=args.realtime,
                        timeout=args.timeout,
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
        "# v5 ASR-only Provider Repeat Eval",
        "",
        "口径：`WS /api/v5/realtime/opus-stream` 仅发送 `run_asr=true`，`run_full_chain=false`。本矩阵只跑到 ASR final，不触发 RAG/LLM/TTS。",
        "",
        "## Provider Summary",
        "",
        "| provider | success_count / total | term_hits / total | mean_asr_final_abs_ms | median_asr_final_abs_ms | p95_asr_final_abs_ms | mean_provider_start_duration_ms | p95_provider_start_duration_ms | mean_first_provider_result_abs_ms | p95_first_provider_result_abs_ms |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for provider in provider_names:
        provider_records = [record for record in records if record.get("provider") == provider]
        successful = [record for record in provider_records if not record.get("error_code")]
        hits = [record for record in provider_records if not record.get("error_code") and record.get("term_hit")]
        lines.append(
            "| {provider} | {success}/{total} | {hits}/{total} | {mean_asr} | {median_asr} | {p95_asr} | {mean_start} | {p95_start} | {mean_first} | {p95_first} |".format(
                provider=provider,
                success=len(successful),
                total=len(provider_records),
                hits=len(hits),
                mean_asr=_mean(provider_records, "asr_final_abs_ms"),
                median_asr=_median(provider_records, "asr_final_abs_ms"),
                p95_asr=_p95(provider_records, "asr_final_abs_ms"),
                mean_start=_mean(provider_records, "provider_start_duration_ms"),
                p95_start=_p95(provider_records, "provider_start_duration_ms"),
                mean_first=_mean(provider_records, "first_provider_result_abs_ms"),
                p95_first=_p95(provider_records, "first_provider_result_abs_ms"),
            )
        )

    lines.extend(
        [
            "",
            "## Term Summary",
            "",
            "| provider | term | hit_count / repeats | unique recognized_texts | common wrong_texts | mean_asr_final_abs_ms |",
            "| --- | --- | ---: | --- | --- | ---: |",
        ]
    )
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[(str(record.get("provider") or ""), str(record.get("term") or ""))].append(record)
    for provider, term in sorted(grouped):
        group_records = grouped[(provider, term)]
        ok_records = [record for record in group_records if not record.get("error_code")]
        hit_records = [record for record in ok_records if record.get("term_hit")]
        texts = [str(record.get("recognized_text") or "") for record in ok_records if record.get("recognized_text")]
        wrong_texts = [
            str(record.get("recognized_text") or "")
            for record in ok_records
            if not record.get("term_hit") and record.get("recognized_text")
        ]
        lines.append(
            "| {provider} | {term} | {hits}/{repeats} | {texts} | {wrong_texts} | {mean_asr} |".format(
                provider=provider,
                term=term,
                hits=len(hit_records),
                repeats=len(group_records),
                texts=_format_text_counts(texts),
                wrong_texts=_format_text_counts(wrong_texts),
                mean_asr=_mean(group_records, "asr_final_abs_ms"),
            )
        )

    lines.extend(
        [
            "",
            "## Details",
            "",
            "| provider | term | repeat | hit | recognized_text | first_frame_server_abs_ms | provider_start_duration_ms | first_pcm_sent_to_provider_abs_ms | first_provider_result_abs_ms | first_asr_partial_abs_ms | asr_final_abs_ms | error_code | provider_log_id |",
            "| --- | --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for record in records:
        lines.append(
            "| {provider} | {term} | {repeat} | {hit} | {text} | {first_frame} | {start} | {sent} | {first_result} | {partial} | {final} | {error} | {log_id} |".format(
                provider=record.get("provider") or "",
                term=record.get("term") or "",
                repeat=record.get("repeat_index"),
                hit="Y" if record.get("term_hit") else "N",
                text=str(record.get("recognized_text") or "").replace("|", "\\|"),
                first_frame=record.get("first_frame_server_abs_ms"),
                start=record.get("provider_start_duration_ms"),
                sent=record.get("first_pcm_sent_to_provider_abs_ms"),
                first_result=record.get("first_provider_result_abs_ms"),
                partial=record.get("first_asr_partial_abs_ms"),
                final=record.get("asr_final_abs_ms"),
                error=record.get("error_code") or "",
                log_id=record.get("provider_log_id") or "",
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio-dir", default="/tmp/volc_asr_eval")
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--providers", default="dashscope,volcengine")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--frame-ms", type=int, default=60)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--output", default="/tmp/v5_asr_only_repeat_eval.jsonl")
    parser.add_argument("--markdown", default="/tmp/v5_asr_only_repeat_eval.md")
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
