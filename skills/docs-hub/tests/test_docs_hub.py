from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_ROOT = Path(__file__).resolve().parents[1]
MANAGED_SKILL_ENTRIES = ["SKILL.md", "agents", "references", "requirements-build.txt", "run.py", "scripts"]
BUILD_SCRIPT = SKILL_ROOT / "scripts" / "build_docset_index.py"
SEARCH_SCRIPT = SKILL_ROOT / "scripts" / "search_docs.py"
INIT_SCRIPT = SKILL_ROOT / "scripts" / "local_doc_init.py"
PYTHON = sys.executable

sys.path.insert(0, str(SKILL_ROOT / "scripts"))
from _bootstrap import runtime_root  # noqa: E402
from _common import DependencyMissingError, parse_front_matter  # noqa: E402
from build_docset_index import compute_build_signature, maybe_vacuum, merge_config  # noqa: E402


_REAL_SUBPROCESS_RUN = subprocess.run


def run_subprocess(*args, **kwargs):
    kwargs.setdefault("encoding", "utf-8")
    kwargs.setdefault("errors", "replace")
    return _REAL_SUBPROCESS_RUN(*args, **kwargs)


subprocess.run = run_subprocess


def copy_skill_tree(src: Path, dst: Path) -> None:
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".deps", ".skill-init.json"))


class DocsHubRuntimeMixin:
    def setUp(self) -> None:
        super().setUp()
        runtime_tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(runtime_tmpdir.cleanup)
        self.runtime_base = Path(runtime_tmpdir.name)
        self.runtime_root = self.runtime_base / "docs-hub"
        self.subprocess_env = {
            **dict(os.environ),
            "SKILLS_HUB_RUNTIME_DIR": str(self.runtime_base),
        }

    def runtime_path(self, *parts: str) -> Path:
        return self.runtime_root.joinpath(*parts)

    def env_with(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        env = dict(self.subprocess_env)
        if extra:
            env.update(extra)
        return env


class DocsHubCommonTest(unittest.TestCase):
    def test_runtime_root_supports_shared_skills_hub_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.dict(os.environ, {"SKILLS_HUB_RUNTIME_DIR": temp_dir}, clear=False):
                self.assertEqual((Path(temp_dir) / "docs-hub").resolve(), runtime_root())

    def test_parse_front_matter_preserves_bool_scalar(self) -> None:
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("PyYAML not available in test process")
        fm, body = parse_front_matter(
            textwrap.dedent(
                """
                ---
                title: bool test
                draft: true
                ---

                content
                """
            ).lstrip()
        )
        self.assertIs(True, fm["draft"])
        self.assertEqual("\ncontent\n", body)

    def test_parse_front_matter_missing_pyyaml_fails_fast(self) -> None:
        real_import = __import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "yaml":
                raise ImportError("yaml missing for test")
            return real_import(name, globals, locals, fromlist, level)

        with mock.patch("builtins.__import__", side_effect=fake_import):
            with self.assertRaises(DependencyMissingError):
                parse_front_matter("---\ntitle: missing yaml\n---\ncontent\n")

    def test_maybe_vacuum_reclaims_free_pages(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        db_path = Path(tmpdir.name) / "vacuum.sqlite"
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, body TEXT)")
            payload = "x" * 4096
            conn.executemany("INSERT INTO t(body) VALUES(?)", [(payload,) for _ in range(2048)])
            conn.commit()
            conn.execute("DELETE FROM t WHERE id % 2 = 0")
            conn.commit()

            before = conn.execute("PRAGMA freelist_count").fetchone()[0]
            self.assertGreaterEqual(before, 1024)
            stats = maybe_vacuum(conn)
            after = conn.execute("PRAGMA freelist_count").fetchone()[0]
        finally:
            conn.close()

        self.assertTrue(stats["vacuumed"])
        self.assertLess(after, before)


class DocsHubLayoutTest(unittest.TestCase):
    def test_skill_bundle_contains_required_entries(self) -> None:
        for entry in MANAGED_SKILL_ENTRIES:
            self.assertTrue((SKILL_ROOT / entry).exists(), entry)


class DocsHubSearchSkillTest(DocsHubRuntimeMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._shared_tmpdir = tempfile.TemporaryDirectory()
        cls.shared_hub_root = Path(cls._shared_tmpdir.name)
        cls._shared_runtime_tmpdir = tempfile.TemporaryDirectory()
        cls.shared_runtime_base = Path(cls._shared_runtime_tmpdir.name)
        cls.shared_runtime_root = cls.shared_runtime_base / "docs-hub"
        (cls.shared_hub_root / "docs" / "bootstrap").mkdir(parents=True, exist_ok=True)
        (cls.shared_hub_root / "index").mkdir(parents=True, exist_ok=True)
        (cls.shared_hub_root / "docsets.json").write_text(
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
                            "id": "bootstrap",
                            "name": "Bootstrap",
                            "root": "docs/bootstrap",
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        subprocess.run(
            [PYTHON, str(INIT_SCRIPT), "--skill-root", str(SKILL_ROOT), "--hub-root", str(cls.shared_hub_root)],
            check=True,
            capture_output=True,
            text=True,
            env={
                **dict(os.environ),
                "SKILLS_HUB_RUNTIME_DIR": str(cls.shared_runtime_base),
            },
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._shared_tmpdir.cleanup()
        cls._shared_runtime_tmpdir.cleanup()

    def setUp(self) -> None:
        super().setUp()
        shutil.copytree(self.shared_runtime_root, self.runtime_root, dirs_exist_ok=True)
        state_path = self.runtime_path(".skill-init.json")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["site_packages"] = str(self.runtime_path(".deps", "site-packages"))
        state["runtime_root"] = str(self.runtime_root)
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        self._repo_skill_initialized = True

    def ensure_repo_skill_initialized(self) -> None:
        if self._repo_skill_initialized:
            return
        subprocess.run(
            [PYTHON, str(INIT_SCRIPT), "--skill-root", str(SKILL_ROOT), "--hub-root", str(self.shared_hub_root)],
            check=True,
            capture_output=True,
            text=True,
            env=self.subprocess_env,
        )
        self._repo_skill_initialized = True

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

    def write_doc(self, hub_root: Path, rel_path: str, content: str) -> Path:
        path = hub_root / "docs" / "testset" / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
        return path

    def run_build(self, hub_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        self.ensure_repo_skill_initialized()
        return subprocess.run(
            [PYTHON, str(BUILD_SCRIPT), "--hub-root", str(hub_root), "--docset", "testset", *args],
            check=True,
            capture_output=True,
            text=True,
            env=self.subprocess_env,
        )

    def run_search(self, hub_root: Path, *args: str) -> list[dict]:
        self.ensure_repo_skill_initialized()
        proc = subprocess.run(
            [PYTHON, str(SEARCH_SCRIPT), "--hub-root", str(hub_root), *args, "--json"],
            check=True,
            capture_output=True,
            text=True,
            env=self.subprocess_env,
        )
        return json.loads(proc.stdout)

    def read_build_signature(self, hub_root: Path, docset_id: str = "testset") -> str | None:
        db_path = hub_root / "index" / f"{docset_id}.sqlite"
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute("SELECT value FROM meta WHERE key='build_signature'").fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    def test_explicit_query_hub_root_overrides_saved_init_hub_root(self) -> None:
        self.ensure_repo_skill_initialized()
        hub_root = self.make_hub()
        self.write_doc(
            hub_root,
            "root.md",
            """
            ---
            title: "root doc"
            source_url: "https://example.com/root"
            menu_path:
              - "指南"
            ---

            # root doc

            hello root file
            """,
        )
        self.run_build(hub_root)
        proc = subprocess.run(
            [PYTHON, str(SEARCH_SCRIPT), "--hub-root", str(hub_root), "hello", "--docset", "testset", "--json"],
            check=True,
            capture_output=True,
            text=True,
            env=self.subprocess_env,
        )
        rows = json.loads(proc.stdout)
        self.assertEqual(["root.md"], [row["rel_path"] for row in rows])
        self.assertTrue(rows[0]["abs_path"].endswith("/docs/testset/root.md"))

    def test_rebuild_stale_refreshes_existing_index(self) -> None:
        hub_root = self.make_hub()
        doc_path = self.write_doc(
            hub_root,
            "sub/a.md",
            """
            ---
            title: "alpha"
            source_url: "https://example.com/a"
            menu_path:
              - "指南"
            ---

            # alpha

            original content
            """,
        )
        self.run_build(hub_root)
        doc_path.write_text(
            textwrap.dedent(
                """
                ---
                title: "alpha"
                source_url: "https://example.com/a"
                menu_path:
                  - "指南"
                ---

                # alpha

                updated content only
                """
            ).lstrip(),
            encoding="utf-8",
        )

        rows = self.run_search(hub_root, "--rebuild-stale", "updated", "--docset", "testset")
        self.assertEqual(["sub/a.md"], [row["rel_path"] for row in rows])

    def test_short_tokens_respect_or_semantics(self) -> None:
        hub_root = self.make_hub()
        self.write_doc(
            hub_root,
            "sub/a.md",
            """
            ---
            title: "doc-a"
            source_url: "https://example.com/a"
            menu_path:
              - "FAQ"
            ---

            # doc-a

            光标
            """,
        )
        self.write_doc(
            hub_root,
            "sub/b.md",
            """
            ---
            title: "doc-b"
            source_url: "https://example.com/b"
            menu_path:
              - "FAQ"
            ---

            # doc-b

            跟随
            """,
        )
        self.run_build(hub_root)
        rows = self.run_search(hub_root, "光标", "跟随", "--match", "or", "--docset", "testset")
        self.assertEqual(["sub/a.md", "sub/b.md"], [row["rel_path"] for row in rows])

    def test_code_fence_fake_heading_is_ignored(self) -> None:
        hub_root = self.make_hub()
        self.write_doc(
            hub_root,
            "sub/code-fence.md",
            """
            ---
            title: "Code Fence"
            source_url: "https://example.com/code-fence"
            menu_path:
              - "指南"
            ---

            # Real Heading

            ```md
            # fake heading
            codesentinel
            ```

            ## Later

            later-sentinel
            """,
        )
        self.run_build(hub_root)
        rows = self.run_search(hub_root, "codesentinel", "--docset", "testset")
        self.assertEqual(["sub/code-fence.md"], [row["rel_path"] for row in rows])
        self.assertEqual("Real Heading", rows[0]["heading_path"])

    def test_tilde_fence_fake_heading_is_ignored(self) -> None:
        hub_root = self.make_hub()
        self.write_doc(
            hub_root,
            "sub/tilde-fence.md",
            """
            ---
            title: "Tilde Fence"
            source_url: "https://example.com/tilde-fence"
            menu_path:
              - "指南"
            ---

            # Real Tilde Heading

            ~~~md
            # fake tilde heading
            tildesentinel
            ~~~

            ## Tilde Later

            tilde-later-sentinel
            """,
        )
        self.run_build(hub_root)
        rows = self.run_search(hub_root, "tildesentinel", "--docset", "testset")
        self.assertEqual(["sub/tilde-fence.md"], [row["rel_path"] for row in rows])
        self.assertEqual("Real Tilde Heading", rows[0]["heading_path"])

    def test_mtime_unchanged_second_build_skips_all(self) -> None:
        hub_root = self.make_hub()
        self.write_doc(
            hub_root,
            "sub/a.md",
            """
            ---
            title: "alpha"
            source_url: "https://example.com/a"
            menu_path:
              - "指南"
            ---

            # alpha

            mtimeskipsentinel
            """,
        )
        first = self.run_build(hub_root)
        self.assertIn("'indexed': 1", first.stdout)
        # 非 Windows 平台命中 stat 快路径；Windows 上会回退到哈希校验，避免同尺寸覆盖写被误判。
        second = self.run_build(hub_root)
        self.assertIn("'indexed': 0", second.stdout)
        self.assertIn("'skipped_unchanged': 1", second.stdout)
        if os.name == "nt":
            self.assertIn("'skipped_fast': 0", second.stdout)
            self.assertIn("'skipped_hash_verified': 1", second.stdout)
        else:
            self.assertIn("'skipped_fast': 1", second.stdout)

    def test_content_change_with_preserved_mtime_still_reindexes(self) -> None:
        """模拟 cp -p / rsync -t：mtime 被保留但内容变了，必须重建。"""
        hub_root = self.make_hub()
        doc_path = self.write_doc(
            hub_root,
            "sub/preserved.md",
            """
            ---
            title: "preserved mtime"
            source_url: "https://example.com/preserved"
            menu_path:
              - "指南"
            ---

            # preserved mtime

            originalpreservedsentinel
            """,
        )
        self.run_build(hub_root)
        original_stat = doc_path.stat()
        # 改内容后显式把 mtime 写回原值
        doc_path.write_text(
            textwrap.dedent(
                """
                ---
                title: "preserved mtime"
                source_url: "https://example.com/preserved"
                menu_path:
                  - "指南"
                ---

                # preserved mtime

                updatedpreservedsentinel
                """
            ).lstrip(),
            encoding="utf-8",
        )
        os.utime(doc_path, (original_stat.st_atime, original_stat.st_mtime))

        rows = self.run_search(hub_root, "--rebuild-stale", "updatedpreservedsentinel", "--docset", "testset")
        self.assertEqual(["sub/preserved.md"], [row["rel_path"] for row in rows])

    def test_content_change_same_size_with_preserved_mtime_still_reindexes(self) -> None:
        """即便 size 和 mtime 一样，只要 ctime 变化，仍要落回哈希校验。"""
        hub_root = self.make_hub()
        doc_path = self.write_doc(
            hub_root,
            "sub/preserved-same-size.md",
            """
            ---
            title: "preserved same size"
            source_url: "https://example.com/preserved-same-size"
            menu_path:
              - "指南"
            ---

            # preserved same size

            alphaequal1
            """,
        )
        self.run_build(hub_root)
        original_stat = doc_path.stat()
        doc_path.write_text(
            textwrap.dedent(
                """
                ---
                title: "preserved same size"
                source_url: "https://example.com/preserved-same-size"
                menu_path:
                  - "指南"
                ---

                # preserved same size

                omegaequal1
                """
            ).lstrip(),
            encoding="utf-8",
        )
        os.utime(doc_path, (original_stat.st_atime, original_stat.st_mtime))

        rows = self.run_search(hub_root, "--rebuild-stale", "omegaequal1", "--docset", "testset")
        self.assertEqual(["sub/preserved-same-size.md"], [row["rel_path"] for row in rows])

    def test_setext_headings_are_recognized(self) -> None:
        hub_root = self.make_hub()
        self.write_doc(
            hub_root,
            "sub/setext.md",
            """
            ---
            title: "Setext Doc"
            source_url: "https://example.com/setext"
            menu_path:
              - "指南"
            ---

            功能介绍
            ========

            setextintrosentinel

            常见问题
            --------

            setextfaqsentinel
            """,
        )
        self.run_build(hub_root)
        intro_rows = self.run_search(hub_root, "setextintrosentinel", "--docset", "testset")
        faq_rows = self.run_search(hub_root, "setextfaqsentinel", "--docset", "testset")
        self.assertEqual(["sub/setext.md"], [row["rel_path"] for row in intro_rows])
        self.assertEqual("功能介绍", intro_rows[0]["heading_path"])
        self.assertEqual("功能介绍 > 常见问题", faq_rows[0]["heading_path"])

    def test_refresh_with_missing_docset_root_skips_that_docset(self) -> None:
        """refresh 模式遇到 docset root 缺失时应跳过该 docset，其他 docset 照常返回结果。"""
        hub_root = self.make_hub()
        self.write_doc(
            hub_root,
            "ok.md",
            """
            ---
            title: "ok doc"
            source_url: "https://example.com/ok"
            menu_path:
              - "指南"
            ---

            # ok doc

            refreshmissingrootok
            """,
        )
        cfg = json.loads((hub_root / "docsets.json").read_text(encoding="utf-8"))
        cfg["docsets"].append({"id": "broken", "name": "Broken", "root": "docs/does-not-exist"})
        (hub_root / "docsets.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

        rows = self.run_search(hub_root, "--rebuild-stale", "refreshmissingrootok")
        self.assertEqual(["ok.md"], [row["rel_path"] for row in rows])

    def test_section_filter_only_returns_matching_section(self) -> None:
        hub_root = self.make_hub()
        self.write_doc(
            hub_root,
            "sub/faq.md",
            """
            ---
            title: "faq doc"
            source_url: "https://example.com/faq"
            menu_path:
              - "FAQ"
            ---

            # faq doc

            sharedsectiontoken
            """,
        )
        self.write_doc(
            hub_root,
            "sub/guide.md",
            """
            ---
            title: "guide doc"
            source_url: "https://example.com/guide"
            menu_path:
              - "指南"
            ---

            # guide doc

            sharedsectiontoken
            """,
        )
        self.run_build(hub_root)
        rows = self.run_search(hub_root, "sharedsectiontoken", "--section", "FAQ", "--docset", "testset")
        self.assertEqual(["sub/faq.md"], [row["rel_path"] for row in rows])

    def test_include_nav_switches_navigation_page_visibility(self) -> None:
        hub_root = self.make_hub()
        self.write_doc(
            hub_root,
            "sub/nav.md",
            """
            ---
            title: "nav doc"
            source_url: "https://example.com/nav"
            ---

            navonlysentinel
            """,
        )
        self.run_build(hub_root)

        hidden_rows = self.run_search(hub_root, "navonlysentinel", "--docset", "testset")
        visible_rows = self.run_search(hub_root, "navonlysentinel", "--docset", "testset", "--include-nav")

        self.assertEqual([], hidden_rows)
        self.assertEqual(["sub/nav.md"], [row["rel_path"] for row in visible_rows])
        self.assertTrue(visible_rows[0]["is_nav"])

    def test_title_fallback_prefers_markdown_heading_then_filename_stem(self) -> None:
        hub_root = self.make_hub()
        self.write_doc(
            hub_root,
            "sub/h1-title.md",
            """
            ---
            source_url: "https://example.com/h1-title"
            menu_path:
              - "指南"
            ---

            # Heading Derived Title

            h1titlesentinel
            """,
        )
        self.write_doc(
            hub_root,
            "sub/stem-only.md",
            """
            ---
            source_url: "https://example.com/stem-only"
            menu_path:
              - "指南"
            ---

            plain body without heading
            stemonlysentinel
            """,
        )
        self.write_doc(
            hub_root,
            "sub/setext-title.md",
            """
            ---
            source_url: "https://example.com/setext-title"
            menu_path:
              - "指南"
            ---

            Setext Derived Title
            ====================

            setexttitlesentinel
            """,
        )
        self.run_build(hub_root)

        h1_rows = self.run_search(hub_root, "h1titlesentinel", "--docset", "testset")
        stem_rows = self.run_search(hub_root, "stemonlysentinel", "--docset", "testset")
        setext_rows = self.run_search(hub_root, "setexttitlesentinel", "--docset", "testset")

        self.assertEqual("Heading Derived Title", h1_rows[0]["title"])
        self.assertEqual("stem-only", stem_rows[0]["title"])
        self.assertEqual("Setext Derived Title", setext_rows[0]["title"])

    def test_match_all_with_long_and_short_tokens_requires_both(self) -> None:
        hub_root = self.make_hub()
        self.write_doc(
            hub_root,
            "sub/long-only.md",
            """
            ---
            title: "long only"
            source_url: "https://example.com/long-only"
            menu_path:
              - "指南"
            ---

            # long only

            alphalongtoken
            """,
        )
        self.write_doc(
            hub_root,
            "sub/both.md",
            """
            ---
            title: "both tokens"
            source_url: "https://example.com/both"
            menu_path:
              - "指南"
            ---

            # both tokens

            alphalongtoken 光标
            """,
        )
        self.run_build(hub_root)
        rows = self.run_search(hub_root, "alphalongtoken", "光标", "--match", "all", "--docset", "testset")
        self.assertEqual(["sub/both.md"], [row["rel_path"] for row in rows])

    def test_multi_word_phrase_falls_back_to_split_terms(self) -> None:
        hub_root = self.make_hub()
        self.write_doc(
            hub_root,
            "sub/phrase-fallback.md",
            """
            ---
            title: "phrase fallback"
            source_url: "https://example.com/phrase-fallback"
            menu_path:
              - "指南"
            ---

            # phrase fallback

            输入法组件支持光标自动跟随能力。
            """,
        )
        self.run_build(hub_root)
        rows = self.run_search(hub_root, "输入法 光标 跟随", "--docset", "testset")
        self.assertEqual(["sub/phrase-fallback.md"], [row["rel_path"] for row in rows])
        self.assertIn("【输入法】", rows[0]["snippet"])

    def test_multi_phrase_fallback_merges_split_results(self) -> None:
        hub_root = self.make_hub()
        self.write_doc(
            hub_root,
            "sub/input-method.md",
            """
            ---
            title: "input method"
            source_url: "https://example.com/input-method"
            menu_path:
              - "指南"
            ---

            # input method

            输入法服务能力说明
            """,
        )
        self.write_doc(
            hub_root,
            "sub/cursor-follow.md",
            """
            ---
            title: "cursor follow"
            source_url: "https://example.com/cursor-follow"
            menu_path:
              - "指南"
            ---

            # cursor follow

            光标跟随体验优化
            """,
        )
        self.run_build(hub_root)
        rows = self.run_search(hub_root, "输入法 服务", "光标 跟随", "--docset", "testset")
        self.assertEqual(
            {"sub/input-method.md", "sub/cursor-follow.md"},
            {row["rel_path"] for row in rows},
        )

    def test_fallback_prefers_more_matched_terms_over_title_only_match(self) -> None:
        hub_root = self.make_hub()
        self.write_doc(
            hub_root,
            "sub/title-only.md",
            """
            ---
            title: "alpha title"
            source_url: "https://example.com/title-only"
            menu_path:
              - "指南"
            ---

            # alpha title

            noise
            """,
        )
        self.write_doc(
            hub_root,
            "sub/multi-hit.md",
            """
            ---
            title: "multi hit"
            source_url: "https://example.com/multi-hit"
            menu_path:
              - "指南"
            ---

            # multi hit

            alpha gamma delta
            """,
        )
        self.run_build(hub_root)
        rows = self.run_search(hub_root, "alpha delta gamma", "--docset", "testset")
        self.assertEqual(["sub/multi-hit.md", "sub/title-only.md"], [row["rel_path"] for row in rows])
        self.assertGreater(rows[0]["matched_terms_count"], rows[1]["matched_terms_count"])

    def test_or_query_prefers_documents_matching_more_keywords(self) -> None:
        hub_root = self.make_hub()
        self.write_doc(
            hub_root,
            "sub/title-alpha.md",
            """
            ---
            title: "alpha title"
            source_url: "https://example.com/title-alpha"
            menu_path:
              - "指南"
            ---

            # alpha title

            noise
            """,
        )
        self.write_doc(
            hub_root,
            "sub/body-alpha-gamma-delta.md",
            """
            ---
            title: "body keywords"
            source_url: "https://example.com/body-keywords"
            menu_path:
              - "指南"
            ---

            # body keywords

            alpha gamma delta
            """,
        )
        self.run_build(hub_root)
        rows = self.run_search(hub_root, "alpha", "gamma", "delta", "--docset", "testset")
        self.assertEqual(
            ["sub/body-alpha-gamma-delta.md", "sub/title-alpha.md"],
            [row["rel_path"] for row in rows],
        )
        self.assertGreater(rows[0]["matched_terms_count"], rows[1]["matched_terms_count"])

    def test_title_match_uses_title_snippet_when_body_has_no_keyword(self) -> None:
        hub_root = self.make_hub()
        self.write_doc(
            hub_root,
            "sub/title-snippet.md",
            """
            ---
            title: "api.error.1001"
            source_url: "https://example.com/title-snippet"
            menu_path:
              - "指南"
            ---

            # heading

            body without the token
            """,
        )
        self.run_build(hub_root)
        rows = self.run_search(hub_root, "api.error.1001", "--docset", "testset")
        self.assertEqual(["sub/title-snippet.md"], [row["rel_path"] for row in rows])
        self.assertEqual("title", rows[0]["snippet_source"])
        self.assertIn("【api.error.1001】", rows[0]["snippet"])

    def test_snippet_is_centered_on_hit_and_highlighted(self) -> None:
        hub_root = self.make_hub()
        self.write_doc(
            hub_root,
            "sub/snippet.md",
            f"""
            ---
            title: "snippet doc"
            source_url: "https://example.com/snippet"
            menu_path:
              - "指南"
            ---

            # snippet doc

            {"prefix " * 80}needlehighlighttoken{" suffix" * 20}
            """,
        )
        self.run_build(hub_root)
        rows = self.run_search(hub_root, "needlehighlighttoken", "--docset", "testset")
        self.assertEqual(["sub/snippet.md"], [row["rel_path"] for row in rows])
        self.assertIn("【needlehighlighttoken】", rows[0]["snippet"])
        self.assertTrue(rows[0]["snippet"].startswith("…"), rows[0]["snippet"])

    def test_build_all_rebuilds_all_docsets_and_cleans_wal_sidecars(self) -> None:
        self.ensure_repo_skill_initialized()
        hub_root = self.make_hub()
        cfg = json.loads((hub_root / "docsets.json").read_text(encoding="utf-8"))
        cfg["docsets"].append({"id": "extraset", "name": "Extra", "root": "docs/extraset"})
        (hub_root / "docs" / "extraset").mkdir(parents=True, exist_ok=True)
        (hub_root / "docs" / "extraset" / "extra.md").write_text(
            textwrap.dedent(
                """
                ---
                title: "extra doc"
                source_url: "https://example.com/extra"
                menu_path:
                  - "指南"
                ---

                # extra doc

                extra-docset-sentinel
                """
            ).lstrip(),
            encoding="utf-8",
        )
        (hub_root / "docsets.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

        subprocess.run(
            [PYTHON, str(BUILD_SCRIPT), "--hub-root", str(hub_root), "--docset", "all", "--rebuild"],
            check=True,
            capture_output=True,
            text=True,
            env=self.subprocess_env,
        )

        self.assertTrue((hub_root / "index" / "testset.sqlite").exists())
        self.assertTrue((hub_root / "index" / "extraset.sqlite").exists())
        self.assertFalse((hub_root / "index" / "testset.sqlite-wal").exists())
        self.assertFalse((hub_root / "index" / "testset.sqlite-shm").exists())
        self.assertFalse((hub_root / "index" / "extraset.sqlite-wal").exists())
        self.assertFalse((hub_root / "index" / "extraset.sqlite-shm").exists())

    def test_init_fails_without_resolvable_hub_root(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        proc = subprocess.run(
            [PYTHON, str(INIT_SCRIPT), "--skill-root", str(SKILL_ROOT)],
            check=False,
            cwd=tmpdir.name,
            capture_output=True,
            text=True,
            env=self.subprocess_env,
        )
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("未找到可用的 DocsHub 根目录", proc.stderr)

    def test_init_with_explicit_invalid_hub_root_fails_immediately(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        invalid_root = Path(tmpdir.name) / "not-a-hub"
        invalid_root.mkdir(parents=True, exist_ok=True)
        valid_hub = self.make_hub()
        proc = subprocess.run(
            [PYTHON, str(INIT_SCRIPT), "--skill-root", str(SKILL_ROOT), "--hub-root", str(invalid_root)],
            check=False,
            capture_output=True,
            text=True,
            env=self.env_with({"CODEX_DOC_HUB": str(valid_hub)}),
        )
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("指定路径不是有效的 DocsHub 根目录", proc.stderr)

    def test_init_auto_builds_missing_indexes(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        isolated_skill_root = Path(tmpdir.name) / "docs-hub"
        copy_skill_tree(SKILL_ROOT, isolated_skill_root)
        hub_root = self.make_hub()
        self.write_doc(
            hub_root,
            "sub/auto.md",
            """
            ---
            title: "auto build"
            source_url: "https://example.com/auto"
            menu_path:
              - "指南"
            ---

            # auto build

            content for auto build
            """,
        )
        subprocess.run(
            [PYTHON, str(isolated_skill_root / "scripts" / "local_doc_init.py"), "--skill-root", str(isolated_skill_root), "--hub-root", str(hub_root)],
            check=True,
            capture_output=True,
            text=True,
            env=self.subprocess_env,
        )
        self.assertTrue((hub_root / "index" / "testset.sqlite").exists())

    def test_init_failure_does_not_leave_state_file(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        isolated_skill_root = Path(tmpdir.name) / "docs-hub"
        copy_skill_tree(SKILL_ROOT, isolated_skill_root)
        init_state = self.runtime_path(".skill-init.json")
        if init_state.exists():
            init_state.unlink()
        hub_root = Path(tmpdir.name) / "hub"
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
                        "nav_rules": {"filenames": ["README.md"], "min_body_chars": 300},
                        "chunk": {"target_chars": 1200, "max_chars": 1500, "overlap_chars": 150},
                    },
                    "docsets": [{"id": "broken", "name": "Broken", "root": "docs/missing"}],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        proc = subprocess.run(
            [PYTHON, str(isolated_skill_root / "scripts" / "local_doc_init.py"), "--skill-root", str(isolated_skill_root), "--hub-root", str(hub_root)],
            check=False,
            capture_output=True,
            text=True,
            env=self.subprocess_env,
        )

        self.assertNotEqual(0, proc.returncode)
        self.assertFalse(self.runtime_path(".skill-init.json").exists())

    def test_init_cleans_stale_site_packages_before_reinstall(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        isolated_skill_root = Path(tmpdir.name) / "docs-hub"
        copy_skill_tree(SKILL_ROOT, isolated_skill_root)
        stale_file = self.runtime_path(".deps", "site-packages", "stale_only.py")
        stale_file.parent.mkdir(parents=True, exist_ok=True)
        stale_file.write_text("stale = True\n", encoding="utf-8")

        hub_root = self.make_hub()
        subprocess.run(
            [
                PYTHON,
                str(isolated_skill_root / "scripts" / "local_doc_init.py"),
                "--skill-root",
                str(isolated_skill_root),
                "--hub-root",
                str(hub_root),
                "--refresh-deps",
            ],
            check=True,
            capture_output=True,
            text=True,
            env=self.subprocess_env,
        )

        self.assertFalse(stale_file.exists())

    def test_init_reuses_existing_site_packages_when_still_valid(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        isolated_skill_root = Path(tmpdir.name) / "docs-hub"
        copy_skill_tree(SKILL_ROOT, isolated_skill_root)
        hub_root = self.make_hub()

        subprocess.run(
            [PYTHON, str(isolated_skill_root / "scripts" / "local_doc_init.py"), "--skill-root", str(isolated_skill_root), "--hub-root", str(hub_root)],
            check=True,
            capture_output=True,
            text=True,
            env=self.subprocess_env,
        )
        sentinel = self.runtime_path(".deps", "site-packages", "cache-sentinel.txt")
        sentinel.write_text("reuse me\n", encoding="utf-8")

        proc = subprocess.run(
            [PYTHON, str(isolated_skill_root / "scripts" / "local_doc_init.py"), "--skill-root", str(isolated_skill_root), "--hub-root", str(hub_root)],
            check=True,
            capture_output=True,
            text=True,
            env=self.subprocess_env,
        )

        self.assertIn("复用已有 skill 依赖", proc.stdout)
        self.assertTrue(sentinel.exists())

    def test_init_rebuilds_stale_indexes(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        isolated_skill_root = Path(tmpdir.name) / "docs-hub"
        copy_skill_tree(SKILL_ROOT, isolated_skill_root)
        hub_root = self.make_hub()
        self.write_doc(
            hub_root,
            "sub/stale-index.md",
            """
            ---
            title: "stale index"
            source_url: "https://example.com/stale-index"
            menu_path:
              - "指南"
            ---

            # stale index

            staleindexsentinel
            """,
        )
        self.run_build(hub_root)
        old_signature = self.read_build_signature(hub_root)

        cfg = json.loads((hub_root / "docsets.json").read_text(encoding="utf-8"))
        cfg["defaults"]["chunk"]["target_chars"] = 900
        (hub_root / "docsets.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        expected_signature = compute_build_signature(merge_config(cfg["defaults"], cfg["docsets"][0]))

        subprocess.run(
            [PYTHON, str(isolated_skill_root / "scripts" / "local_doc_init.py"), "--skill-root", str(isolated_skill_root), "--hub-root", str(hub_root)],
            check=True,
            capture_output=True,
            text=True,
            env=self.subprocess_env,
        )

        new_signature = self.read_build_signature(hub_root)
        self.assertNotEqual(old_signature, new_signature)
        self.assertEqual(expected_signature, new_signature)

    def test_init_accepts_workspace_root_with_nested_docsearch(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        isolated_skill_root = Path(tmpdir.name) / "docs-hub"
        copy_skill_tree(SKILL_ROOT, isolated_skill_root)
        workspace_root = Path(tmpdir.name) / "workspace"
        hub_root = workspace_root / "doc-search"
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
                        "nav_rules": {"filenames": ["README.md"], "min_body_chars": 300},
                        "chunk": {"target_chars": 1200, "max_chars": 1500, "overlap_chars": 150},
                    },
                    "docsets": [{"id": "testset", "name": "Test", "root": "docs/testset"}],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        subprocess.run(
            [PYTHON, str(isolated_skill_root / "scripts" / "local_doc_init.py"), "--skill-root", str(isolated_skill_root), "--hub-root", str(workspace_root)],
            check=True,
            capture_output=True,
            text=True,
            env=self.subprocess_env,
        )
        state = json.loads(self.runtime_path(".skill-init.json").read_text(encoding="utf-8"))
        self.assertEqual(str(hub_root.resolve()), state["hub_root"])

    def test_missing_skill_init_mentions_doc_hub_init(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        isolated_skill_root = Path(tmpdir.name) / "docs-hub"
        copy_skill_tree(SKILL_ROOT, isolated_skill_root)
        init_state = self.runtime_path(".skill-init.json")
        if init_state.exists():
            init_state.unlink()
        hub_root = self.make_hub()
        proc = subprocess.run(
            [PYTHON, str(isolated_skill_root / "scripts" / "search_docs.py"), "--hub-root", str(hub_root), "输入法"],
            check=False,
            capture_output=True,
            text=True,
            env=self.subprocess_env,
        )
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("$docs-hub init", proc.stderr)

    def test_query_prefers_saved_init_hub_root(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        isolated_skill_root = Path(tmpdir.name) / "docs-hub"
        copy_skill_tree(SKILL_ROOT, isolated_skill_root)
        hub_root = self.make_hub()
        self.write_doc(
            hub_root,
            "sub/a.md",
            """
            ---
            title: "alpha"
            source_url: "https://example.com/a"
            menu_path:
              - "指南"
            ---

            # alpha

            reusable content
            """,
        )
        subprocess.run(
            [PYTHON, str(isolated_skill_root / "scripts" / "local_doc_init.py"), "--skill-root", str(isolated_skill_root), "--hub-root", str(hub_root)],
            check=True,
            capture_output=True,
            text=True,
            env=self.subprocess_env,
        )
        proc = subprocess.run(
            [PYTHON, str(isolated_skill_root / "scripts" / "search_docs.py"), "reusable", "--docset", "testset", "--json"],
            check=True,
            capture_output=True,
            text=True,
            cwd=tmpdir.name,
            env=self.subprocess_env,
        )
        rows = json.loads(proc.stdout)
        self.assertEqual(["sub/a.md"], [row["rel_path"] for row in rows])

    def test_refresh_prefers_saved_init_hub_root(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        isolated_skill_root = Path(tmpdir.name) / "docs-hub"
        copy_skill_tree(SKILL_ROOT, isolated_skill_root)
        hub_root = self.make_hub()
        doc_path = self.write_doc(
            hub_root,
            "sub/a.md",
            """
            ---
            title: "alpha"
            source_url: "https://example.com/a"
            menu_path:
              - "指南"
            ---

            # alpha

            original refresh content
            """,
        )
        subprocess.run(
            [PYTHON, str(isolated_skill_root / "scripts" / "local_doc_init.py"), "--skill-root", str(isolated_skill_root), "--hub-root", str(hub_root)],
            check=True,
            capture_output=True,
            text=True,
            env=self.subprocess_env,
        )
        doc_path.write_text(
            textwrap.dedent(
                """
                ---
                title: "alpha"
                source_url: "https://example.com/a"
                menu_path:
                  - "指南"
                ---

                # alpha

                refreshed content only
                """
            ).lstrip(),
            encoding="utf-8",
        )
        proc = subprocess.run(
            [PYTHON, str(isolated_skill_root / "scripts" / "search_docs.py"), "--rebuild-stale", "refreshed", "--docset", "testset", "--json"],
            check=True,
            capture_output=True,
            text=True,
            cwd=tmpdir.name,
            env=self.subprocess_env,
        )
        rows = json.loads(proc.stdout)
        self.assertEqual(["sub/a.md"], [row["rel_path"] for row in rows])


if __name__ == "__main__":
    unittest.main()
