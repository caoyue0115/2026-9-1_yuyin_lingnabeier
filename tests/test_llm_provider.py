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

    def test_build_messages_ground_disney_answers_in_references(self) -> None:
        from src.providers.llm import _build_messages

        messages = _build_messages(
            "玲娜贝儿是谁",
            [{"source_title": "玲娜贝儿角色介绍", "snippet": "玲娜贝儿是一只爱探索的粉色小狐狸。"}],
        )

        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("只能依据", messages[0]["content"])
        self.assertIn("不要编造", messages[0]["content"])
        self.assertIn("一到两句自然口语", messages[0]["content"])
        self.assertIn("不要声称自己代表迪士尼官方", messages[0]["content"])
        self.assertEqual(messages[1]["role"], "user")
        self.assertIn("像面对面聊天一样", messages[1]["content"])
        self.assertIn("必要时再补一句", messages[1]["content"])
        self.assertIn("问题：玲娜贝儿是谁", messages[1]["content"])
        self.assertIn("玲娜贝儿角色介绍", messages[1]["content"])

    def test_short_answer_mode_uses_stricter_length_prompt(self) -> None:
        from src.providers.llm import _build_messages

        messages = _build_messages(
            "达菲是谁",
            [{"source_title": "达菲角色介绍", "snippet": "达菲是米奇的泰迪熊。"}],
            answer_mode="short",
        )

        self.assertIn("一到两句", messages[0]["content"])
        self.assertIn("不超过70字", messages[0]["content"])
        self.assertIn("第一句就给答案", messages[0]["content"])
        self.assertIn("不要长篇解释", messages[0]["content"])
        self.assertIn("不超过70字", messages[1]["content"])

    def test_stream_answer_disables_thinking_for_dashscope_flash_model(self) -> None:
        from src.providers import llm

        captured_kwargs: dict = {}

        class FakeCompletions:
            def create(self, **kwargs):
                captured_kwargs.update(kwargs)
                chunk = SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="玲娜贝儿爱探索。"))]
                )
                return iter([chunk])

        fake_client = SimpleNamespace(
            chat=SimpleNamespace(completions=FakeCompletions())
        )

        with patch.object(llm, "_build_client", return_value=fake_client):
            chunks = list(llm.stream_answer_text("你好呀", []))

        self.assertEqual(chunks, ["玲娜贝儿爱探索。"])
        self.assertEqual(captured_kwargs["model"], "qwen3.5-flash-2026-02-23")
        self.assertEqual(captured_kwargs["extra_body"], {"enable_thinking": False})
        self.assertTrue(captured_kwargs["stream"])

    def test_stream_answer_short_mode_uses_fixed_smaller_max_tokens(self) -> None:
        from src.providers import llm

        captured_kwargs: dict = {}

        class FakeCompletions:
            def create(self, **kwargs):
                captured_kwargs.update(kwargs)
                chunk = SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="达菲是米奇的泰迪熊。"))]
                )
                return iter([chunk])

        fake_client = SimpleNamespace(
            chat=SimpleNamespace(completions=FakeCompletions())
        )

        with patch.object(llm, "_build_client", return_value=fake_client):
            chunks = list(llm.stream_answer_text("达菲是谁", [], answer_mode="short"))

        self.assertEqual(chunks, ["达菲是米奇的泰迪熊。"])
        self.assertLessEqual(captured_kwargs["max_tokens"], 96)
        self.assertIn("不超过70字", captured_kwargs["messages"][0]["content"])


if __name__ == "__main__":
    unittest.main()
