from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from catalog import load_or_build_catalog, update_catalog  # noqa: E402


class CatalogFreshnessTest(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        self.hub_root = Path(tmpdir.name)
        (self.hub_root / "docs" / "testset").mkdir(parents=True)
        (self.hub_root / "index").mkdir()
        self.write_docsets(
            [
                {
                    "id": "testset",
                    "name": "Test",
                    "root": "docs/testset",
                    "topics": ["Old Topic"],
                    "recommended_queries": ["Old Query"],
                    "source_sets": [{"id": "old-source"}],
                }
            ]
        )

    def write_docsets(self, docsets: list[dict]) -> None:
        payload = {
            "version": 1,
            "defaults": {},
            "docsets": docsets,
        }
        (self.hub_root / "docsets.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def write_index(self, *, built_at: str, title: str = "Indexed Topic") -> None:
        db_path = self.hub_root / "index" / "testset.sqlite"
        if db_path.exists():
            db_path.unlink()
        conn = sqlite3.connect(db_path)
        try:
            conn.executescript(
                """
                CREATE TABLE documents (
                    id INTEGER PRIMARY KEY,
                    rel_path TEXT NOT NULL UNIQUE,
                    title TEXT,
                    section TEXT,
                    doc_type TEXT,
                    source_url TEXT,
                    is_nav INTEGER NOT NULL DEFAULT 0
                );
                CREATE VIRTUAL TABLE chunks USING fts5(
                    title,
                    symbols,
                    body,
                    doc_id UNINDEXED,
                    chunk_idx UNINDEXED,
                    tokenize = 'trigram'
                );
                CREATE TABLE meta (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
                """
            )
            conn.execute(
                """
                INSERT INTO documents(rel_path, title, section, doc_type, source_url, is_nav)
                VALUES('guide.md', ?, 'Guide', 'doc', 'https://example.com/guide', 0)
                """,
                (title,),
            )
            conn.execute(
                "INSERT INTO chunks(title, symbols, body, doc_id, chunk_idx) VALUES(?, '', 'body', 1, 0)",
                (title,),
            )
            conn.execute("INSERT INTO meta(key, value) VALUES('built_at', ?)", (built_at,))
            conn.execute("INSERT INTO meta(key, value) VALUES('build_signature', 'sig')")
            conn.execute("INSERT INTO meta(key, value) VALUES('build_logic_version', 'test')")
            conn.commit()
        finally:
            conn.close()

    def test_load_or_build_catalog_rebuilds_when_docsets_metadata_changes(self) -> None:
        self.write_index(built_at="2026-05-05T00:00:00+00:00")
        stale_payload = update_catalog(self.hub_root)
        self.assertEqual(["Old Topic"], stale_payload["docsets"][0]["topics"])

        self.write_docsets(
            [
                {
                    "id": "testset",
                    "name": "Test",
                    "root": "docs/testset",
                    "topics": ["New Topic"],
                    "recommended_queries": ["New Query"],
                    "source_sets": [{"id": "new-source", "description": "explicit"}],
                }
            ]
        )

        payload = load_or_build_catalog(self.hub_root)

        self.assertEqual(["New Topic"], payload["docsets"][0]["topics"])
        self.assertEqual(["New Query"], payload["docsets"][0]["recommended_queries"])
        self.assertEqual([{"id": "new-source", "description": "explicit"}], payload["docsets"][0]["source_sets"])
        persisted = json.loads((self.hub_root / "index" / "catalog.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["freshness"], persisted["freshness"])

    def test_load_or_build_catalog_rebuilds_when_docset_index_status_changes(self) -> None:
        stale_payload = update_catalog(self.hub_root)
        self.assertEqual("missing-index", stale_payload["docsets"][0]["status"])

        self.write_docsets(
            [
                {
                    "id": "testset",
                    "name": "Test",
                    "root": "docs/testset",
                }
            ]
        )
        self.write_index(built_at="2026-05-05T01:02:03+00:00")

        payload = load_or_build_catalog(self.hub_root)

        self.assertEqual("indexed", payload["docsets"][0]["status"])
        self.assertEqual("2026-05-05T01:02:03+00:00", payload["docsets"][0]["built_at"])
        self.assertEqual(1, payload["docsets"][0]["documents"])
        self.assertIn("Guide", payload["docsets"][0]["topics"])


if __name__ == "__main__":
    unittest.main()
