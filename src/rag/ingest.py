from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import faiss

from pypdf import PdfReader

from src.rag.retriever import HashingEmbedder, clean_text, index_paths, split_text, to_float32_matrix, tokenize_zh
from src.settings import settings

ALLOWED_EXTS = {".json", ".md", ".txt", ".pdf"}


def extract_pdf_units(fp: Path) -> list[dict[str, Any]]:
    reader = PdfReader(str(fp))
    units: list[dict[str, Any]] = []
    for i, page in enumerate(reader.pages, start=1):
        text = clean_text(page.extract_text() or "")
        if text:
            units.append({"source_file": str(fp), "source_title": fp.name, "page_no": i, "text": text})
    return units


def should_ingest_file(fp: Path) -> bool:
    return fp.suffix.lower() in ALLOWED_EXTS and not fp.name.startswith(".")


def _extract_json_units(fp: Path) -> list[dict[str, Any]]:
    payload = json.loads(fp.read_text(encoding="utf-8"))
    records = payload if isinstance(payload, list) else [payload]
    units: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        if record.get("index_enabled") is False:
            continue
        text = clean_text(str(record.get("text") or ""))
        if not text:
            continue
        units.append(
            {
                "source_file": str(fp),
                "source_title": str(record.get("title") or fp.stem),
                "source_url": str(record.get("url") or ""),
                "fetched_at": str(record.get("fetched_at") or ""),
                "knowledge_scope": str(record.get("knowledge_scope") or "disney_hearsay"),
                "page_no": record.get("page_no"),
                "text": text,
            }
        )
    return units


def collect_doc_units(base: Path | None = None) -> list[dict[str, Any]]:
    base = base or settings.kb_dir
    units: list[dict[str, Any]] = []
    for fp in sorted(base.rglob("*")):
        if not fp.is_file() or not should_ingest_file(fp):
            continue
        if fp.suffix.lower() == ".json":
            units.extend(_extract_json_units(fp))
            continue
        if fp.suffix.lower() == ".pdf":
            units.extend(extract_pdf_units(fp))
            continue
        text = clean_text(fp.read_text(encoding="utf-8", errors="ignore"))
        if text:
            units.append(
                {
                    "source_file": str(fp),
                    "source_title": fp.name,
                    "source_url": "",
                    "fetched_at": "",
                    "knowledge_scope": "disney_hearsay",
                    "page_no": None,
                    "text": text,
                }
            )
    return units


def ingest_disney_docs() -> dict[str, Any]:
    units = collect_doc_units()
    if not units:
        raise RuntimeError(f"no docs found under {settings.kb_dir}")
    chunks: list[dict[str, Any]] = []
    for unit in units:
        for i, part in enumerate(split_text(unit["text"], settings.chunk_size, settings.chunk_overlap)):
            indexed_text = f"{unit['source_title']}\n{part}"
            chunks.append(
                {
                    "chunk_id": len(chunks) + 1,
                    "source_file": unit["source_file"],
                    "source_title": unit["source_title"],
                    "source_url": unit.get("source_url", ""),
                    "fetched_at": unit.get("fetched_at", ""),
                    "knowledge_scope": unit.get("knowledge_scope", "disney_hearsay"),
                    "page_no": unit["page_no"],
                    "part": i,
                    "text": indexed_text,
                }
            )
    corpus = [x["text"] for x in chunks]
    tokenized = [tokenize_zh(x) for x in corpus]
    vecs = to_float32_matrix(HashingEmbedder(dim=settings.embedding_dim).encode(corpus, normalize_embeddings=True))
    index = faiss.IndexFlatIP(vecs.shape[1])
    index.add(vecs)
    settings.indices_dir.mkdir(parents=True, exist_ok=True)
    meta_file, faiss_file = index_paths()
    meta_file.write_text(
        json.dumps(
            {
                "domain": "disney",
                "chunks": chunks,
                "tokenized_corpus": tokenized,
                "chunk_size": settings.chunk_size,
                "chunk_overlap": settings.chunk_overlap,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    faiss.write_index(index, str(faiss_file))
    return {
        "domain": "disney",
        "docs": len({x["source_file"] for x in chunks}),
        "chunks": len(chunks),
        "meta_file": str(meta_file),
        "faiss_file": str(faiss_file),
    }


if __name__ == "__main__":
    print(json.dumps(ingest_disney_docs(), ensure_ascii=False, indent=2))
