import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


RUNNER_PATH = Path(__file__).resolve().parents[1] / "run.py"


class ProjectOnboardingRunnerTests(unittest.TestCase):
    def test_runner_dispatches_project_facts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            (repo / "README.md").write_text("# Runner Demo\n", encoding="utf-8")

            proc = subprocess.run(
                [sys.executable, str(RUNNER_PATH), "project_facts", "--repo", str(repo), "--format", "json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["summary"], "Runner Demo")

    def test_runner_dispatches_onboard_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            (repo / "README.md").write_text("# Onboard Demo\n", encoding="utf-8")

            proc = subprocess.run(
                [sys.executable, str(RUNNER_PATH), "onboard", "--repo", str(repo), "--format", "json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["summary"], "Onboard Demo")


if __name__ == "__main__":
    unittest.main()
