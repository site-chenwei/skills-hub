import subprocess
import sys
import unittest
from pathlib import Path


RUNNER_PATH = Path(__file__).resolve().parents[1] / "run.py"


class HarmonyBuildRunnerTests(unittest.TestCase):
    def test_runner_dispatches_help_to_harmony_build_cli(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(RUNNER_PATH), "detect", "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("usage: harmony_build.py detect", proc.stdout)


if __name__ == "__main__":
    unittest.main()
