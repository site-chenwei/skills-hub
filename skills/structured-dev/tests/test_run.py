import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


RUNNER_PATH = Path(__file__).resolve().parents[1] / "run.py"


class StructuredDevRunnerTests(unittest.TestCase):
    def test_runner_dispatches_change_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            (repo / "README.md").write_text("# Demo\n", encoding="utf-8")

            proc = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER_PATH),
                    "change_plan",
                    "--repo",
                    str(repo),
                    "--paths",
                    "README.md",
                    "--format",
                    "json",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertIn(payload["mode"], {"light", "full"})
        self.assertEqual(payload["repo_path"], str(repo.resolve()))


if __name__ == "__main__":
    unittest.main()
