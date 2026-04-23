import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


def copy_skill_tree(src: Path, dst: Path) -> None:
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".deps", ".skill-init.json"))


class DocsHubRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        runtime_tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(runtime_tmpdir.cleanup)
        self.shared_runtime_root = Path(runtime_tmpdir.name)
        self.runtime_root = self.shared_runtime_root / "docs-hub"
        self.subprocess_env = {
            **dict(os.environ),
            "SKILLS_HUB_RUNTIME_DIR": str(self.shared_runtime_root),
        }

    def runtime_path(self, *parts: str) -> Path:
        return self.runtime_root.joinpath(*parts)

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
            copy_skill_tree(source_skill_root, isolated_skill_root)
            runner_path = isolated_skill_root / "run.py"
            hub_root = self.make_hub()

            init_proc = subprocess.run(
                [sys.executable, str(runner_path), "init", "--hub-root", str(hub_root)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                env=self.subprocess_env,
            )

            self.assertEqual(init_proc.returncode, 0, init_proc.stderr)
            state = json.loads(self.runtime_path(".skill-init.json").read_text(encoding="utf-8"))
            self.assertEqual(state["skill_root"], str(isolated_skill_root))

            search_proc = subprocess.run(
                [sys.executable, str(runner_path), "search", "--hub-root", str(hub_root), "--list-docsets", "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                env=self.subprocess_env,
            )

            self.assertEqual(search_proc.returncode, 0, search_proc.stderr)
            self.assertIn("testset", search_proc.stdout)
            self.assertIn("[indexed]", search_proc.stdout)

    def test_fresh_skill_copy_reuses_external_runtime_after_init(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_skill_root = Path(__file__).resolve().parents[1]
            first_skill_root = Path(temp_dir) / "docs-hub-v1"
            second_skill_root = Path(temp_dir) / "docs-hub-v2"
            copy_skill_tree(source_skill_root, first_skill_root)
            copy_skill_tree(source_skill_root, second_skill_root)
            hub_root = self.make_hub()

            init_proc = subprocess.run(
                [sys.executable, str(first_skill_root / "run.py"), "init", "--hub-root", str(hub_root)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                env=self.subprocess_env,
            )
            self.assertEqual(init_proc.returncode, 0, init_proc.stderr)
            self.assertTrue(self.runtime_path(".skill-init.json").exists())
            self.assertFalse((second_skill_root / ".skill-init.json").exists())
            self.assertFalse((second_skill_root / ".deps").exists())

            search_proc = subprocess.run(
                [sys.executable, str(second_skill_root / "run.py"), "search", "--list-docsets", "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                cwd=temp_dir,
                env=self.subprocess_env,
            )

            self.assertEqual(search_proc.returncode, 0, search_proc.stderr)
            self.assertIn("testset", search_proc.stdout)
            self.assertIn("[indexed]", search_proc.stdout)


if __name__ == "__main__":
    unittest.main()
