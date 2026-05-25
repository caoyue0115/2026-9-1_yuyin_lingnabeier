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


def _load_gate_module():
    module_path = ROOT / "scripts" / "v6_n16r8_release_gate.py"
    spec = importlib.util.spec_from_file_location("v6_n16r8_release_gate", module_path)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load v6_n16r8_release_gate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class V6N16R8ReleaseGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name)
        self.artifact = self.tmp_path / "esp_idf_demo_v6_n16r8_004_ota_canary_002_20260522.bin"
        self.artifact.write_bytes(b"firmware-v6-n16r8-004")
        self.sha256 = hashlib.sha256(self.artifact.read_bytes()).hexdigest()
        self.gate = _load_gate_module()

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_artifact_gate_accepts_small_bin_with_expected_sha(self) -> None:
        exit_code = self.gate.main(
            [
                "--artifact",
                str(self.artifact),
                "--expected-sha256",
                self.sha256,
                "--expected-version",
                "v6-n16r8-004-ota-canary",
            ]
        )

        self.assertEqual(exit_code, 0)

    def test_artifact_gate_rejects_sha_mismatch(self) -> None:
        exit_code = self.gate.main(
            [
                "--artifact",
                str(self.artifact),
                "--expected-sha256",
                "0" * 64,
                "--expected-version",
                "v6-n16r8-004-ota-canary",
            ]
        )

        self.assertEqual(exit_code, 2)

    def test_log_gate_requires_v1_0_audio_and_non_empty_network_config(self) -> None:
        log = self.tmp_path / "boot.log"
        log.write_text(
            "\n".join(
                [
                    "I app_init: App version:      v6-n16r8-004-ota-canary",
                    "I esp_idf_demo: Board: ESP-VoCat v1.0",
                    "I esp_idf_demo:   board_rev=v1.0 target_profile=vocat_lowcost_16m8m "
                    "audio_pcb_rev=v1.0 audio_i2s_din_gpio=15 audio_pa_gpio=4 "
                    "audio_gpio48_enable=0",
                    "I esp_idf_demo:   wifi_ssid=GMT-G60",
                    "I esp_idf_demo:   server_base_url=http://106.54.240.51",
                    "I esp_idf_demo:   ota_boot_switch_enabled=1",
                    "I esp_idf_demo:   ota_rollback_validation_enabled=1",
                    "I esp_idf_demo: stage=ota_post_reboot_confirm event=success",
                ]
            ),
            encoding="utf-8",
        )

        exit_code = self.gate.main(
            [
                "--log",
                str(log),
                "--expected-version",
                "v6-n16r8-004-ota-canary",
                "--require-ota-success",
            ]
        )

        self.assertEqual(exit_code, 0)

    def test_log_gate_rejects_v1_2_audio_binding(self) -> None:
        log = self.tmp_path / "bad.log"
        log.write_text(
            "\n".join(
                [
                    "I app_init: App version:      v6-n16r8-004-ota-canary",
                    "I esp_idf_demo: Board: ESP-VoCat v1.0",
                    "I esp_idf_demo:   board_rev=v1.0 target_profile=vocat_lowcost_16m8m "
                    "audio_pcb_rev=v1.2 audio_i2s_din_gpio=3 audio_pa_gpio=15 "
                    "audio_gpio48_enable=1",
                    "I esp_idf_demo:   wifi_ssid=GMT-G60",
                    "I esp_idf_demo:   server_base_url=http://106.54.240.51",
                    "I esp_idf_demo:   ota_boot_switch_enabled=1",
                    "I esp_idf_demo:   ota_rollback_validation_enabled=1",
                ]
            ),
            encoding="utf-8",
        )

        exit_code = self.gate.main(
            [
                "--log",
                str(log),
                "--expected-version",
                "v6-n16r8-004-ota-canary",
            ]
        )

        self.assertEqual(exit_code, 2)

    def test_manifest_gate_requires_002_update_and_blocks_003_004(self) -> None:
        def fake_read_json_url(url: str, timeout_sec: float) -> dict:
            del timeout_sec
            if "miaoban-v1p2-002" in url:
                return {
                    "device_id": "miaoban-v1p2-002",
                    "updates": [
                        {
                            "release_id": "2026-05-22-v6-n16r8-004-002-p3d",
                            "version": "v6-n16r8-004-ota-canary",
                            "artifact": self.artifact.name,
                            "sha256": self.sha256,
                            "size": self.artifact.stat().st_size,
                            "min_version": "v6-n16r8-002-ota-baseline",
                        }
                    ],
                }
            return {"updates": []}

        with mock.patch.object(self.gate, "_read_json_url", side_effect=fake_read_json_url):
            exit_code = self.gate.main(
                [
                    "--artifact",
                    str(self.artifact),
                    "--expected-sha256",
                    self.sha256,
                    "--expected-version",
                    "v6-n16r8-004-ota-canary",
                    "--expected-release-id",
                    "2026-05-22-v6-n16r8-004-002-p3d",
                    "--manifest-base-url",
                    "http://106.54.240.51",
                ]
            )

        self.assertEqual(exit_code, 0)

    def test_manifest_gate_can_verify_allowed_device_has_consumed_release(self) -> None:
        def fake_read_json_url(url: str, timeout_sec: float) -> dict:
            del url, timeout_sec
            return {"updates": []}

        with mock.patch.object(self.gate, "_read_json_url", side_effect=fake_read_json_url):
            exit_code = self.gate.main(
                [
                    "--artifact",
                    str(self.artifact),
                    "--expected-sha256",
                    self.sha256,
                    "--expected-version",
                    "v6-n16r8-004-ota-canary",
                    "--expected-release-id",
                    "2026-05-22-v6-n16r8-004-002-p3d",
                    "--manifest-base-url",
                    "http://106.54.240.51",
                    "--allowed-device-mode",
                    "no-update",
                ]
            )

        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
