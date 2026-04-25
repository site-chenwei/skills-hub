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


def modules_by_path(facts: dict) -> dict:
    return {module["path"]: module for module in facts["inferred"]["modules"]}


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
        self.assertIn("<python_cmd> -m unittest discover", commands)
        self.assertEqual(facts["parse_errors"], [])

    def test_collect_facts_infers_harmony_stack_and_conditional_build_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            (repo / "README.md").write_text("# Harmony Demo\n", encoding="utf-8")
            (repo / "build-profile.json5").write_text("{ app: {} }\n", encoding="utf-8")
            (repo / "hvigorfile.ts").write_text("export default {};\n", encoding="utf-8")
            (repo / "oh-package.json5").write_text("{ name: 'demo' }\n", encoding="utf-8")
            (repo / "AppScope").mkdir()
            (repo / "AppScope" / "app.json5").write_text("{ app: {} }\n", encoding="utf-8")
            (repo / "entry" / "src" / "main" / "ets" / "pages").mkdir(parents=True)
            (repo / "entry" / "src" / "main" / "resources" / "base").mkdir(parents=True)
            (repo / "entry" / "src" / "main" / "module.json5").write_text("{ module: {} }\n", encoding="utf-8")
            (repo / "entry" / "src" / "main" / "ets" / "pages" / "Index.ets").write_text(
                "@Entry\n@Component\nstruct Index { build() {} }\n",
                encoding="utf-8",
            )
            (repo / "entry" / "src" / "main" / "resources" / "base" / "element.json").write_text(
                "{}\n",
                encoding="utf-8",
            )

            facts = PROJECT_FACTS.collect_facts(repo)

        self.assertIn("harmony", facts["inferred"]["primary_stacks"])
        languages = {item["name"] for item in facts["inferred"]["languages"]}
        self.assertIn("ArkTS", languages)
        self.assertIn("build-profile.json5", facts["confirmed_facts"]["configs"])
        self.assertIn("entry/src/main/module.json5", facts["confirmed_facts"]["configs"])
        commands = {item["command"] for item in facts["inferred"]["validation_commands"]}
        self.assertIn("$harmony-build verify --task <public module task>", commands)
        self.assertNotIn("harmony-build module compile", commands)

    def test_collect_facts_does_not_infer_harmony_from_entry_and_resources_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            (repo / "README.md").write_text("# Generic Resources Demo\n", encoding="utf-8")
            (repo / "entry" / "src" / "main" / "resources" / "base").mkdir(parents=True)
            (repo / "entry" / "src" / "main" / "resources" / "base" / "messages.json").write_text(
                "{}\n",
                encoding="utf-8",
            )

            facts = PROJECT_FACTS.collect_facts(repo)

        self.assertNotIn("harmony", facts["inferred"]["primary_stacks"])
        commands = {item["command"] for item in facts["inferred"]["validation_commands"]}
        self.assertFalse(any("harmony-build" in command for command in commands))

    def test_collect_facts_infers_java_stack_and_maven_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            (repo / "README.md").write_text("# Java Demo\n", encoding="utf-8")
            (repo / "pom.xml").write_text("<project></project>\n", encoding="utf-8")
            (repo / "src" / "main" / "java" / "com" / "example" / "controller").mkdir(parents=True)
            (repo / "src" / "main" / "resources" / "db" / "migration").mkdir(parents=True)
            (repo / "src" / "main" / "java" / "com" / "example" / "controller" / "UserController.java").write_text(
                "class UserController {}\n",
                encoding="utf-8",
            )
            (repo / "src" / "main" / "resources" / "application.yml").write_text(
                "spring:\n  application:\n    name: demo\n",
                encoding="utf-8",
            )
            (repo / "src" / "main" / "resources" / "db" / "migration" / "V1__init.sql").write_text(
                "select 1;\n",
                encoding="utf-8",
            )

            facts = PROJECT_FACTS.collect_facts(repo)

        self.assertIn("java", facts["inferred"]["primary_stacks"])
        commands = {item["command"] for item in facts["inferred"]["validation_commands"]}
        self.assertIn("mvn test", commands)

    def test_collect_facts_infers_react_web_stack_and_package_script_validations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            (repo / "README.md").write_text("# React Demo\n", encoding="utf-8")
            (repo / "package.json").write_text(
                json.dumps(
                    {
                        "name": "react-demo",
                        "dependencies": {
                            "react": "latest",
                            "react-dom": "latest",
                        },
                        "devDependencies": {
                            "vitest": "latest",
                            "@storybook/react-vite": "latest",
                        },
                        "scripts": {
                            "test": "vitest run",
                            "lint": "eslint .",
                            "typecheck": "tsc --noEmit",
                            "build": "vite build",
                        },
                    }
                ),
                encoding="utf-8",
            )
            (repo / "tsconfig.json").write_text("{}", encoding="utf-8")
            (repo / ".storybook").mkdir()
            (repo / ".storybook" / "main.ts").write_text("export default {};\n", encoding="utf-8")
            (repo / "src").mkdir()
            (repo / "src" / "App.tsx").write_text("export function App() { return null; }\n", encoding="utf-8")

            facts = PROJECT_FACTS.collect_facts(repo)

        self.assertIn("react-web", facts["inferred"]["primary_stacks"])
        self.assertIn("node", facts["inferred"]["primary_stacks"])
        self.assertIn("typescript", facts["inferred"]["primary_stacks"])
        commands = {item["command"] for item in facts["inferred"]["validation_commands"]}
        self.assertIn("npm test", commands)
        self.assertIn("npm run lint", commands)
        self.assertIn("npm run typecheck", commands)
        self.assertIn("npm run build", commands)

    def test_collect_facts_reports_nested_react_module_with_local_package_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            web = repo / "apps" / "web"
            (repo / "README.md").write_text("# Monorepo\n", encoding="utf-8")
            (web / "src").mkdir(parents=True)
            (web / "package.json").write_text(
                json.dumps(
                    {
                        "name": "web",
                        "packageManager": "pnpm@9.12.0",
                        "dependencies": {
                            "react": "latest",
                            "react-dom": "latest",
                        },
                        "scripts": {
                            "test": "vitest run",
                            "lint": "eslint .",
                            "build": "vite build",
                        },
                    }
                ),
                encoding="utf-8",
            )
            (web / "src" / "App.tsx").write_text("export function App() { return null; }\n", encoding="utf-8")

            facts = PROJECT_FACTS.collect_facts(repo)

        modules = modules_by_path(facts)
        self.assertIn("apps/web", modules)
        web_module = modules["apps/web"]
        self.assertIn("react-web", web_module["stacks"])
        self.assertIn("node", web_module["stacks"])
        self.assertEqual(web_module["package_manager"], "pnpm")
        self.assertIn("package.json", web_module["configs"])
        commands = {item["command"] for item in web_module["validation_commands"]}
        self.assertIn("cd apps/web && pnpm test", commands)
        self.assertIn("cd apps/web && pnpm run lint", commands)
        self.assertIn("cd apps/web && pnpm run build", commands)
        root_commands = {item["command"] for item in facts["inferred"]["validation_commands"]}
        self.assertNotIn("cd apps/web && pnpm test", root_commands)

    def test_collect_facts_reports_nested_java_maven_and_gradle_modules(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            user_service = repo / "services" / "user"
            billing_service = repo / "services" / "billing"
            (repo / "README.md").write_text("# Services\n", encoding="utf-8")
            (user_service / "src" / "main" / "java" / "com" / "example").mkdir(parents=True)
            (billing_service / "src" / "main" / "java" / "com" / "example").mkdir(parents=True)
            (user_service / "pom.xml").write_text("<project></project>\n", encoding="utf-8")
            (user_service / "src" / "main" / "java" / "com" / "example" / "UserService.java").write_text(
                "class UserService {}\n",
                encoding="utf-8",
            )
            (billing_service / "build.gradle").write_text("plugins { id 'java' }\n", encoding="utf-8")
            (billing_service / "src" / "main" / "java" / "com" / "example" / "BillingService.java").write_text(
                "class BillingService {}\n",
                encoding="utf-8",
            )

            facts = PROJECT_FACTS.collect_facts(repo)

        modules = modules_by_path(facts)
        self.assertIn("services/user", modules)
        self.assertIn("services/billing", modules)
        user_module = modules["services/user"]
        billing_module = modules["services/billing"]
        self.assertEqual(user_module["package_manager"], None)
        self.assertIn("java", user_module["stacks"])
        self.assertIn("java", billing_module["stacks"])
        self.assertIn("pom.xml", user_module["configs"])
        self.assertIn("build.gradle", billing_module["configs"])
        user_commands = {item["command"] for item in user_module["validation_commands"]}
        billing_commands = {item["command"] for item in billing_module["validation_commands"]}
        self.assertIn("cd services/user && mvn test", user_commands)
        self.assertIn("cd services/billing && gradle test", billing_commands)

    def test_collect_facts_ignores_generated_dependency_directories_for_modules(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            (repo / "README.md").write_text("# Generated Directories\n", encoding="utf-8")
            (repo / "oh_modules" / "cached" / "src").mkdir(parents=True)
            (repo / ".hvigor" / "cache").mkdir(parents=True)
            (repo / ".gradle" / "cache" / "src" / "main" / "java").mkdir(parents=True)
            (repo / "oh_modules" / "cached" / "package.json").write_text(
                json.dumps({"dependencies": {"react": "latest"}}),
                encoding="utf-8",
            )
            (repo / "oh_modules" / "cached" / "src" / "App.tsx").write_text(
                "export function App() { return null; }\n",
                encoding="utf-8",
            )
            (repo / ".hvigor" / "cache" / "pom.xml").write_text("<project></project>\n", encoding="utf-8")
            (repo / ".gradle" / "cache" / "build.gradle").write_text("plugins { id 'java' }\n", encoding="utf-8")
            (repo / ".gradle" / "cache" / "src" / "main" / "java" / "Generated.java").write_text(
                "class Generated {}\n",
                encoding="utf-8",
            )

            facts = PROJECT_FACTS.collect_facts(repo)

        self.assertEqual(facts["inferred"]["modules"], [])
        self.assertNotIn("oh_modules", facts["confirmed_facts"]["top_level_dirs"])
        self.assertNotIn("react-web", facts["inferred"]["primary_stacks"])
        self.assertNotIn("java", facts["inferred"]["primary_stacks"])
        languages = {item["name"] for item in facts["inferred"]["languages"]}
        self.assertNotIn("TSX", languages)
        self.assertNotIn("Java", languages)


if __name__ == "__main__":
    unittest.main()
