import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "project_facts.py"
SPEC = importlib.util.spec_from_file_location("project_facts", SCRIPT_PATH)
PROJECT_FACTS = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(PROJECT_FACTS)


class ProjectFactsTests(unittest.TestCase):
    def test_collect_facts_detects_docs_stack_and_validation_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            (repo / "README.md").write_text("# Demo App\n\nA small demo project.\n", encoding="utf-8")
            (repo / "package.json").write_text(
                json.dumps(
                    {
                        "name": "demo-app",
                        "packageManager": "pnpm@9.1.0",
                        "scripts": {
                            "test": "vitest run",
                            "build": "vite build",
                        },
                    }
                ),
                encoding="utf-8",
            )
            (repo / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
            (repo / "tsconfig.json").write_text("{}", encoding="utf-8")
            (repo / "src").mkdir()
            (repo / "tests").mkdir()
            (repo / "src" / "index.ts").write_text("export const demo = 1;\n", encoding="utf-8")
            (repo / "tests" / "app.test.ts").write_text("it('works', () => {});\n", encoding="utf-8")

            facts = PROJECT_FACTS.collect_facts(repo)

        self.assertEqual(facts["summary"], "Demo App")
        self.assertIn("README.md", facts["confirmed_facts"]["docs"])
        self.assertEqual(facts["confirmed_facts"]["package_manager"], "pnpm")
        self.assertIn("node", facts["inferred"]["primary_stacks"])
        self.assertIn("typescript", facts["inferred"]["primary_stacks"])
        commands = {item["command"] for item in facts["inferred"]["validation_commands"]}
        self.assertIn("pnpm test", commands)
        self.assertIn("pnpm run build", commands)
        self.assertIn("src", facts["confirmed_facts"]["top_level_dirs"])
        self.assertFalse(any("缺少 PROJECT.md / README" in item for item in facts["needs_confirmation"]))

    def test_collect_facts_does_not_skip_repo_under_ignored_parent_directory_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir) / "build" / "demo-repo"
            (repo / "src").mkdir(parents=True)
            (repo / "README.md").write_text("# Parent Build Repo\n", encoding="utf-8")
            (repo / "main.py").write_text("print('ok')\n", encoding="utf-8")
            (repo / "src" / "worker.py").write_text("VALUE = 1\n", encoding="utf-8")

            facts = PROJECT_FACTS.collect_facts(repo)

        languages = {item["name"] for item in facts["inferred"]["languages"]}
        self.assertIn("Python", languages)
        self.assertIn("main.py", facts["inferred"]["entry_points"])

    def test_collect_facts_handles_invalid_manifests_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            (repo / "README.md").write_text("# Broken Repo\n", encoding="utf-8")
            (repo / "package.json").write_text("{invalid json}\n", encoding="utf-8")
            (repo / "pyproject.toml").write_text("[project\nname='broken'\n", encoding="utf-8")
            (repo / "worker.py").write_text("print('ok')\n", encoding="utf-8")

            facts = PROJECT_FACTS.collect_facts(repo)

        self.assertEqual(facts["summary"], "Broken Repo")
        self.assertEqual(len(facts["parse_errors"]), 2)
        self.assertTrue(any("package.json" in item for item in facts["parse_errors"]))
        self.assertTrue(any("pyproject.toml" in item for item in facts["parse_errors"]))
        self.assertTrue(any("解析失败" in item for item in facts["parse_errors"]))
        self.assertTrue(any("解析失败" in item for item in facts["needs_confirmation"]))

    def test_collect_facts_infers_python_stack_and_unittest_command_from_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            (repo / "README.md").write_text("# Python Demo\n", encoding="utf-8")
            (repo / "src").mkdir()
            (repo / "tests").mkdir()
            (repo / "src" / "worker.py").write_text("def run():\n    return 1\n", encoding="utf-8")
            (repo / "tests" / "test_worker.py").write_text("import unittest\n", encoding="utf-8")

            facts = PROJECT_FACTS.collect_facts(repo)

        self.assertIn("python", facts["inferred"]["primary_stacks"])
        commands = {item["command"] for item in facts["inferred"]["validation_commands"]}
        self.assertIn("python3 -m unittest discover", commands)
        self.assertEqual(facts["parse_errors"], [])


if __name__ == "__main__":
    unittest.main()
