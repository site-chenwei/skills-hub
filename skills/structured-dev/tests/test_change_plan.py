import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "change_plan.py"
SPEC = importlib.util.spec_from_file_location("change_plan", SCRIPT_PATH)
CHANGE_PLAN = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(CHANGE_PLAN)


class ChangePlanTests(unittest.TestCase):
    def test_build_plan_promotes_full_workflow_for_dependency_and_interface_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            (repo / "src").mkdir()
            (repo / "src" / "api.py").write_text("def endpoint():\n    return {}\n", encoding="utf-8")
            (repo / "pyproject.toml").write_text("[project]\nname='demo'\nversion='0.1.0'\n", encoding="utf-8")

            args = SimpleNamespace(
                repo=str(repo),
                goal="更新接口并调整依赖",
                paths=["src/api.py", "pyproject.toml"],
                interface_change=True,
                dependency_change=True,
                schema_change=False,
                security_sensitive=False,
                performance_sensitive=False,
                bugfix=False,
            )
            plan = CHANGE_PLAN.build_plan(repo, args)

        self.assertEqual(plan["mode"], "full")
        self.assertIn("design", plan["stages"])
        self.assertIn("code-review-checklist", plan["recommended_skill_chain"])
        self.assertIn("project-onboarding", plan["recommended_skill_chain"])
        self.assertIn("执行受影响范围内的单元测试或最小功能验证。", plan["validation_expectations"])
        self.assertIn("补跑构建或安装相关验证，确认依赖和锁文件与环境一致。", plan["validation_expectations"])

    def test_build_plan_treats_monorepo_leaf_paths_as_distinct_modules(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            (repo / "skills" / "project-onboarding" / "scripts").mkdir(parents=True)
            (repo / "skills" / "harmony-build" / "scripts").mkdir(parents=True)

            args = SimpleNamespace(
                repo=str(repo),
                goal="同时调整两个 Skill",
                paths=[
                    "skills/project-onboarding/scripts/project_facts.py",
                    "skills/harmony-build/scripts/harmony_build.py",
                ],
                interface_change=False,
                dependency_change=False,
                schema_change=False,
                security_sensitive=False,
                performance_sensitive=False,
                bugfix=False,
            )
            plan = CHANGE_PLAN.build_plan(repo, args)

        self.assertEqual(plan["mode"], "full")
        self.assertIn("skills/project-onboarding", plan["modules"])
        self.assertIn("skills/harmony-build", plan["modules"])
        self.assertIn("project-onboarding", plan["recommended_skill_chain"])
        self.assertIn("code-review-checklist", plan["recommended_skill_chain"])

    def test_build_plan_marks_outside_repo_paths_instead_of_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir) / "repo"
            repo.mkdir()

            args = SimpleNamespace(
                repo=str(repo),
                goal="分析外部配置",
                paths=["/etc/hosts"],
                interface_change=False,
                dependency_change=False,
                schema_change=False,
                security_sensitive=False,
                performance_sensitive=False,
                bugfix=False,
            )
            plan = CHANGE_PLAN.build_plan(repo, args)

        self.assertEqual(plan["outside_repo_paths"], ["/etc/hosts"])
        self.assertEqual(plan["modules"], ["(outside repo)"])
        self.assertEqual(plan["mode"], "full")
        self.assertIn("project-onboarding", plan["recommended_skill_chain"])
        self.assertTrue(any("仓库边界" in item for item in plan["validation_expectations"]))


if __name__ == "__main__":
    unittest.main()
