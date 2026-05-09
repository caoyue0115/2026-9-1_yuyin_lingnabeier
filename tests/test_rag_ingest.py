from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests._stubs import install_dependency_stubs

install_dependency_stubs()

from src.rag import ingest


class RagIngestTests(unittest.TestCase):
    def test_should_ingest_only_curated_prefixes_by_default(self) -> None:
        self.assertTrue(ingest.should_ingest_file(Path("ZT02_阿弥陀佛是谁_大白话版.md")))
        self.assertTrue(ingest.should_ingest_file(Path("BT02_佛法到底在讲什么_大白话版.md")))
        self.assertFalse(ingest.should_ingest_file(Path("ZT35_净土专题总索引.md")))
        self.assertFalse(ingest.should_ingest_file(Path("ZT36_RAG召回优先级与偏差防护清单.md")))
        self.assertTrue(ingest.should_ingest_file(Path("金刚经.md")))
        self.assertFalse(ingest.should_ingest_file(Path("金刚经讲记_圣严法师.md")))
        self.assertFalse(ingest.should_ingest_file(Path("金刚顶经.pdf")))

    def test_collect_doc_units_skips_legacy_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_dir = Path(tmpdir)
            (kb_dir / "ZT02_阿弥陀佛是谁_大白话版.md").write_text("# ok\n阿弥陀佛是极乐世界教主。", encoding="utf-8")
            (kb_dir / "BT02_佛法到底在讲什么_大白话版.md").write_text("# ok\n佛法帮助人离苦得乐。", encoding="utf-8")
            (kb_dir / "金刚经.md").write_text("# legacy\n应无所住而生其心。", encoding="utf-8")
            (kb_dir / "BT12_金刚经讲记导读_圣严法师整理版.md").write_text("# guide\n《金刚经》也可落在现实修行。", encoding="utf-8")
            (kb_dir / "金刚经讲记_圣严法师.md").write_text("# full\n很长的原始讲记。", encoding="utf-8")
            (kb_dir / "ZT35_净土专题总索引.md").write_text("# control\n仅供索引。", encoding="utf-8")
            (kb_dir / "金刚顶经.pdf").write_bytes(b"%PDF-1.4\n")

            units = ingest.collect_doc_units(kb_dir)

        titles = sorted(unit["source_title"] for unit in units)
        self.assertEqual(
            titles,
            [
                "BT02_佛法到底在讲什么_大白话版.md",
                "BT12_金刚经讲记导读_圣严法师整理版.md",
                "ZT02_阿弥陀佛是谁_大白话版.md",
                "金刚经.md",
            ],
        )


if __name__ == "__main__":
    unittest.main()
