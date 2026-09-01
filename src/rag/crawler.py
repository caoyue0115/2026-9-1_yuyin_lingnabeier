from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests
from pypdf import PdfReader

USER_AGENT = "DisneyVoiceAssistantDemo/1.0 (+internal RAG prototype)"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALLOWED_HOST_SUFFIXES = (
    "disney.com",
    "shanghaidisneyresort.com",
    "hongkongdisneyland.com",
    "tokyodisneyresort.jp",
)


def _clean_text(text: str) -> str:
    lines = [re.sub(r"[ \t]{2,}", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


class VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._hidden_depth = 0
        self.title = ""
        self._in_title = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style", "noscript", "svg"}:
            self._hidden_depth += 1
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._hidden_depth:
            self._hidden_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._hidden_depth:
            return
        normalized = re.sub(r"\s+", " ", data).strip()
        if not normalized:
            return
        if self._in_title:
            self.title = f"{self.title} {normalized}".strip()
        self.parts.append(normalized)


def _validate_source_url(url: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not any(host == suffix or host.endswith(f".{suffix}") for suffix in ALLOWED_HOST_SUFFIXES):
        raise ValueError(f"source is not on the official Disney allowlist: {url}")


def _robots_allows(session: requests.Session, url: str, timeout: float) -> bool:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        response = session.get(robots_url, timeout=timeout)
    except requests.RequestException:
        return True
    if response.status_code == 404:
        return True
    if response.status_code >= 400:
        return False
    parser = RobotFileParser()
    parser.set_url(robots_url)
    parser.parse(response.text.splitlines())
    return parser.can_fetch(USER_AGENT, url)


def _extract_html(content: bytes, fallback_title: str) -> tuple[str, str]:
    parser = VisibleTextParser()
    parser.feed(content.decode("utf-8", errors="ignore"))
    text = _clean_text("\n".join(parser.parts))
    return parser.title or fallback_title, text


def _extract_pdf(content: bytes, fallback_title: str) -> tuple[str, str]:
    reader = PdfReader(BytesIO(content))
    pages = [_clean_text(page.extract_text() or "") for page in reader.pages]
    return fallback_title, _clean_text("\n".join(page for page in pages if page))


def crawl_source(session: requests.Session, source: dict, *, timeout: float = 20.0) -> dict:
    url = str(source["url"])
    _validate_source_url(url)
    if not _robots_allows(session, url, timeout):
        raise PermissionError(f"robots.txt disallows crawling: {url}")

    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    fallback_title = str(source.get("title") or source.get("id") or url)
    source_format = str(source.get("format") or "html").lower()
    if source_format == "pdf":
        extracted_title, text = _extract_pdf(response.content, fallback_title)
    elif source_format == "html":
        extracted_title, text = _extract_html(response.content, fallback_title)
    else:
        raise ValueError(f"unsupported source format: {source_format}")

    max_chars = int(source.get("max_chars") or 30000)
    text = text[:max_chars].strip()
    if len(text) < 80:
        raise ValueError(f"source did not yield enough text: {url}")
    return {
        "id": str(source["id"]),
        "title": fallback_title or extracted_title,
        "page_title": extracted_title,
        "url": url,
        "fetched_at": datetime.now(UTC).isoformat(),
        "text": text,
    }


def crawl_manifest(manifest_path: Path, output_dir: Path, *, timeout: float = 20.0) -> dict:
    sources = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(sources, list):
        raise ValueError("source manifest must be a JSON array")
    output_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7"})
    completed: list[dict] = []
    failed: list[dict] = []
    for source in sources:
        try:
            record = crawl_source(session, source, timeout=timeout)
            destination = output_dir / f"{record['id']}.json"
            destination.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            completed.append({"id": record["id"], "path": str(destination), "chars": len(record["text"])})
        except Exception as exc:
            failed.append({"id": str(source.get("id") or "unknown"), "error": str(exc)})
    return {"completed": completed, "failed": failed}


def main() -> None:
    parser = argparse.ArgumentParser(description="Crawl allowlisted official Disney sources for the local RAG index")
    parser.add_argument("--manifest", type=Path, default=PROJECT_ROOT / "config" / "disney_sources.json")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "data" / "disney" / "crawled")
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()
    print(json.dumps(crawl_manifest(args.manifest, args.output, timeout=args.timeout), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
