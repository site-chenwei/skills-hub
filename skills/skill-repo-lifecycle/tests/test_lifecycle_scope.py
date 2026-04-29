from __future__ import annotations

import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "lifecycle_scope.py"
SPEC = importlib.util.spec_from_file_location("skill_lifecycle_scope", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class LifecycleScopeTests(unittest.TestCase):
    def test_collect_summary_discovers_skills_and_install_parity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = root / "repo"
            install = root / "install"
            skill = repo / "skills" / "sample-skill"
            (skill / "agents").mkdir(parents=True)
            (skill / "tests").mkdir()
            (repo / "skills").mkdir(exist_ok=True)
            (repo / "skills" / "test_all_skills.py").write_text("# aggregate\n", encoding="utf-8")
            (skill / "SKILL.md").write_text("---\nname: sample-skill\ndescription: test\n---\n", encoding="utf-8")
            (skill / "agents" / "openai.yaml").write_text("interface: {}\n", encoding="utf-8")
            (skill / "run.py").write_text("print('ok')\n", encoding="utf-8")
            (skill / "tests" / "test_sample.py").write_text("import unittest\n", encoding="utf-8")
            shutil.copytree(skill, install / "sample-skill")

            summary = MODULE.collect_summary(repo, install)

        self.assertEqual(summary["skill_count"], 1)
        self.assertEqual(summary["active_skill_count"], 1)
        self.assertEqual(summary["archived_skill_count"], 0)
        self.assertEqual(summary["skills"][0]["name"], "sample-skill")
        self.assertTrue(summary["skills"][0]["install_matches_source"])
        self.assertEqual(summary["recommended_validation"], "python3 -m unittest skills.test_all_skills")

    def test_run_py_without_tests_is_attention_item(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir) / "repo"
            skill = repo / "skills" / "sample-skill"
            (skill / "agents").mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: sample-skill\ndescription: test\n---\n", encoding="utf-8")
            (skill / "agents" / "openai.yaml").write_text("interface: {}\n", encoding="utf-8")
            (skill / "run.py").write_text("print('ok')\n", encoding="utf-8")

            summary = MODULE.collect_summary(repo, Path(temp_dir) / "install")

        self.assertIn("sample-skill: run.py exists but no test_*.py under tests/", summary["attention"])

    def test_missing_install_copy_is_attention_item(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir) / "repo"
            install = Path(temp_dir) / "install"
            skill = repo / "skills" / "sample-skill"
            (skill / "agents").mkdir(parents=True)
            (skill / "tests").mkdir()
            (skill / "SKILL.md").write_text("---\nname: sample-skill\ndescription: test\n---\n", encoding="utf-8")
            (skill / "agents" / "openai.yaml").write_text("interface: {}\n", encoding="utf-8")
            (skill / "run.py").write_text("print('ok')\n", encoding="utf-8")
            (skill / "tests" / "test_sample.py").write_text("import unittest\n", encoding="utf-8")

            summary = MODULE.collect_summary(repo, install)

        self.assertIn(f"sample-skill: installed copy missing at {install / 'sample-skill'}", summary["attention"])

    def test_archived_skill_install_residual_is_attention_item(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir) / "repo"
            install = Path(temp_dir) / "install"
            archived = repo / "archive" / "skills" / "old-skill"
            installed = install / "old-skill"
            archived.mkdir(parents=True)
            installed.mkdir(parents=True)
            (archived / "SKILL.md").write_text("---\nname: old-skill\ndescription: old\n---\n", encoding="utf-8")
            (installed / "SKILL.md").write_text("---\nname: old-skill\ndescription: old\n---\n", encoding="utf-8")

            summary = MODULE.collect_summary(repo, install)

        self.assertEqual(summary["archived_skill_count"], 1)
        self.assertEqual(summary["archived_skills"][0]["name"], "old-skill")
        self.assertTrue(summary["archived_skills"][0]["installed"])
        self.assertIn(f"old-skill: archived skill still installed at {install / 'old-skill'}", summary["attention"])

    def test_markdown_output_reports_active_and_archived_sections(self) -> None:
        summary = {
            "repo": "/tmp/repo",
            "install_root": "/tmp/install",
            "active_skill_count": 1,
            "archived_skill_count": 1,
            "recommended_validation": "python3 -m unittest skills.test_all_skills",
            "shared_tests": True,
            "skills": [
                {
                    "name": "current-skill",
                    "has_run_py": True,
                    "has_tests": True,
                    "installed": True,
                    "install_matches_source": True,
                }
            ],
            "archived_skills": [{"name": "old-skill", "installed": True}],
            "attention": ["old-skill: archived skill still installed at /tmp/install/old-skill"],
        }

        text = MODULE.format_markdown(summary)

        self.assertIn("Active Skill 清单：", text)
        self.assertIn("- current-skill (run.py, tests, installed, parity)", text)
        self.assertIn("归档 Skill 清单：", text)
        self.assertIn("- old-skill (installed-residual)", text)


if __name__ == "__main__":
    unittest.main()
