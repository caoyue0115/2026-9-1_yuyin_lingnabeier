from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.settings import settings


def default_hotwords_path() -> Path:
    return ROOT / "config" / "asr_hotwords.buddhism.json"


def load_hotwords(path: str | Path) -> list[dict]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("hotword file must be a JSON array")
    return payload


def build_summary(vocabulary_id: str, target_model: str, hotwords: list[dict]) -> dict:
    return {
        "vocabulary_id": vocabulary_id,
        "target_model": target_model,
        "count": len(hotwords),
        "sample_terms": [item["text"] for item in hotwords[:5]],
    }


def _configure_dashscope_sdk() -> None:
    import dashscope

    dashscope.api_key = settings.dashscope_api_key
    if hasattr(dashscope, "base_http_api_url") and settings.dashscope_base_url:
        dashscope.base_http_api_url = settings.dashscope_base_url.rstrip("/") + "/api/v1"


def create_or_update_vocabulary(
    hotwords: list[dict],
    *,
    target_model: str,
    prefix: str,
    vocabulary_id: str | None,
) -> str:
    _configure_dashscope_sdk()
    from dashscope.audio.asr import VocabularyService

    service = VocabularyService()
    if vocabulary_id:
        service.update_vocabulary(vocabulary_id=vocabulary_id, vocabulary=hotwords)
        return vocabulary_id
    return service.create_vocabulary(target_model=target_model, prefix=prefix, vocabulary=hotwords)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hotwords", default=str(default_hotwords_path()))
    parser.add_argument("--target-model", default=settings.asr_model)
    parser.add_argument("--prefix", default="buddhaasr")
    parser.add_argument("--vocabulary-id")
    args = parser.parse_args()

    hotwords = load_hotwords(args.hotwords)
    vocabulary_id = create_or_update_vocabulary(
        hotwords,
        target_model=args.target_model,
        prefix=args.prefix,
        vocabulary_id=args.vocabulary_id,
    )
    summary = build_summary(vocabulary_id, args.target_model, hotwords)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"ASR_VOCABULARY_ID={vocabulary_id}")


if __name__ == "__main__":
    main()
