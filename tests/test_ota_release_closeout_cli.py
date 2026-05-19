from __future__ import annotations

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
    module_path = ROOT / "scripts" / "ota_release_closeout.py"
    spec = importlib.util.spec_from_file_location("ota_release_closeout", module_path)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load ota_release_closeout.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OtaReleaseCloseoutCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name)
        self.patchers = [
            mock.patch.object(settings, "sqlite_path", str(self.tmp_path / "ota.db")),
            mock.patch.object(settings, "public_base_url", "http://testserver"),
            mock.patch.object(settings, "ota_artifact_dir", str(self.tmp_path / "ota_artifacts"), create=True),
        ]
        for patcher in self.patchers:
            patcher.start()
        storage_db.init_db()
        storage_db.create_ota_release(
            release_id="2026-05-19-v35-002-p3c",
            target="esp32s3",
            version="v35",
            artifact_name="esp_idf_demo_v35.bin",
            sha256="d" * 64,
            size=1234,
            min_version="1",
            device_ids=["miaoban-v1p2-002"],
            enabled=True,
            board="ESP-VoCat",
            hw_rev="v1.2",
            priority=1,
            notes="P3c closeout test",
        )

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.tmpdir.cleanup()

    def _record_report(self, stage: str, ok: bool = True) -> None:
        storage_db.record_ota_report(
            {
                "device_id": "miaoban-v1p2-002",
                "target": "esp32s3",
                "from_version": "1",
                "to_version": "v35",
                "release_id": "2026-05-19-v35-002-p3c",
                "stage": stage,
                "ok": ok,
            }
        )

    def test_closeout_disables_release_after_required_success_reports(self) -> None:
        self._record_report("partition_write")
        self._record_report("boot_switch_scheduled")
        self._record_report("post_reboot_confirm")
        cli = _load_cli_module()

        exit_code = cli.main(["--release-id", "2026-05-19-v35-002-p3c", "--device-id", "miaoban-v1p2-002"])

        self.assertEqual(exit_code, 0)
        payload = ota_api.get_ota_manifest(
            device_id="miaoban-v1p2-002",
            board="ESP-VoCat",
            hw_rev="v1.2",
            app_version="v35",
        )
        self.assertEqual(payload["updates"], [])

    def test_closeout_rejects_missing_post_reboot_confirm(self) -> None:
        self._record_report("partition_write")
        self._record_report("boot_switch_scheduled")
        cli = _load_cli_module()

        exit_code = cli.main(["--release-id", "2026-05-19-v35-002-p3c", "--device-id", "miaoban-v1p2-002"])

        self.assertEqual(exit_code, 2)


if __name__ == "__main__":
    unittest.main()
