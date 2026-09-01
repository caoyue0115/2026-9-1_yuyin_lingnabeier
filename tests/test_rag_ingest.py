from __future__ import annotations

import sys
import tempfile
import unittest
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests._stubs import install_dependency_stubs

install_dependency_stubs()

from src.rag import ingest


class RagIngestTests(unittest.TestCase):
    def test_should_ingest_supported_disney_source_formats(self) -> None:
        for name in ("linabell.json", "duffy.md", "zootopia.txt", "shanghai-disney.pdf"):
            self.assertTrue(ingest.should_ingest_file(Path(name)))
        self.assertFalse(ingest.should_ingest_file(Path(".crawler-state.json")))
        self.assertFalse(ingest.should_ingest_file(Path("park-hours.csv")))

    def test_collect_doc_units_preserves_source_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_dir = Path(tmpdir)
            (kb_dir / "official.json").write_text(
                json.dumps(
                    {
                        "title": "玲娜贝儿官方角色介绍",
                        "url": "https://example.disney/linabell",
                        "fetched_at": "2026-09-01T00:00:00Z",
                        "text": "玲娜贝儿是一只爱探索的粉色小狐狸。",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (kb_dir / "duffy.md").write_text("# 达菲\n达菲是米奇的泰迪熊。", encoding="utf-8")
            (kb_dir / ".crawler-state.json").write_text("{}", encoding="utf-8")
            (kb_dir / "ignore.csv").write_text("not,indexed", encoding="utf-8")

            units = ingest.collect_doc_units(kb_dir)

        titles = sorted(unit["source_title"] for unit in units)
        self.assertEqual(titles, ["duffy.md", "玲娜贝儿官方角色介绍"])
        official = next(unit for unit in units if unit["source_title"] == "玲娜贝儿官方角色介绍")
        self.assertEqual(official["source_url"], "https://example.disney/linabell")
        self.assertEqual(official["fetched_at"], "2026-09-01T00:00:00Z")


if __name__ == "__main__":
    unittest.main()
