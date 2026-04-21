import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


RUNNER_PATH = Path(__file__).resolve().parents[1] / "run.py"


class CodeReviewChecklistRunnerTests(unittest.TestCase):
    def test_runner_dispatches_review_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            (repo / "src").mkdir()
            (repo / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")

            proc = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER_PATH),
                    "review_scope",
                    "--repo",
                    str(repo),
                    "--files",
                    "src/app.py",
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
        self.assertEqual(payload["changed_files"][0]["path"], "src/app.py")


if __name__ == "__main__":
    unittest.main()
