from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests._stubs import install_dependency_stubs

install_dependency_stubs()

from src import app as app_module


class HealthzTests(unittest.TestCase):
    def test_healthz_includes_asr_status(self) -> None:
        with mock.patch.object(app_module, "sqlite_ok", return_value=True), mock.patch.object(
            app_module, "asr_health", return_value=True
        ), mock.patch.object(app_module, "llm_health", return_value=True), mock.patch.object(
            app_module, "tts_health", return_value=False
        ), mock.patch("src.app.Redis.from_url") as redis_from_url:
            redis_from_url.return_value.ping.return_value = True
            response = app_module.healthz()

        self.assertEqual(response.api, "ok")
        self.assertEqual(response.redis, "ok")
        self.assertEqual(response.sqlite, "ok")
        self.assertEqual(response.asr, "ok")
        self.assertEqual(response.llm, "ok")
        self.assertEqual(response.tts, "down")


if __name__ == "__main__":
    unittest.main()
