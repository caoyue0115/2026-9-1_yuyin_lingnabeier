from __future__ import annotations

import hashlib
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests._stubs import install_dependency_stubs

install_dependency_stubs()

from src.api import ota as ota_api
from src.settings import settings
from src.storage import db as storage_db


def _load_cli_module():
    module_path = ROOT / "scripts" / "ota_release_create.py"
    spec = importlib.util.spec_from_file_location("ota_release_create", module_path)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load ota_release_create.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OtaReleaseCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name)
        self.artifact_dir = self.tmp_path / "ota_artifacts"
        self.artifact_dir.mkdir()
        self.patchers = [
            mock.patch.object(settings, "sqlite_path", str(self.tmp_path / "ota.db")),
            mock.patch.object(settings, "public_base_url", "http://testserver"),
            mock.patch.object(settings, "ota_artifact_dir", str(self.artifact_dir), create=True),
        ]
        for patcher in self.patchers:
            patcher.start()
        storage_db.init_db()

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.tmpdir.cleanup()

    def test_cli_creates_release_from_artifact_and_manifest_returns_it(self) -> None:
        artifact = self.artifact_dir / "esp_idf_demo_v30.bin"
        artifact_bytes = b"firmware-v30"
        artifact.write_bytes(artifact_bytes)
        expected_sha = hashlib.sha256(artifact_bytes).hexdigest()
        cli = _load_cli_module()

        exit_code = cli.main(
            [
                "--release-id",
                "2026-05-17-v30",
                "--version",
                "v30",
                "--artifact",
                str(artifact),
                "--device-id",
                "miaoban-v1p2-001",
                "--board",
                "ESP-VoCat",
                "--hw-rev",
                "v1.2",
                "--min-version",
                "1",
                "--priority",
                "10",
                "--notes",
                "P3a test release",
            ]
        )

        self.assertEqual(exit_code, 0)
        payload = ota_api.get_ota_manifest(
            device_id="miaoban-v1p2-001",
            board="ESP-VoCat",
            hw_rev="v1.2",
            app_version="1",
        )
        self.assertEqual(len(payload["updates"]), 1)
        update = payload["updates"][0]
        self.assertEqual(update["release_id"], "2026-05-17-v30")
        self.assertEqual(update["artifact"], "esp_idf_demo_v30.bin")
        self.assertEqual(update["size"], len(artifact_bytes))
        self.assertEqual(update["sha256"], expected_sha)

    def test_cli_rejects_artifact_outside_ota_artifact_dir(self) -> None:
        artifact = self.tmp_path / "outside.bin"
        artifact.write_bytes(b"outside")
        cli = _load_cli_module()

        exit_code = cli.main(
            [
                "--release-id",
                "bad",
                "--version",
                "v30",
                "--artifact",
                str(artifact),
                "--device-id",
                "miaoban-v1p2-001",
            ]
        )

        self.assertEqual(exit_code, 2)


if __name__ == "__main__":
    unittest.main()
