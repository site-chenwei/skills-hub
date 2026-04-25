import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[2]


def load_script(module_name: str, relative_path: str):
    script_path = REPO_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


PROJECT_FACTS = load_script("matrix_project_facts", "skills/project-onboarding/scripts/project_facts.py")
CHANGE_PLAN = load_script("matrix_change_plan", "skills/structured-dev/scripts/change_plan.py")
REVIEW_SCOPE = load_script("matrix_review_scope", "skills/code-review-checklist/scripts/review_scope.py")
CAPTURE_FAILURE = load_script("matrix_capture_failure", "skills/verification-and-debug/scripts/capture_failure.py")
HARMONY_BUILD = load_script("matrix_harmony_build", "skills/harmony-build/scripts/harmony_build.py")


def default_plan_args(repo: Path, paths: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        repo=str(repo),
        goal="matrix",
        paths=paths,
        interface_change=False,
        dependency_change=False,
        schema_change=False,
        security_sensitive=False,
        performance_sensitive=False,
        bugfix=False,
    )


class EngineeringMatrixTests(unittest.TestCase):
    def test_monorepo_module_facts_drive_react_and_java_expectations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            web = repo / "apps" / "web"
            api = repo / "services" / "user"
            (web / "src").mkdir(parents=True)
            (api / "src" / "main" / "java" / "com" / "example").mkdir(parents=True)
            (web / "package.json").write_text(
                json.dumps(
                    {
                        "name": "web",
                        "packageManager": "pnpm@9.0.0",
                        "dependencies": {"react": "^18.0.0", "react-dom": "^18.0.0"},
                        "scripts": {"test": "vitest run", "typecheck": "tsc --noEmit"},
                    }
                ),
                encoding="utf-8",
            )
            (web / "src" / "App.tsx").write_text("export function App() { return null; }\n", encoding="utf-8")
            (api / "pom.xml").write_text("<project></project>\n", encoding="utf-8")
            (api / "src" / "main" / "java" / "com" / "example" / "UserController.java").write_text(
                "class UserController {}\n",
                encoding="utf-8",
            )

            facts = PROJECT_FACTS.collect_facts(repo)
            modules = {item["path"]: item for item in facts["inferred"]["modules"]}

            self.assertIn("react-web", modules["apps/web"]["stacks"])
            self.assertTrue(
                any(item["command"] == "cd apps/web && pnpm test" for item in modules["apps/web"]["validation_commands"])
            )
            self.assertIn("java", modules["services/user"]["stacks"])
            self.assertTrue(
                any(item["command"] == "cd services/user && mvn test" for item in modules["services/user"]["validation_commands"])
            )

            react_plan = CHANGE_PLAN.build_plan(repo, default_plan_args(repo, ["apps/web/src/auth.ts"]))
            java_plan = CHANGE_PLAN.build_plan(
                repo,
                default_plan_args(repo, ["services/user/src/main/java/com/example/UserController.java"]),
            )

            self.assertIn("react-high-risk", react_plan["path_categories"])
            self.assertIn("java-high-risk", java_plan["path_categories"])

    def test_cross_skill_routing_avoids_known_false_positives(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)

            non_react_plan = CHANGE_PLAN.build_plan(repo, default_plan_args(repo, ["src/auth.ts"]))
            harmony_util_plan = CHANGE_PLAN.build_plan(
                repo,
                default_plan_args(repo, ["entry/src/main/ets/utils/format.ets"]),
            )
            harmony_page_plan = CHANGE_PLAN.build_plan(
                repo,
                default_plan_args(repo, ["entry/src/main/ets/pages/Index.ets"]),
            )

        self.assertNotIn("react-high-risk", non_react_plan["path_categories"])
        self.assertNotIn("react-web", non_react_plan["path_categories"])
        self.assertIn("harmony", harmony_util_plan["path_categories"])
        self.assertNotIn("harmony-high-risk", harmony_util_plan["path_categories"])
        self.assertIn("harmony-high-risk", harmony_page_plan["path_categories"])

        non_react_summary = REVIEW_SCOPE.build_summary(
            Path("/tmp/repo"),
            [{"path": "src/auth.ts", "status": "M", "additions": 1, "deletions": 0}],
            "explicit file list",
        )
        harmony_util_summary = REVIEW_SCOPE.build_summary(
            Path("/tmp/repo"),
            [{"path": "entry/src/main/ets/utils/format.ets", "status": "M", "additions": 1, "deletions": 0}],
            "explicit file list",
        )

        self.assertIn("security-sensitive", non_react_summary["risk_tags"])
        self.assertNotIn("client-contract", non_react_summary["risk_tags"])
        self.assertNotIn("public-contract", harmony_util_summary["risk_tags"])
        self.assertNotIn("harmony-ui-structure", harmony_util_summary["risk_tags"])

    def test_failure_and_harmony_build_outputs_keep_root_cause_context(self) -> None:
        details = CAPTURE_FAILURE.classify_failure_details(
            "SpringApplication failed. Could not resolve placeholder 'demo.url' in value.",
            1,
        )
        vite_category, _ = CAPTURE_FAILURE.classify_failure("VITE_API_URL=http://127.0.0.1 ECONNREFUSED", 1)
        recommendation = HARMONY_BUILD.recommend_tasks_for_paths(
            None,
            ["entry/src/main/ets/pages/Index.ets", "docs/readme.md"],
        )

        self.assertEqual(details["classification"], "java-profile-config")
        self.assertTrue(
            any(item["classification"] == "java-spring-context" for item in details["secondary_matches"])
        )
        self.assertEqual(vite_category, "network")
        self.assertEqual(recommendation["recommendations"][0]["task_template"], ":entry:assembleHap")
        self.assertTrue(recommendation["recommendations"][1]["requires_task_listing"])


if __name__ == "__main__":
    unittest.main()
