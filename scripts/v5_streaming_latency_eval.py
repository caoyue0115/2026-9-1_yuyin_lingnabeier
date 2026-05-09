from __future__ import annotations

import argparse
import json
import statistics
import sys
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

TIMELINE_FIELDS = [
    "first_frame_server_abs_ms",
    "first_pcm_to_asr_abs_ms",
    "first_asr_partial_abs_ms",
    "asr_final_abs_ms",
    "retrieval_done_abs_ms",
    "first_llm_chunk_abs_ms",
    "first_tts_chunk_abs_ms",
    "first_audio_byte_abs_ms",
    "done_abs_ms",
]


def _normalize_ms(value: Any, base_ms: int | None) -> int | None:
    if value is None:
        return None
    if base_ms is None:
        return int(value)
    return max(0, int(value) - base_ms)


def _nested_get(payload: dict, key: str) -> Any:
    if key in payload:
        return payload.get(key)
    trace = payload.get("trace")
    if isinstance(trace, dict):
        return trace.get(key)
    return None


def _term_hit(term: str, text: str | None) -> bool:
    return bool(term and text and term in text)


def build_streaming_latency_record(
    *,
    term: str,
    audio_path: str,
    done_payload: dict,
    status_payload: dict | None,
    asr_provider: str = "dashscope",
) -> dict:
    status_payload = status_payload or {}
    trace = status_payload.get("trace") if isinstance(status_payload.get("trace"), dict) else {}
    first_frame_base_ms = done_payload.get("first_frame_server_abs_ms")
    question_text = status_payload.get("question_text") or done_payload.get("question_text")
    answer_text = status_payload.get("answer_text") or ""
    provider = done_payload.get("asr_provider") or trace.get("asr_provider") or asr_provider
    asr_log_id = (
        done_payload.get("asr_log_id")
        or trace.get("asr_log_id")
        or done_payload.get("realtime_asr_request_id")
        or trace.get("realtime_asr_request_id")
    )
    record = {
        "term": term,
        "audio_path": audio_path,
        "path_type": "streaming",
        "asr_provider": provider,
        "question_text": question_text,
        "recognized_text": question_text,
        "term_hit": _term_hit(term, question_text),
        "audio_duration_ms": trace.get("audio_duration_ms"),
        "answer_chars": len("".join(str(answer_text).split())) if answer_text else 0,
        "error_code": status_payload.get("error_code") or done_payload.get("error_code"),
        "error_message": status_payload.get("error_message") or done_payload.get("error_message"),
        "session_id": status_payload.get("session_id") or done_payload.get("session_id"),
        "asr_log_id": asr_log_id,
        "log_id": asr_log_id,
    }
    source_payload = dict(done_payload)
    source_payload.update(trace)
    for field in TIMELINE_FIELDS:
        record[field] = _normalize_ms(_nested_get(source_payload, field), first_frame_base_ms)
    return record


def build_error_record(
    *,
    term: str,
    audio_path: str,
    path_type: str,
    error_code: str,
    error_message: str,
    asr_provider: str = "dashscope",
) -> dict:
    record = {
        "term": term,
        "audio_path": audio_path,
        "path_type": path_type,
        "asr_provider": asr_provider,
        "question_text": None,
        "recognized_text": None,
        "term_hit": False,
        "audio_duration_ms": None,
        "answer_chars": 0,
        "error_code": error_code,
        "error_message": error_message,
        "session_id": None,
        "asr_log_id": None,
        "log_id": None,
    }
    for field in TIMELINE_FIELDS:
        record[field] = None
    return record


def discover_cases(audio_dir: str | Path) -> list[tuple[str, Path]]:
    base = Path(audio_dir)
    return [(term, base / filename) for term, filename in CASES if (base / filename).exists()]


def run_streaming_case(
    *,
    term: str,
    audio_path: Path,
    base_url: str,
    frame_ms: int,
    realtime: bool,
    timeout: float,
    status_timeout: float,
    poll_interval: float,
    max_polls: int,
    asr_provider: str,
) -> dict:
    try:
        done_payload = run_stream_smoke(
            audio_path,
            base_url=base_url,
            frame_ms=frame_ms,
            realtime=realtime,
            timeout=timeout,
            run_session_after_stream=False,
            run_asr=True,
            run_full_chain=True,
            asr_provider=asr_provider,
            poll_interval=poll_interval,
            max_polls=max_polls,
            status_timeout=status_timeout,
            emit_trace=False,
        )
    except Exception as exc:
        return build_error_record(
            term=term,
            audio_path=str(audio_path),
            path_type="streaming",
            error_code="smoke_failed",
            error_message=str(exc),
            asr_provider=asr_provider,
        )
    return build_streaming_latency_record(
        term=term,
        audio_path=str(audio_path),
        done_payload=done_payload,
        status_payload=done_payload.get("session_status") if isinstance(done_payload.get("session_status"), dict) else None,
        asr_provider=asr_provider,
    )


def _providers_from_args(args: argparse.Namespace) -> list[str]:
    if args.provider_matrix:
        providers = [provider.strip() for provider in args.provider_matrix.split(",") if provider.strip()]
    else:
        providers = [args.asr_provider]
    valid = {"dashscope", "volcengine"}
    invalid = [provider for provider in providers if provider not in valid]
    if invalid:
        raise ValueError(f"invalid ASR provider(s): {', '.join(invalid)}")
    return providers


def run_eval(args: argparse.Namespace) -> list[dict]:
    records: list[dict] = []
    cases = discover_cases(args.audio_dir)
    providers = _providers_from_args(args)
    for term, audio_path in cases:
        for asr_provider in providers:
            if args.target in {"streaming", "both"}:
                records.append(
                    run_streaming_case(
                        term=term,
                        audio_path=audio_path,
                        base_url=args.base_url.rstrip("/"),
                        frame_ms=args.frame_ms,
                        realtime=args.realtime,
                        timeout=args.timeout,
                        status_timeout=args.status_timeout,
                        poll_interval=args.poll_interval,
                        max_polls=args.max_polls,
                        asr_provider=asr_provider,
                    )
                )
            if args.target in {"body", "both"}:
                records.append(
                    build_error_record(
                        term=term,
                        audio_path=str(audio_path),
                        path_type="body",
                        error_code="body_target_not_implemented",
                        error_message="P1.5 only runs the streaming path",
                        asr_provider=asr_provider,
                    )
                )
    return records


def write_jsonl(records: list[dict], output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as writer:
        for record in records:
            writer.write(json.dumps(record, ensure_ascii=False) + "\n")


def _mean(records: list[dict], key: str) -> float | None:
    values = [record[key] for record in records if isinstance(record.get(key), (int, float))]
    if not values:
        return None
    return round(statistics.mean(values), 1)


def write_markdown(records: list[dict], markdown_path: str | Path) -> None:
    path = Path(markdown_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ok_records = [record for record in records if not record.get("error_code")]
    hit_count = sum(1 for record in ok_records if record.get("term_hit"))
    providers = sorted({str(record.get("asr_provider") or "") for record in records if record.get("asr_provider")})
    lines = [
        "# v5 Streaming Latency Eval",
        "",
        "时间轴口径：表中 `*_abs_ms` 字段统一归一化为从客户端发送第一帧起算。服务端原始时间来自 stream accept 相对值，矩阵脚本用 `first_frame_server_abs_ms` 做零点平移。",
        "",
        "## Summary",
        "",
        f"- cases: {len(records)}",
        f"- providers: {', '.join(providers) if providers else 'N/A'}",
        f"- successful: {len(ok_records)}",
        f"- term_hits: {hit_count}/{len(ok_records) if ok_records else 0}",
        f"- mean_asr_final_abs_ms: {_mean(ok_records, 'asr_final_abs_ms')}",
        f"- mean_first_audio_byte_abs_ms: {_mean(ok_records, 'first_audio_byte_abs_ms')}",
        f"- mean_done_abs_ms: {_mean(ok_records, 'done_abs_ms')}",
        "",
        "## Details",
        "",
        "| term | provider | hit | asr_final_abs_ms | first_audio_byte_abs_ms | done_abs_ms | audio_duration_ms | answer_chars | error_code | session_id | log_id |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for record in records:
        lines.append(
            "| {term} | {provider} | {hit} | {asr} | {first_audio} | {done} | {audio_duration} | {answer_chars} | {error} | {session} | {log_id} |".format(
                term=record["term"],
                provider=record.get("asr_provider") or "",
                hit="Y" if record.get("term_hit") else "N",
                asr=record.get("asr_final_abs_ms"),
                first_audio=record.get("first_audio_byte_abs_ms"),
                done=record.get("done_abs_ms"),
                audio_duration=record.get("audio_duration_ms"),
                answer_chars=record.get("answer_chars"),
                error=record.get("error_code") or "",
                session=record.get("session_id") or "",
                log_id=record.get("log_id") or "",
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio-dir", default="/tmp/volc_asr_eval")
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--target", choices=["streaming", "body", "both"], default="streaming")
    parser.add_argument("--asr-provider", choices=["dashscope", "volcengine"], default="dashscope")
    parser.add_argument("--provider-matrix", default="")
    parser.add_argument("--output", default="/tmp/v5_streaming_latency_eval.jsonl")
    parser.add_argument("--markdown", default="/tmp/v5_streaming_latency_eval.md")
    parser.add_argument("--frame-ms", type=int, default=60)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--status-timeout", type=float, default=20.0)
    parser.add_argument("--poll-interval", type=float, default=0.3)
    parser.add_argument("--max-polls", type=int, default=120)
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
                "output": args.output,
                "markdown": args.markdown,
            },
            ensure_ascii=False,
        )
    )
    if any(record.get("error_code") for record in records):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
