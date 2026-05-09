from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tests._stubs import install_dependency_stubs

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

install_dependency_stubs()


class LlmProviderTests(unittest.TestCase):
    def test_default_llm_model_uses_flash_model(self) -> None:
        from src.settings import Settings

        self.assertEqual(Settings().llm_model, "qwen3.5-flash-2026-02-23")

    def test_build_messages_instructs_definition_and_core_idea_style(self) -> None:
        from src.providers.llm import _build_messages

        messages = _build_messages(
            "什么是无相",
            [{"source_title": "金刚经", "snippet": "凡所有相，皆是虚妄"}],
        )

        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("定义", messages[0]["content"])
        self.assertIn("核心思想", messages[0]["content"])
        self.assertIn("40字", messages[0]["content"])
        self.assertIn("不要把“根据某法师", messages[0]["content"])
        self.assertEqual(messages[1]["role"], "user")
        self.assertIn("先给一句定义", messages[1]["content"])
        self.assertIn("第二句补核心思想", messages[1]["content"])
        self.assertIn("问题：什么是无相", messages[1]["content"])
        self.assertIn("金刚经", messages[1]["content"])

    def test_stream_answer_disables_thinking_for_dashscope_flash_model(self) -> None:
        from src.providers import llm

        captured_kwargs: dict = {}

        class FakeCompletions:
            def create(self, **kwargs):
                captured_kwargs.update(kwargs)
                chunk = SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="无相即离相。"))]
                )
                return iter([chunk])

        fake_client = SimpleNamespace(
            chat=SimpleNamespace(completions=FakeCompletions())
        )

        with patch.object(llm, "_build_client", return_value=fake_client):
            chunks = list(llm.stream_answer_text("什么是无相", []))

        self.assertEqual(chunks, ["无相即离相。"])
        self.assertEqual(captured_kwargs["model"], "qwen3.5-flash-2026-02-23")
        self.assertEqual(captured_kwargs["extra_body"], {"enable_thinking": False})
        self.assertTrue(captured_kwargs["stream"])


if __name__ == "__main__":
    unittest.main()
