from __future__ import annotations

from pathlib import Path

import pytest

from src.rag.crawler import _extract_html, _validate_source_url


def test_extract_html_omits_script_and_keeps_visible_text() -> None:
    title, text = _extract_html(
        b"<html><title>Disney Test</title><script>secret()</script><body>LinaBell and Duffy</body></html>",
        "fallback",
    )
    assert title == "Disney Test"
    assert "LinaBell and Duffy" in text
    assert "secret" not in text


def test_source_allowlist_accepts_official_domains_only() -> None:
    _validate_source_url("https://movies.disney.com/zootopia")
    _validate_source_url("https://www.shanghaidisneyresort.com/zh-cn/characters")
    with pytest.raises(ValueError):
        _validate_source_url("https://example.com/copied-disney-content")
