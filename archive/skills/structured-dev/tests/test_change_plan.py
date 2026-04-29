import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


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

    def test_build_plan_classifies_directory_paths_by_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            (repo / "web" / "src" / "routes").mkdir(parents=True)
            (repo / "web" / "src" / "routes" / "account.tsx").write_text(
                "export function Account() { return null; }\n",
                encoding="utf-8",
            )
            (repo / "web" / "src" / "components").mkdir(parents=True)
            (repo / "web" / "src" / "components" / "Button.tsx").write_text(
                "export function Button() { return null; }\n",
                encoding="utf-8",
            )

            args = SimpleNamespace(
                repo=str(repo),
                goal="调整 web 目录",
                paths=["web/src"],
                interface_change=False,
                dependency_change=False,
                schema_change=False,
                security_sensitive=False,
                performance_sensitive=False,
                bugfix=False,
            )
            plan = CHANGE_PLAN.build_plan(repo, args)

        self.assertEqual(plan["paths"], ["web/src"])
        self.assertNotIn("other", plan["path_categories"])
        self.assertIn("react-high-risk", plan["path_categories"])
        self.assertIn("web", plan["modules"])
        self.assertTrue(any("React Web 高风险" in item for item in plan["validation_expectations"]))

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

    def test_build_plan_promotes_harmony_high_risk_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            (repo / "entry" / "src" / "main" / "ets" / "pages").mkdir(parents=True)
            (repo / "entry" / "src" / "main" / "resources" / "base").mkdir(parents=True)

            args = SimpleNamespace(
                repo=str(repo),
                goal="调整 Harmony 页面结构",
                paths=[
                    "entry/src/main/ets/pages/Index.ets",
                    "entry/src/main/module.json5",
                    "entry/src/main/resources/base/element/string.json",
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
        self.assertIn("harmony-high-risk", plan["path_categories"])
        self.assertTrue(any("模块级 hvigor 编译验证" in item for item in plan["validation_expectations"]))
        self.assertTrue(any("module.json5" in item for item in plan["review_focus"]))

    def test_build_plan_promotes_java_high_risk_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            (repo / "src" / "main" / "java" / "com" / "example" / "user").mkdir(parents=True)

            args = SimpleNamespace(
                repo=str(repo),
                goal="调整 Java API",
                paths=[
                    "src/main/java/com/example/user/UserController.java",
                    "src/main/java/com/example/user/UserDto.java",
                    "src/main/resources/application.yml",
                    "pom.xml",
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
        self.assertIn("java-high-risk", plan["path_categories"])
        self.assertTrue(any("./gradlew test 或 mvn test" in item for item in plan["validation_expectations"]))
        self.assertTrue(any("controller/API/DTO/config/migration" in item for item in plan["review_focus"]))

    def test_build_plan_keeps_non_react_auth_ts_out_of_react_risk(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            (repo / "src").mkdir()

            args = SimpleNamespace(
                repo=str(repo),
                goal="调整 Node 鉴权工具",
                paths=["src/auth.ts"],
                interface_change=False,
                dependency_change=False,
                schema_change=False,
                security_sensitive=True,
                performance_sensitive=False,
                bugfix=False,
            )
            plan = CHANGE_PLAN.build_plan(repo, args)

        self.assertIn("source", plan["path_categories"])
        self.assertNotIn("react-high-risk", plan["path_categories"])
        self.assertNotIn("react-web", plan["path_categories"])
        self.assertTrue(any("权限边界" in item for item in plan["validation_expectations"]))
        self.assertFalse(any("React Web" in item for item in plan["validation_expectations"]))

    def test_build_plan_promotes_react_auth_with_stack_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            (repo / "web" / "src").mkdir(parents=True)

            args = SimpleNamespace(
                repo=str(repo),
                goal="调整 React 鉴权",
                paths=["web/src/auth.ts"],
                interface_change=False,
                dependency_change=False,
                schema_change=False,
                security_sensitive=False,
                performance_sensitive=False,
                bugfix=False,
            )
            plan = CHANGE_PLAN.build_plan(repo, args)

        self.assertEqual(plan["mode"], "full")
        self.assertIn("react-high-risk", plan["path_categories"])
        self.assertTrue(any("React Web 高风险" in item for item in plan["validation_expectations"]))

    def test_build_plan_promotes_react_web_high_risk_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            (repo / "src" / "routes").mkdir(parents=True)

            args = SimpleNamespace(
                repo=str(repo),
                goal="调整 React 路由",
                paths=[
                    "src/routes/account.tsx",
                    "src/api-client/auth.ts",
                    "package.json",
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
        self.assertIn("react-high-risk", plan["path_categories"])
        self.assertTrue(any("test、lint、typecheck" in item for item in plan["validation_expectations"]))
        self.assertTrue(any("routing、SSR/data loading" in item for item in plan["review_focus"]))

    def test_build_plan_keeps_plain_harmony_ets_util_low_risk(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            (repo / "entry" / "src" / "main" / "ets" / "utils").mkdir(parents=True)

            args = SimpleNamespace(
                repo=str(repo),
                goal="调整 ArkTS 格式化工具",
                paths=["entry/src/main/ets/utils/format.ets"],
                interface_change=False,
                dependency_change=False,
                schema_change=False,
                security_sensitive=False,
                performance_sensitive=False,
                bugfix=False,
            )
            plan = CHANGE_PLAN.build_plan(repo, args)

        self.assertEqual(plan["mode"], "light")
        self.assertIn("harmony", plan["path_categories"])
        self.assertNotIn("harmony-high-risk", plan["path_categories"])
        self.assertTrue(any("不默认升级到 hvigor 编译" in item for item in plan["validation_expectations"]))
        self.assertFalse(any("模块级 hvigor 编译验证" in item for item in plan["validation_expectations"]))

    def test_build_plan_keeps_non_react_package_json_as_dependency_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            (repo / "package.json").write_text('{"name":"python-tools"}\n', encoding="utf-8")

            args = SimpleNamespace(
                repo=str(repo),
                goal="更新工具依赖",
                paths=["package.json"],
                interface_change=False,
                dependency_change=False,
                schema_change=False,
                security_sensitive=False,
                performance_sensitive=False,
                bugfix=False,
            )
            plan = CHANGE_PLAN.build_plan(repo, args)

        self.assertIn("dependencies", plan["path_categories"])
        self.assertNotIn("react-high-risk", plan["path_categories"])
        self.assertNotIn("react-web", plan["path_categories"])

    def test_build_plan_does_not_treat_author_file_as_react_auth_risk(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            (repo / "src").mkdir()

            args = SimpleNamespace(
                repo=str(repo),
                goal="调整作者信息",
                paths=["src/author.ts"],
                interface_change=False,
                dependency_change=False,
                schema_change=False,
                security_sensitive=False,
                performance_sensitive=False,
                bugfix=False,
            )
            plan = CHANGE_PLAN.build_plan(repo, args)

        self.assertEqual(plan["path_categories"], ["source"])
        self.assertEqual(plan["mode"], "light")
        self.assertFalse(any("React Web 高风险" in item for item in plan["validation_expectations"]))

    def test_build_plan_treats_windows_absolute_paths_as_outside_repo(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            if os.name != "nt":
                (repo / "C:" / "tmp").mkdir(parents=True)
                (repo / "C:" / "tmp" / "file.ts").write_text("export const value = 1;\n", encoding="utf-8")

            args = SimpleNamespace(
                repo=str(repo),
                goal="分析外部 Windows 路径",
                paths=[r"C:\tmp\file.ts"],
                interface_change=False,
                dependency_change=False,
                schema_change=False,
                security_sensitive=False,
                performance_sensitive=False,
                bugfix=False,
            )
            plan = CHANGE_PLAN.build_plan(repo, args)

        self.assertEqual(plan["outside_repo_paths"], ["C:/tmp/file.ts"])
        self.assertEqual(plan["modules"], ["(outside repo)"])
        self.assertEqual(plan["mode"], "full")

    def test_build_task_intake_combines_project_facts_and_plan_without_running_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            (repo / "README.md").write_text("# Intake Demo\n", encoding="utf-8")
            (repo / "src").mkdir()
            (repo / "tests").mkdir()
            (repo / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            (repo / "tests" / "test_app.py").write_text("import unittest\n", encoding="utf-8")

            args = SimpleNamespace(
                repo=str(repo),
                goal="调整 Python 逻辑",
                paths=["src/app.py"],
                interface_change=False,
                dependency_change=False,
                schema_change=False,
                security_sensitive=False,
                performance_sensitive=False,
                bugfix=False,
            )
            package = CHANGE_PLAN.build_task_intake(repo, args)

        self.assertEqual(package["package_type"], "task-intake")
        self.assertEqual(package["not_executed"], ["implementation", "validation"])
        self.assertEqual(package["plan"]["mode"], "light")
        self.assertEqual(package["facts"]["summary"], "Intake Demo")
        self.assertTrue(package["validation_candidates"]["not_executed"])
        commands = {item["command"] for item in package["validation_candidates"]["commands"]}
        self.assertIn("<python_cmd> -m unittest discover", commands)

    def test_build_task_intake_includes_skill_module_unittest_start_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            (repo / "README.md").write_text("# Skills Demo\n", encoding="utf-8")
            skill = repo / "skills" / "alpha-skill"
            (skill / "tests").mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: alpha-skill\ndescription: Demo.\n---\n", encoding="utf-8")
            (skill / "run.py").write_text("def main():\n    return 0\n", encoding="utf-8")
            (skill / "tests" / "test_alpha.py").write_text(
                "import unittest\n\nclass AlphaTests(unittest.TestCase):\n    pass\n",
                encoding="utf-8",
            )

            args = SimpleNamespace(
                repo=str(repo),
                goal="调整 Skill",
                paths=["skills/alpha-skill"],
                interface_change=False,
                dependency_change=False,
                schema_change=False,
                security_sensitive=False,
                performance_sensitive=False,
                bugfix=False,
            )
            package = CHANGE_PLAN.build_task_intake(repo, args)

        commands = {item["command"] for item in package["validation_candidates"]["commands"]}
        self.assertIn("cd skills/alpha-skill && <python_cmd> -m unittest discover -s tests", commands)
        self.assertNotIn("cd skills/alpha-skill && <python_cmd> -m unittest discover", commands)

    def test_load_project_facts_module_reports_missing_helper(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_script = Path(temp_dir) / "structured-dev" / "scripts" / "change_plan.py"
            fake_script.parent.mkdir(parents=True)

            with mock.patch.object(CHANGE_PLAN, "__file__", str(fake_script)):
                module, error = CHANGE_PLAN.load_project_facts_module()

        self.assertIsNone(module)
        self.assertIn("未找到 project_facts 辅助脚本", error)

    def test_collect_project_facts_reports_helper_load_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fake_script = root / "structured-dev" / "scripts" / "change_plan.py"
            helper = root / "project-onboarding" / "scripts" / "project_facts.py"
            fake_script.parent.mkdir(parents=True)
            helper.parent.mkdir(parents=True)
            helper.write_text("raise RuntimeError('load boom')\n", encoding="utf-8")

            with mock.patch.object(CHANGE_PLAN, "__file__", str(fake_script)):
                facts, error = CHANGE_PLAN.collect_project_facts(root)

        self.assertIsNone(facts)
        self.assertIn("project_facts 辅助脚本加载失败", error)
        self.assertIn("load boom", error)

    def test_collect_project_facts_reports_scan_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fake_script = root / "structured-dev" / "scripts" / "change_plan.py"
            helper = root / "project-onboarding" / "scripts" / "project_facts.py"
            fake_script.parent.mkdir(parents=True)
            helper.parent.mkdir(parents=True)
            helper.write_text(
                "def collect_facts(repo):\n    raise RuntimeError('scan boom')\n",
                encoding="utf-8",
            )

            with mock.patch.object(CHANGE_PLAN, "__file__", str(fake_script)):
                facts, error = CHANGE_PLAN.collect_project_facts(root)

        self.assertIsNone(facts)
        self.assertIn("project_facts 扫描失败", error)
        self.assertIn("scan boom", error)

    def test_task_intake_main_returns_nonzero_when_project_facts_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            (repo / "README.md").write_text("# Intake Failure\n", encoding="utf-8")
            argv = [
                "change_plan.py",
                "--task-intake",
                "--repo",
                str(repo),
                "--goal",
                "准备执行包",
                "--paths",
                "README.md",
                "--format",
                "json",
            ]
            stdout = io.StringIO()
            with mock.patch.object(sys, "argv", argv), mock.patch.object(
                CHANGE_PLAN,
                "collect_project_facts",
                return_value=(None, "project_facts 扫描失败：scan boom"),
            ), redirect_stdout(stdout):
                return_code = CHANGE_PLAN.main()

        payload = json.loads(stdout.getvalue())
        self.assertEqual(return_code, 1)
        self.assertIsNone(payload["facts"])
        self.assertEqual(payload["facts_error"], "project_facts 扫描失败：scan boom")


if __name__ == "__main__":
    unittest.main()
