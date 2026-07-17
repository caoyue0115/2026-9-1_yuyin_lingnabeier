from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / ".agents" / "skills" / "religion-v6-n16r8-ota-release"


class RepoOtaSkillTests(unittest.TestCase):
    def test_skill_requires_an_explicit_user_ota_request(self) -> None:
        skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        frontmatter = skill.split("---", 2)[1].lower()
        body = skill.split("---", 2)[2].lower()

        self.assertIn("only when the user explicitly requests", frontmatter)
        self.assertIn("do not use for ordinary", frontmatter)
        self.assertIn("## activation gate", body)
        self.assertIn("do not infer ota intent", body)
        self.assertIn("prior ota authorization does not carry forward", body)

    def test_skill_uses_only_current_v1_0_release_sources(self) -> None:
        skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("docs/deploy/v6-n16r8-release-handoff-20260522.md", skill)
        self.assertIn("docs/deploy/greenunion-sh-ota-p3c-runbook.md", skill)
        self.assertNotIn("greenunion-sh-ota-*.md", skill)
        self.assertNotIn("greenunion-sh-ota-p3a-release-runbook.md", skill)
        self.assertNotIn("greenunion-sh-ota-p3b-runbook.md", skill)
        self.assertNotIn("next device", skill.lower())

    def test_skill_routes_gate_output_through_sanitizer(self) -> None:
        skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("scripts/run_gate.py", skill)
        self.assertIn("scripts/run_tests.py", skill)
        self.assertNotIn("python3 scripts/v6_n16r8_release_gate.py", skill)
        self.assertNotIn("http://106.54.240.51", skill)
        self.assertIn("<authorized-base-url>", skill)
        self.assertIn("gitleaks git", skill)
        self.assertIn("--redact", skill)
        self.assertNotIn(" \\\n", skill)

    def test_gate_wrapper_never_relays_subprocess_output(self) -> None:
        script_path = SKILL_DIR / "scripts" / "run_gate.py"
        spec = importlib.util.spec_from_file_location("repo_ota_gate", script_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        completed = SimpleNamespace(
            stdout=(
                "bare-secret sample-unit-008 captures/sample-unit-009/boot.log "
                "http://example.invalid/private\n"
            ),
            stderr="wifi_ssid=Private Network question_text=private question\n",
            returncode=7,
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        with mock.patch.object(module.subprocess, "run", return_value=completed):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = module.main(
                    [
                        "--artifact",
                        "dummy.bin",
                        "--expected-sha256",
                        "a" * 64,
                        "--expected-version",
                        "v6-n16r8-5-ota-canary",
                    ]
                )

        output = stdout.getvalue() + stderr.getvalue()
        self.assertEqual(exit_code, 7)
        self.assertEqual(output, "gate_result=fail exit_code=7\n")

    def test_safe_test_runner_uses_fixed_focused_suite(self) -> None:
        runner = (SKILL_DIR / "scripts" / "run_tests.py").read_text(encoding="utf-8")

        self.assertIn("tests/test_v6_n16r8_release_gate.py", runner)
        self.assertIn("tests/test_ota_release_cli.py", runner)
        self.assertIn("tests/test_ota_release_closeout_cli.py", runner)
        self.assertIn("tests/test_ota_api.py", runner)
        self.assertIn("--tb=no", runner)
        self.assertIn("TemporaryDirectory", runner)
        self.assertIn("focused_tests=pass", runner)
        self.assertNotIn("completed.stdout", runner)
        self.assertNotIn("completed.stderr", runner)

    def test_gate_wrapper_sanitizes_subprocess_output_and_preserves_exit(self) -> None:
        script_path = SKILL_DIR / "scripts" / "run_gate.py"
        spec = importlib.util.spec_from_file_location("repo_ota_gate_subprocess", script_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        completed = SimpleNamespace(stdout="private", stderr="private", returncode=0)
        stdout = io.StringIO()
        stderr = io.StringIO()

        with mock.patch.object(module.subprocess, "run", return_value=completed):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = module.main(
                    ["--artifact", "dummy.bin", "--expected-version", "test"]
                )

        output = stdout.getvalue() + stderr.getvalue()
        self.assertEqual(exit_code, 2)
        self.assertEqual(output, "gate_error=invalid_version\n")

    def test_gate_wrapper_rejects_noop_invocation(self) -> None:
        script_path = SKILL_DIR / "scripts" / "run_gate.py"
        spec = importlib.util.spec_from_file_location("repo_ota_gate_noop", script_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        stderr = io.StringIO()

        with mock.patch.object(module.subprocess, "run") as run:
            with redirect_stderr(stderr):
                exit_code = module.main(
                    ["--expected-version", "v6-n16r8-5-ota-canary"]
                )

        self.assertEqual(exit_code, 2)
        run.assert_not_called()
        self.assertIn("gate_error=no_check_selected", stderr.getvalue())

    def test_gate_wrapper_rejects_empty_selector_and_hides_invalid_args(self) -> None:
        script_path = SKILL_DIR / "scripts" / "run_gate.py"
        spec = importlib.util.spec_from_file_location("repo_ota_gate_empty", script_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        for args, expected_error in (
            (
                [
                    "--manifest-base-url=",
                    "--expected-version",
                    "v6-n16r8-5-ota-canary",
                ],
                "empty_manifest_base_url",
            ),
            (
                [
                    "--artifact",
                    "dummy.bin",
                    "--expected-version",
                    "v6-n16r8-5-ota-canary",
                    "--unknown-secret",
                    "top-secret",
                ],
                "invalid_arguments",
            ),
        ):
            stderr = io.StringIO()
            with self.subTest(expected_error=expected_error):
                with mock.patch.object(module.subprocess, "run") as run:
                    with redirect_stderr(stderr):
                        exit_code = module.main(args)
                self.assertEqual(exit_code, 2)
                run.assert_not_called()
                self.assertIn(f"gate_error={expected_error}", stderr.getvalue())
                self.assertNotIn("top-secret", stderr.getvalue())

    def test_gate_wrapper_rejects_release_guard_overrides(self) -> None:
        script_path = SKILL_DIR / "scripts" / "run_gate.py"
        spec = importlib.util.spec_from_file_location("repo_ota_gate_guards", script_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with mock.patch.object(module.subprocess, "run") as run:
            exit_code = module.main(
                [
                    "--artifact",
                    "dummy.bin",
                    "--expected-sha256",
                    "a" * 64,
                    "--expected-version",
                    "v6-n16r8-5-ota-canary",
                    "--max-bytes",
                    "9999999",
                ]
            )

        self.assertEqual(exit_code, 2)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
