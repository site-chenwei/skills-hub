import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
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

    def write_doc(self, hub_root: Path, rel_path: str, content: str, docset: str = "testset") -> Path:
        path = hub_root / "docs" / docset / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
        return path

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
            self.assertEqual(state["skill_root"], str(isolated_skill_root.resolve()))

            search_proc = subprocess.run(
                [sys.executable, str(runner_path), "search", "--hub-root", str(hub_root), "--list-docsets", "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                env=self.subprocess_env,
            )

            self.assertEqual(search_proc.returncode, 0, search_proc.stderr)
            payload = json.loads(search_proc.stdout)
            self.assertTrue(payload["ok"], payload)
            self.assertEqual(["testset"], [item["id"] for item in payload["docsets"]])
            self.assertEqual("indexed", payload["docsets"][0]["status"])

            catalog_proc = subprocess.run(
                [sys.executable, str(runner_path), "catalog", "--hub-root", str(hub_root), "--docset", "testset", "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                env=self.subprocess_env,
            )

            self.assertEqual(catalog_proc.returncode, 0, catalog_proc.stderr)
            catalog_payload = json.loads(catalog_proc.stdout)
            self.assertEqual(["testset"], [item["id"] for item in catalog_payload["docsets"]])
            self.assertTrue((hub_root / "index" / "catalog.json").exists())

            list_proc = subprocess.run(
                [sys.executable, str(runner_path), "list", "--hub-root", str(hub_root), "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                env=self.subprocess_env,
            )

            self.assertEqual(list_proc.returncode, 0, list_proc.stderr)
            list_payload = json.loads(list_proc.stdout)
            self.assertEqual(["testset"], [item["id"] for item in list_payload["docsets"]])

    def test_runner_init_auto_discovers_docs_subdirectories_and_updates_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            isolated_skill_root = Path(temp_dir) / "docs-hub"
            source_skill_root = Path(__file__).resolve().parents[1]
            copy_skill_tree(source_skill_root, isolated_skill_root)
            runner_path = isolated_skill_root / "run.py"
            hub_root = self.make_hub()
            self.write_doc(
                hub_root,
                "auto.md",
                """
                ---
                title: "auto doc"
                source_url: "https://example.com/auto"
                menu_path:
                  - "指南"
                ---

                # auto doc

                autodiscoverysentinel
                """,
                docset="autoset",
            )

            init_proc = subprocess.run(
                [sys.executable, str(runner_path), "init", "--hub-root", str(hub_root)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                env=self.subprocess_env,
            )

            self.assertEqual(init_proc.returncode, 0, init_proc.stderr)
            cfg = json.loads((hub_root / "docsets.json").read_text(encoding="utf-8"))
            autoset = [item for item in cfg["docsets"] if item["id"] == "autoset"][0]
            self.assertEqual("docs/autoset", autoset["root"])
            self.assertTrue(autoset["auto_discovered"])
            self.assertTrue((hub_root / "index" / "autoset.sqlite").exists())

            catalog_payload = json.loads((hub_root / "index" / "catalog.json").read_text(encoding="utf-8"))
            self.assertIn("autoset", [item["id"] for item in catalog_payload["docsets"]])

    def test_runner_init_accepts_positional_hub_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            isolated_skill_root = Path(temp_dir) / "docs-hub"
            source_skill_root = Path(__file__).resolve().parents[1]
            copy_skill_tree(source_skill_root, isolated_skill_root)
            runner_path = isolated_skill_root / "run.py"
            hub_root = self.make_hub()

            init_proc = subprocess.run(
                [sys.executable, str(runner_path), "init", str(hub_root)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                env=self.subprocess_env,
            )

            self.assertEqual(init_proc.returncode, 0, init_proc.stderr)
            state = json.loads(self.runtime_path(".skill-init.json").read_text(encoding="utf-8"))
            self.assertEqual(str(hub_root.resolve()), state["hub_root"])

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
            payload = json.loads(search_proc.stdout)
            self.assertTrue(payload["ok"], payload)
            self.assertEqual(["testset"], [item["id"] for item in payload["docsets"]])
            self.assertEqual("indexed", payload["docsets"][0]["status"])

    def test_runner_lookup_outputs_json_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            isolated_skill_root = Path(temp_dir) / "docs-hub"
            source_skill_root = Path(__file__).resolve().parents[1]
            copy_skill_tree(source_skill_root, isolated_skill_root)
            runner_path = isolated_skill_root / "run.py"
            hub_root = self.make_hub()
            self.write_doc(
                hub_root,
                "lookup.md",
                """
                ---
                title: "lookup doc"
                source_url: "https://example.com/lookup"
                menu_path:
                  - "指南"
                ---

                # lookup doc

                lookupsentinel
                """,
            )

            init_proc = subprocess.run(
                [sys.executable, str(runner_path), "init", "--hub-root", str(hub_root)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                env=self.subprocess_env,
            )
            self.assertEqual(init_proc.returncode, 0, init_proc.stderr)

            lookup_proc = subprocess.run(
                [sys.executable, str(runner_path), "lookup", "--hub-root", str(hub_root), "lookupsentinel", "--docset", "testset"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                env=self.subprocess_env,
            )

            self.assertEqual(lookup_proc.returncode, 0, lookup_proc.stderr)
            payload = json.loads(lookup_proc.stdout)
            self.assertTrue(payload["ok"], payload)
            self.assertEqual(["lookup.md"], [row["rel_path"] for row in payload["results"]])

    def test_runner_lookup_outputs_json_envelope_when_uninitialized(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            isolated_skill_root = Path(temp_dir) / "docs-hub"
            source_skill_root = Path(__file__).resolve().parents[1]
            copy_skill_tree(source_skill_root, isolated_skill_root)
            runner_path = isolated_skill_root / "run.py"

            lookup_proc = subprocess.run(
                [sys.executable, str(runner_path), "lookup", "missinginit"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                env=self.subprocess_env,
            )

            self.assertNotEqual(0, lookup_proc.returncode)
            payload = json.loads(lookup_proc.stdout)
            self.assertFalse(payload["ok"], payload)
            self.assertTrue(payload["failed"], payload)
            self.assertEqual([], payload["results"])
            self.assertEqual("lookup_failed", payload["failed_docsets"][0]["reason"])
            self.assertIn("尚未初始化", payload["failed_docsets"][0]["message"])

    def test_runner_unknown_command_exits_2_without_searching(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            isolated_skill_root = Path(temp_dir) / "docs-hub"
            source_skill_root = Path(__file__).resolve().parents[1]
            copy_skill_tree(source_skill_root, isolated_skill_root)
            runner_path = isolated_skill_root / "run.py"

            proc = subprocess.run(
                [sys.executable, str(runner_path), "not-a-command"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                env=self.subprocess_env,
            )

            self.assertEqual(2, proc.returncode)
            self.assertIn("unknown command: not-a-command", proc.stderr)
            self.assertNotIn("尚未初始化", proc.stderr)

    def test_runner_reinit_defaults_to_all_and_accepts_positional_hub_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            isolated_skill_root = Path(temp_dir) / "docs-hub"
            source_skill_root = Path(__file__).resolve().parents[1]
            copy_skill_tree(source_skill_root, isolated_skill_root)
            runner_path = isolated_skill_root / "run.py"
            hub_root = self.make_hub()
            cfg = json.loads((hub_root / "docsets.json").read_text(encoding="utf-8"))
            cfg["docsets"].append({"id": "extraset", "name": "Extra", "root": "docs/extraset"})
            (hub_root / "docsets.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
            self.write_doc(
                hub_root,
                "extra.md",
                """
                ---
                title: "extra doc"
                source_url: "https://example.com/extra"
                menu_path:
                  - "指南"
                ---

                # extra doc

                extrasentinel
                """,
                docset="extraset",
            )

            init_proc = subprocess.run(
                [sys.executable, str(runner_path), "init", "--hub-root", str(hub_root)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                env=self.subprocess_env,
            )
            self.assertEqual(init_proc.returncode, 0, init_proc.stderr)
            (hub_root / "index" / "testset.sqlite").unlink()
            (hub_root / "index" / "extraset.sqlite").unlink()

            reinit_proc = subprocess.run(
                [sys.executable, str(runner_path), "reinit", str(hub_root)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                env=self.subprocess_env,
            )

            self.assertEqual(reinit_proc.returncode, 0, reinit_proc.stderr)
            self.assertTrue((hub_root / "index" / "testset.sqlite").exists())
            self.assertTrue((hub_root / "index" / "extraset.sqlite").exists())


if __name__ == "__main__":
    unittest.main()
