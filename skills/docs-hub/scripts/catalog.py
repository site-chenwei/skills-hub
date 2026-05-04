"""DocsHub agent-facing catalog.

The catalog is intentionally small: it tells an agent what can be queried, not
what the documents say. Source documents remain the authority and should still
be opened through lookup results.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CATALOG_FILENAME = "catalog.json"
DOCSET_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
DOCS_DIR_NAME = "docs"
MAX_TOPICS = 8
MAX_RECOMMENDED_QUERIES = 6
MAX_SOURCE_SETS = 6


def catalog_path(hub_root: Path) -> Path:
    return hub_root.resolve() / "index" / CATALOG_FILENAME


def load_docsets_config(hub_root: Path) -> dict[str, Any]:
    cfg_path = hub_root / "docsets.json"
    with cfg_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_docsets_config(hub_root: Path, cfg: dict[str, Any]) -> None:
    write_json_atomic(hub_root / "docsets.json", cfg)


def safe_docset_id_value(value: str) -> str:
    docset_id = value.strip()
    if not DOCSET_ID_RE.fullmatch(docset_id):
        raise ValueError(f"docset id 不安全: {value!r}")
    return docset_id


def slugify_docset_id(name: str, used: set[str]) -> str:
    slug = name.strip().lower()
    slug = re.sub(r"[^a-z0-9_.-]+", "-", slug)
    slug = slug.strip("-._")
    if not slug or not re.match(r"^[a-z0-9]", slug):
        digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
        slug = f"docset-{digest}"
    if slug not in used:
        used.add(slug)
        return slug

    base = slug
    index = 2
    while f"{base}-{index}" in used:
        index += 1
    slug = f"{base}-{index}"
    used.add(slug)
    return slug


def resolve_relative_to_hub(hub_root: Path, raw_path: str) -> Path:
    if not raw_path.strip():
        raise ValueError("路径为空")
    rel = Path(raw_path)
    if rel.is_absolute():
        raise ValueError(f"路径必须位于 hub root 内且使用相对路径: {raw_path}")
    hub_resolved = hub_root.resolve()
    resolved = (hub_resolved / rel).resolve()
    try:
        resolved.relative_to(hub_resolved)
    except ValueError as exc:
        raise ValueError(f"路径越过 hub root 边界: {raw_path}") from exc
    return resolved


def resolve_docset_root(hub_root: Path, docset: dict[str, Any]) -> Path:
    return resolve_relative_to_hub(hub_root, str(docset.get("root") or ""))


def resolve_catalog_file(hub_root: Path, docset: dict[str, Any], doc_root: Path) -> tuple[str, str]:
    candidates: list[tuple[str, Path]] = []
    raw_catalog_file = str(docset.get("catalog_file") or "").strip()
    if raw_catalog_file:
        try:
            explicit_path = resolve_relative_to_hub(hub_root, raw_catalog_file)
        except ValueError as exc:
            return "", str(exc)
        candidates.append((raw_catalog_file, explicit_path))

    for filename in ("DOCSET.md", "CATALOG.md"):
        path = doc_root / filename
        try:
            path.relative_to(hub_root.resolve())
        except ValueError:
            continue
        candidates.append((path.relative_to(hub_root.resolve()).as_posix(), path))

    for rel_path, path in candidates:
        if path.exists() and path.is_file():
            return rel_path, ""
    return "", ""


def index_path_for_docset(hub_root: Path, docset_id: str) -> Path:
    return hub_root.resolve() / "index" / f"{docset_id}.sqlite"


def normalize_string_list(value: Any, *, limit: int) -> list[str]:
    if isinstance(value, str):
        raw_items = [value]
    elif isinstance(value, list):
        raw_items = [str(item) for item in value if isinstance(item, (str, int, float))]
    else:
        raw_items = []

    items: list[str] = []
    seen: set[str] = set()
    for raw_item in raw_items:
        item = raw_item.strip()
        marker = item.casefold()
        if not item or marker in seen:
            continue
        seen.add(marker)
        items.append(item)
        if len(items) >= limit:
            break
    return items


def normalize_source_sets(value: Any) -> list[dict[str, str]]:
    raw_items = value if isinstance(value, list) else []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw_items:
        if isinstance(item, str):
            source_id = item.strip()
            description = ""
        elif isinstance(item, dict):
            source_id = str(item.get("id") or item.get("name") or item.get("type") or "").strip()
            description = str(item.get("description") or "").strip()
        else:
            continue
        if not source_id:
            continue
        marker = source_id.casefold()
        if marker in seen:
            continue
        seen.add(marker)
        entry = {"id": source_id}
        if description:
            entry["description"] = description
        out.append(entry)
        if len(out) >= MAX_SOURCE_SETS:
            break
    return out


def infer_source_sets_from_rows(rows: list[sqlite3.Row]) -> list[dict[str, str]]:
    prefixes: Counter[str] = Counter()
    for row in rows:
        rel_path = str(row["rel_path"] or "")
        first_part = rel_path.split("/", 1)[0].strip()
        if first_part and first_part != rel_path:
            prefixes[first_part] += 1
    out = []
    for source_id, _count in prefixes.most_common(MAX_SOURCE_SETS):
        out.append({"id": source_id})
    return out


def is_catalog_topic_candidate(value: str) -> bool:
    topic = value.strip()
    if not topic:
        return False
    lowered = topic.casefold()
    if lowered.endswith((".md", ".markdown", ".mdx")):
        return False
    if lowered in {"readme", "index", "catalog", "docset"}:
        return False
    return True


def load_document_rows(db_path: Path) -> tuple[list[sqlite3.Row], int, str, str]:
    if not db_path.exists():
        return [], 0, "", "missing-index"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT rel_path, title, section, doc_type, source_url, is_nav
            FROM documents
            ORDER BY rel_path ASC
            """
        ).fetchall()
        chunks = int(conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
        built_at_row = conn.execute("SELECT value FROM meta WHERE key='built_at'").fetchone()
        built_at = str(built_at_row[0]) if built_at_row else ""
        return rows, chunks, built_at, "indexed"
    except sqlite3.Error:
        return [], 0, "", "invalid-index"
    finally:
        conn.close()


def infer_topics(docset: dict[str, Any], rows: list[sqlite3.Row]) -> list[str]:
    explicit = normalize_string_list(docset.get("topics"), limit=MAX_TOPICS)
    if explicit:
        return explicit

    sections: Counter[str] = Counter()
    first_dirs: Counter[str] = Counter()
    doc_types: Counter[str] = Counter()
    for row in rows:
        section = str(row["section"] or "").strip()
        if is_catalog_topic_candidate(section):
            sections[section] += 1
        doc_type = str(row["doc_type"] or "").strip()
        if doc_type and doc_type != "doc":
            doc_types[doc_type] += 1
        rel_path = str(row["rel_path"] or "")
        first_part = rel_path.split("/", 1)[0].strip()
        if first_part and first_part != rel_path and is_catalog_topic_candidate(first_part):
            first_dirs[first_part] += 1

    topics: list[str] = []
    seen: set[str] = set()
    for counter in (sections, first_dirs, doc_types):
        for value, _count in counter.most_common(MAX_TOPICS):
            marker = value.casefold()
            if marker in seen:
                continue
            seen.add(marker)
            topics.append(value)
            if len(topics) >= MAX_TOPICS:
                return topics
    return topics


def infer_recommended_queries(docset: dict[str, Any], topics: list[str]) -> list[str]:
    explicit = normalize_string_list(docset.get("recommended_queries"), limit=MAX_RECOMMENDED_QUERIES)
    if explicit:
        return explicit

    name = str(docset.get("name") or docset.get("id") or "").strip()
    queries: list[str] = []
    for topic in topics:
        if name and topic.casefold() not in name.casefold():
            query = f"{name} {topic}"
        else:
            query = topic
        if query and query not in queries:
            queries.append(query)
        if len(queries) >= MAX_RECOMMENDED_QUERIES:
            break
    return queries


def docset_catalog_entry(hub_root: Path, docset: dict[str, Any]) -> dict[str, Any]:
    raw_docset_id = str(docset.get("id") or "")
    entry: dict[str, Any] = {
        "id": raw_docset_id,
        "name": str(docset.get("name") or raw_docset_id),
        "root": str(docset.get("root") or ""),
        "description": str(docset.get("description") or "").strip(),
        "topics": [],
        "recommended_queries": [],
        "source_sets": [],
        "catalog_file": "",
        "documents": 0,
        "chunks": 0,
        "status": "invalid-config",
    }
    try:
        docset_id = safe_docset_id_value(raw_docset_id)
        doc_root = resolve_docset_root(hub_root, docset)
    except ValueError as exc:
        entry["error"] = str(exc)
        return entry

    entry["id"] = docset_id
    entry["doc_root"] = doc_root.as_posix()
    if not doc_root.exists():
        entry["status"] = "missing-root"
        return entry

    rows, chunks, built_at, status = load_document_rows(index_path_for_docset(hub_root, docset_id))
    topics = infer_topics(docset, rows)
    source_sets = normalize_source_sets(docset.get("source_sets")) or infer_source_sets_from_rows(rows)
    catalog_file, catalog_file_error = resolve_catalog_file(hub_root, docset, doc_root)

    entry.update(
        {
            "topics": topics,
            "recommended_queries": infer_recommended_queries(docset, topics),
            "source_sets": source_sets,
            "catalog_file": catalog_file,
            "documents": len(rows),
            "chunks": chunks,
            "built_at": built_at,
            "status": status,
        }
    )
    if catalog_file_error:
        entry["catalog_file_error"] = catalog_file_error
    if bool(docset.get("auto_discovered")):
        entry["auto_discovered"] = True
    return entry


def build_catalog_payload(hub_root: Path) -> dict[str, Any]:
    cfg = load_docsets_config(hub_root)
    docsets = [docset_catalog_entry(hub_root, docset) for docset in cfg.get("docsets", [])]
    return {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "hub_root": hub_root.resolve().as_posix(),
        "catalog_path": catalog_path(hub_root).as_posix(),
        "docsets": docsets,
    }


def update_catalog(hub_root: Path) -> dict[str, Any]:
    payload = build_catalog_payload(hub_root)
    write_json_atomic(catalog_path(hub_root), payload)
    return payload


def load_or_build_catalog(hub_root: Path, *, write_if_missing: bool = False) -> dict[str, Any]:
    path = catalog_path(hub_root)
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
            if isinstance(payload, dict) and isinstance(payload.get("docsets"), list):
                return payload
        except (OSError, json.JSONDecodeError):
            pass
    if write_if_missing:
        return update_catalog(hub_root)
    return build_catalog_payload(hub_root)


def catalog_hints(
    hub_root: Path,
    docset_ids: list[str] | None = None,
    *,
    max_docsets: int = 3,
    max_topics: int = 5,
    max_queries: int = 4,
) -> list[dict[str, Any]]:
    wanted = {docset_id for docset_id in (docset_ids or []) if docset_id}
    payload = load_or_build_catalog(hub_root)
    hints: list[dict[str, Any]] = []
    for docset in payload.get("docsets", []):
        docset_id = str(docset.get("id") or "")
        if wanted and docset_id not in wanted:
            continue
        topics = normalize_string_list(docset.get("topics"), limit=max_topics)
        queries = normalize_string_list(docset.get("recommended_queries"), limit=max_queries)
        if not topics and not queries:
            continue
        hints.append(
            {
                "id": docset_id,
                "name": str(docset.get("name") or docset_id),
                "description": str(docset.get("description") or ""),
                "topics": topics,
                "recommended_queries": queries,
            }
        )
        if len(hints) >= max_docsets:
            break
    return hints


def print_catalog(payload: dict[str, Any]) -> None:
    print("DocsHub catalog")
    print(f"- hub_root: {payload.get('hub_root')}")
    print(f"- catalog: {payload.get('catalog_path')}")
    for docset in payload.get("docsets", []):
        status = str(docset.get("status") or "unknown")
        doc_count = int(docset.get("documents") or 0)
        chunk_count = int(docset.get("chunks") or 0)
        print(f"\n{docset.get('id')} - {docset.get('name')} [{status}] docs={doc_count} chunks={chunk_count}")
        description = str(docset.get("description") or "").strip()
        if description:
            print(f"适合回答：{description}")
        topics = normalize_string_list(docset.get("topics"), limit=MAX_TOPICS)
        if topics:
            print(f"主题：{', '.join(topics)}")
        source_sets = normalize_source_sets(docset.get("source_sets"))
        if source_sets:
            print(f"来源：{', '.join(item['id'] for item in source_sets)}")
        queries = normalize_string_list(docset.get("recommended_queries"), limit=MAX_RECOMMENDED_QUERIES)
        if queries:
            print(f"推荐查询：{', '.join(queries)}")
        catalog_file = str(docset.get("catalog_file") or "").strip()
        if catalog_file:
            print(f"目录文件：{catalog_file}")


def discover_missing_docsets(hub_root: Path) -> list[dict[str, Any]]:
    cfg = load_docsets_config(hub_root)
    docs_dir = hub_root / DOCS_DIR_NAME
    if not docs_dir.exists() or not docs_dir.is_dir():
        return []

    docsets = cfg.setdefault("docsets", [])
    registered_roots = {str(docset.get("root") or "").strip().rstrip("/") for docset in docsets}
    used_ids = {str(docset.get("id") or "").strip() for docset in docsets if str(docset.get("id") or "").strip()}
    added: list[dict[str, Any]] = []

    for child in sorted(docs_dir.iterdir(), key=lambda path: path.name.casefold()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        rel_root = child.relative_to(hub_root).as_posix()
        if rel_root in registered_roots:
            continue
        docset_id = slugify_docset_id(child.name, used_ids)
        docset = {
            "id": docset_id,
            "name": child.name,
            "root": rel_root,
            "auto_discovered": True,
        }
        docsets.append(docset)
        registered_roots.add(rel_root)
        added.append(docset)

    if added:
        write_docsets_config(hub_root, cfg)
    return added
