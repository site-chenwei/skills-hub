import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


RUNNER_PATH = Path(__file__).resolve().parents[1] / "run.py"


class VerificationAndDebugRunnerTests(unittest.TestCase):
    def test_runner_dispatches_capture_failure_and_preserves_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            proc = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER_PATH),
                    "capture_failure",
                    "--cwd",
                    temp_dir,
                    "--format",
                    "json",
                    "--",
                    sys.executable,
                    "-c",
                    "import sys; sys.exit(9)",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )

        self.assertEqual(proc.returncode, 9)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["exit_code"], 9)


if __name__ == "__main__":
    unittest.main()
