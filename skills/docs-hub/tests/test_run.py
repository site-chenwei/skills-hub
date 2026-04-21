import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class DocsHubRunnerTests(unittest.TestCase):
    def make_hub(self) -> Path:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        hub_root = Path(tmpdir.name)
        (hub_root / "docs" / "testset").mkdir(parents=True, exist_ok=True)
        (hub_root / "index").mkdir(parents=True, exist_ok=True)
        (hub_root / "docsets.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "defaults": {
                        "include": ["*.md", "**/*.md"],
                        "exclude": [],
                        "section_from": ["menu_path[0]", "rel_path[0]"],
                        "doc_type_rules": [],
                        "nav_rules": {
                            "filenames": ["README.md", "catalog.md", "index.md"],
                            "min_body_chars": 300,
                        },
                        "chunk": {
                            "target_chars": 1200,
                            "max_chars": 1500,
                            "overlap_chars": 150,
                        },
                    },
                    "docsets": [
                        {
                            "id": "testset",
                            "name": "Test",
                            "root": "docs/testset",
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return hub_root

    def test_runner_init_injects_skill_root_and_search_lists_docsets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            isolated_skill_root = Path(temp_dir) / "docs-hub"
            source_skill_root = Path(__file__).resolve().parents[1]
            shutil.copytree(source_skill_root, isolated_skill_root)
            runner_path = isolated_skill_root / "run.py"
            hub_root = self.make_hub()

            init_proc = subprocess.run(
                [sys.executable, str(runner_path), "init", "--hub-root", str(hub_root)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )

            self.assertEqual(init_proc.returncode, 0, init_proc.stderr)
            state = json.loads((isolated_skill_root / ".skill-init.json").read_text(encoding="utf-8"))
            self.assertEqual(state["skill_root"], str(isolated_skill_root))

            search_proc = subprocess.run(
                [sys.executable, str(runner_path), "search", "--hub-root", str(hub_root), "--list-docsets", "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )

            self.assertEqual(search_proc.returncode, 0, search_proc.stderr)
            self.assertIn("testset", search_proc.stdout)
            self.assertIn("[indexed]", search_proc.stdout)


if __name__ == "__main__":
    unittest.main()
