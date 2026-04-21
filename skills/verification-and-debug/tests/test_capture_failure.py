import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "capture_failure.py"
SPEC = importlib.util.spec_from_file_location("capture_failure", SCRIPT_PATH)
CAPTURE_FAILURE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(CAPTURE_FAILURE)


class CaptureFailureTests(unittest.TestCase):
    def test_build_report_classifies_missing_python_module_as_dependency_issue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report = CAPTURE_FAILURE.build_report(
                [
                    sys.executable,
                    "-c",
                    "import definitely_missing_module",
                ],
                Path(temp_dir),
                timeout=30,
                line_limit=10,
            )

        self.assertFalse(report["success"])
        self.assertEqual(report["classification"], "dependency")
        self.assertIn("modulenotfounderror", report["signals"])
        self.assertEqual(report["exit_code"], 1)
        self.assertTrue(any("依赖" in step for step in report["next_steps"]))

    def test_build_report_handles_missing_executable_as_environment_issue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report = CAPTURE_FAILURE.build_report(
                ["definitely-not-a-real-command-for-codex"],
                Path(temp_dir),
                timeout=30,
                line_limit=10,
            )

        self.assertFalse(report["success"])
        self.assertEqual(report["classification"], "environment")
        self.assertIn("missing_executable", report["signals"])
        self.assertTrue(report["stderr_tail"])
        self.assertTrue(any("环境" in step or "工作目录" in step for step in report["next_steps"]))

    def test_classify_failure_prefers_build_signal_over_generic_failed_word(self) -> None:
        category, signals = CAPTURE_FAILURE.classify_failure("Build failed\nFailed to execute goal", 1)

        self.assertEqual(category, "build")
        self.assertIn("build failed", signals)

    def test_cli_preserves_original_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--cwd",
                    temp_dir,
                    "--",
                    sys.executable,
                    "-c",
                    "import sys; sys.exit(7)",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )

        self.assertEqual(result.returncode, 7)
        self.assertIn("退出码：7", result.stdout)


if __name__ == "__main__":
    unittest.main()
