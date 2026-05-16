from __future__ import annotations

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

from fastapi import HTTPException

from src.api import ota as ota_api
from src.settings import settings
from src.storage import db as storage_db


class OtaApiTests(unittest.TestCase):
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

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.tmpdir.cleanup()

    def test_manifest_without_release_returns_empty_updates(self) -> None:
        response = ota_api.get_ota_manifest(
            device_id="esp32s3-demo-001",
            board="esp32s3",
            app_version="v26",
        )

        self.assertEqual(
            response,
            {"device_id": "esp32s3-demo-001", "poll_interval_sec": 3600, "updates": []},
        )

    def test_manifest_returns_first_whitelisted_release(self) -> None:
        storage_db.create_ota_release(
            release_id="2026-05-15-v28",
            target="esp32s3",
            version="v28",
            artifact_name="esp32s3_v28.bin",
            sha256="b" * 64,
            size=456,
            min_version="v25",
            device_ids=["esp32s3-demo-001"],
            priority=20,
            notes="second matching release",
        )
        storage_db.create_ota_release(
            release_id="2026-05-15-v27",
            target="esp32s3",
            version="v27",
            artifact_name="esp32s3_v27.bin",
            sha256="a" * 64,
            size=123,
            min_version="v25",
            device_ids=["esp32s3-demo-001"],
            priority=10,
            notes="first matching release",
        )

        payload = ota_api.get_ota_manifest(
            device_id="esp32s3-demo-001",
            board="esp32s3",
            app_version="v26",
        )

        self.assertEqual(payload["device_id"], "esp32s3-demo-001")
        self.assertEqual(len(payload["updates"]), 1)
        self.assertEqual(payload["updates"][0]["release_id"], "2026-05-15-v27")
        self.assertEqual(payload["updates"][0]["artifact"], "esp32s3_v27.bin")
        self.assertEqual(payload["updates"][0]["url"], "http://testserver/api/v5/ota/firmware/esp32s3_v27.bin")

    def test_manifest_ignores_non_whitelisted_release(self) -> None:
        storage_db.create_ota_release(
            release_id="2026-05-15-v27",
            target="esp32s3",
            version="v27",
            artifact_name="esp32s3_v27.bin",
            sha256="a" * 64,
            size=123,
            min_version="v25",
            device_ids=["another-device"],
            priority=10,
        )

        response = ota_api.get_ota_manifest(
            device_id="esp32s3-demo-001",
            board="esp32s3",
            app_version="v26",
        )

        self.assertEqual(response["updates"], [])

    def test_firmware_rejects_path_traversal(self) -> None:
        (self.tmp_path / "secret.bin").write_bytes(b"secret")

        with self.assertRaises(HTTPException) as cm:
            ota_api.get_ota_firmware("../secret.bin")
        self.assertEqual(cm.exception.status_code, 404)

    def test_report_can_be_submitted(self) -> None:
        response = ota_api.submit_ota_report(
            ota_api.OtaReportRequest(
                device_id="esp32s3-demo-001",
                target="esp32s3",
                from_version="v26",
                to_version="v27",
                release_id="2026-05-15-v27",
                stage="installed",
                ok=True,
                error_code=None,
                error_message=None,
                free_heap=123456,
                rssi=-55,
            )
        )

        self.assertEqual(response["status"], "accepted")
        report = storage_db.fetch_latest_ota_report("esp32s3-demo-001")
        self.assertIsNotNone(report)
        self.assertEqual(report["stage"], "installed")
        self.assertEqual(report["ok"], 1)


if __name__ == "__main__":
    unittest.main()
