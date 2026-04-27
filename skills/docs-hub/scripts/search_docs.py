"""查询外部 DocsHub 索引。

用法示例：
    <python_cmd> run.py search --hub-root /path/to/hub --list-docsets
    <python_cmd> run.py search --hub-root /path/to/hub 输入法 --top 10
    <python_cmd> run.py search 光标 跟随 --match all --docset harmonyos --top 5
    <python_cmd> run.py search pdd.mall.info.get --docset pinduoduo
    <python_cmd> run.py lookup 输入法 --docset harmonyos
    <python_cmd> run.py status --json
    <python_cmd> run.py refresh 订单 --top 8

排序权重：bm25(chunks, 10.0, 6.0, 1.0) — title:10 symbols:6 body:1
默认过滤 is_nav=1 的导航页；--include-nav 可带出。
JSON 查询输出固定为对象：ok/partial/failed/results/failed_docsets。
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from _bootstrap import ensure_initialized, format_python_command, resolve_query_hub_root  # noqa: E402
from _common import load_docsets  # noqa: E402
from _bootstrap import dependency_cache_problem, init_state_path, load_init_state, runtime_root  # noqa: E402
from build_docset_index import (  # noqa: E402
    DocsetBuildError,
    build_docset,
    compute_build_signature,
    docset_index_path,
    merge_config,
    meta_value,
    resolve_docset_root,
    safe_docset_id,
)


_FTS_SPECIAL = re.compile(r'[()":*+\^]')
_QUERY_SPLIT_RE = re.compile(r"[\s,，、;；/|-]+")


class UnsafeIndexedPathError(ValueError):
    """索引中的 rel_path 无法安全映射回当前 doc_root。"""


def fts_escape(token: str) -> str:
    """把用户关键词转成 FTS5 安全的短语表达式。

    trigram tokenizer 要求 token >= 3 字符；短于 3 字的中文词（如"光标"）
    无法被 FTS5 命中，需要标记为 short_token 由调用方降级处理。
    """
    cleaned = _FTS_SPECIAL.sub(" ", token).strip()
    if not cleaned:
        return ""
    return '"' + cleaned.replace('"', ' ') + '"'


def like_escape(token: str) -> str:
    return token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def resolve_indexed_abs_path(doc_root: Path, rel_path: str) -> Path:
    rel_path = str(rel_path or "")
    if not rel_path:
        raise UnsafeIndexedPathError("rel_path 为空")
    indexed_path = Path(rel_path)
    if indexed_path.is_absolute():
        raise UnsafeIndexedPathError(f"rel_path 不能是绝对路径: {rel_path}")

    doc_root_resolved = doc_root.resolve()
    abs_path = (doc_root_resolved / indexed_path).resolve()
    try:
        abs_path.relative_to(doc_root_resolved)
    except ValueError as exc:
        raise UnsafeIndexedPathError(f"rel_path 越过 doc_root 边界: {rel_path}") from exc
    return abs_path


def _is_short_token(token: str) -> bool:
    """trigram 要求 >= 3 字符；ASCII 字符按字节计，中文按 unicode 字符计。"""
    return len(token.strip()) < 3


def build_match_expr(keywords: list[str], mode: str) -> tuple[str, list[str]]:
    """返回 (fts_match_expr, short_tokens)。

    short_tokens 是无法进入 FTS5 的短词，调用方用 LIKE 补充过滤。
    """
    long_kws = [k for k in keywords if k.strip() and not _is_short_token(k)]
    short_kws = [k for k in keywords if k.strip() and _is_short_token(k)]
    phrases = [fts_escape(k) for k in long_kws]
    phrases = [p for p in phrases if p]
    if not phrases:
        return "", short_kws
    joiner = " AND " if mode == "all" else " OR "
    return joiner.join(phrases), short_kws


def build_short_token_hit_union(
    tokens: list[str],
    *,
    from_clause: str,
    chunk_rowid_expr: str,
    weighted_columns: list[tuple[str, float]],
) -> tuple[str, list[Any]]:
    """把短词展开成按列分发的 UNION ALL 命中流。

    避免 `title OR symbols OR body` 这种组合 LIKE，把 trigram FTS 的可优化路径尽量保留下来。
    """
    if not tokens:
        return "", []

    selects: list[str] = []
    params: list[Any] = []
    for token_ord, token in enumerate(tokens):
        pattern = f"%{like_escape(token)}%"
        for column_expr, weight in weighted_columns:
            selects.append(
                f"SELECT {chunk_rowid_expr} AS chunk_rowid, {token_ord} AS token_ord, {weight} AS weight "
                f"{from_clause} WHERE {column_expr} LIKE ? ESCAPE '\\'"
            )
            params.append(pattern)
    return "\nUNION ALL\n".join(selects), params


def snippet_clean(s: str, max_len: int = 200) -> str:
    s = s.replace("\n", " ").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def _dedupe_terms(keywords: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for keyword in sorted((kw.strip() for kw in keywords if kw.strip()), key=len, reverse=True):
        marker = keyword.casefold()
        if marker in seen:
            continue
        seen.add(marker)
        ordered.append(keyword)
    return ordered


def expand_keywords_for_fallback(keywords: list[str]) -> list[str]:
    expanded: list[str] = []
    seen: set[str] = set()
    for keyword in keywords:
        keyword = keyword.strip()
        if not keyword:
            continue
        for part in _QUERY_SPLIT_RE.split(keyword):
            part = part.strip()
            if not part:
                continue
            marker = part.casefold()
            if marker in seen:
                continue
            seen.add(marker)
            expanded.append(part)
    return expanded


def build_highlighted_snippet(text: str, keywords: list[str], max_len: int = 200) -> str:
    compact = text.replace("\n", " ").strip()
    if not compact:
        return ""

    terms = _dedupe_terms(keywords)
    if not terms:
        return snippet_clean(compact, max_len)

    folded = compact.casefold()
    hit_index: int | None = None
    for term in terms:
        idx = folded.find(term.casefold())
        if idx >= 0 and (hit_index is None or idx < hit_index):
            hit_index = idx

    if hit_index is None:
        return snippet_clean(compact, max_len)

    # 优先保留命中点前后文，避免总是返回 chunk 开头。
    before = max_len // 3
    start = max(0, hit_index - before)
    end = min(len(compact), start + max_len)
    if end - start < max_len:
        start = max(0, end - max_len)

    snippet = compact[start:end].strip()
    if start > 0:
        snippet = "…" + snippet.lstrip()
    if end < len(compact):
        snippet = snippet.rstrip() + "…"

    pattern = re.compile("|".join(re.escape(term) for term in terms), re.IGNORECASE)
    return pattern.sub(lambda match: f"【{match.group(0)}】", snippet)


def text_contains_keyword(text: str, keywords: list[str]) -> bool:
    folded = text.casefold()
    return any(keyword.casefold() in folded for keyword in keywords if keyword.strip())


def choose_snippet_text(row: sqlite3.Row, keywords: list[str]) -> tuple[str, str]:
    body = str(row["body"] or "")
    chunk_title = str(row["chunk_title"] or "")
    title = str(row["title"] or "")
    symbols = str(row["chunk_symbols"] or "")

    if body and text_contains_keyword(body, keywords):
        return body, "body"
    if chunk_title and text_contains_keyword(chunk_title, keywords):
        return chunk_title, "title"
    if title and text_contains_keyword(title, keywords):
        return title, "title"
    if symbols and text_contains_keyword(symbols, keywords):
        return symbols, "symbols"
    return body or chunk_title or title or symbols, "body"


def count_row_keyword_matches(row: sqlite3.Row, keywords: list[str]) -> int:
    fields = [
        str(row["title"] or ""),
        str(row["chunk_title"] or ""),
        str(row["chunk_symbols"] or ""),
        str(row["body"] or ""),
    ]
    count = 0
    for keyword in _dedupe_terms(keywords):
        folded = keyword.casefold()
        if any(folded in field.casefold() for field in fields if field):
            count += 1
    return count


def collect_query_rows(
    conn: sqlite3.Connection,
    keywords: list[str],
    mode: str,
    section: str | None,
    top: int,
    include_nav: bool,
) -> list[dict[str, Any]]:
    match_expr, short_tokens = build_match_expr(keywords, mode)
    if not match_expr and not short_tokens:
        return []

    rows: list[sqlite3.Row] = []
    if match_expr:
        required_short_tokens = short_tokens if mode == "all" else []
        rows.extend(query_fts(conn, match_expr, section, top, include_nav, required_short_tokens))
    if short_tokens and (mode == "or" or not match_expr):
        rows.extend(query_like(conn, short_tokens, mode, section, top, include_nav))
    return [{"row": row, "matched_terms_count": 0} for row in rows]


def collect_fallback_rows(
    conn: sqlite3.Connection,
    keywords: list[str],
    section: str | None,
    top: int,
    include_nav: bool,
) -> tuple[list[dict[str, Any]], list[str]]:
    expanded_keywords = expand_keywords_for_fallback(keywords)
    if len(expanded_keywords) <= 1:
        return [], expanded_keywords

    original_markers = {keyword.strip().casefold() for keyword in keywords if keyword.strip()}
    expanded_markers = {keyword.casefold() for keyword in expanded_keywords}
    if expanded_markers == original_markers:
        return [], expanded_keywords

    merged: dict[str, dict[str, Any]] = {}
    for keyword in expanded_keywords:
        row_items = collect_query_rows(conn, [keyword], "or", section, top, include_nav)
        for item in row_items:
            row = item["row"]
            rel_path = str(row["rel_path"])
            entry = merged.get(rel_path)
            if entry is None:
                merged[rel_path] = {
                    "row": row,
                    "matched_terms": {keyword.casefold()},
                }
                continue
            entry["matched_terms"].add(keyword.casefold())
            best_row = entry["row"]
            if (row["score"], row["rel_path"], row["chunk_idx"]) < (
                best_row["score"],
                best_row["rel_path"],
                best_row["chunk_idx"],
            ):
                entry["row"] = row

    ordered = sorted(
        merged.values(),
        key=lambda item: (
            -len(item["matched_terms"]),
            item["row"]["score"],
            item["row"]["rel_path"],
            item["row"]["chunk_idx"],
        ),
    )
    return [
        {
            "row": item["row"],
            "matched_terms_count": len(item["matched_terms"]),
        }
        for item in ordered[: top * 3]
    ], expanded_keywords


def make_docset_failure(
    docset: dict[str, Any],
    reason: str,
    message: str,
    *,
    index_path: Path | None = None,
    doc_root: Path | None = None,
) -> dict[str, Any]:
    failure = {
        "id": str(docset.get("id") or ""),
        "reason": reason,
        "message": message,
    }
    if docset.get("root"):
        failure["root"] = str(docset["root"])
    if doc_root is not None:
        failure["doc_root"] = doc_root.resolve().as_posix()
    if index_path is not None:
        failure["index_path"] = index_path.resolve().as_posix()
    return failure


def search_payload(
    *,
    hub_root: Path,
    results: list[dict[str, Any]],
    failed_docsets: list[dict[str, Any]],
    searched_docsets: list[str],
) -> dict[str, Any]:
    partial = bool(failed_docsets) and bool(searched_docsets)
    failed = bool(failed_docsets) and not searched_docsets
    return {
        "ok": not failed_docsets,
        "partial": partial,
        "failed": failed,
        "hub_root": hub_root.resolve().as_posix(),
        "searched_docsets": searched_docsets,
        "results": results,
        "failed_docsets": failed_docsets,
    }


def docset_index_status(hub_root: Path, docset: dict[str, Any], defaults: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    raw_docset_id = str(docset.get("id") or "")
    raw_root = str(docset.get("root") or "")
    try:
        docset_id = safe_docset_id(docset)
        doc_root = resolve_docset_root(hub_root, docset)
        db_path = docset_index_path(hub_root, docset)
    except DocsetBuildError as exc:
        item = {
            "id": raw_docset_id,
            "name": str(docset.get("name") or ""),
            "root": raw_root,
            "doc_root": None,
            "root_exists": False,
            "index_path": None,
            "index_exists": False,
            "status": "invalid-config",
            "documents": None,
            "chunks": None,
            "built_at": None,
            "build_signature_match": None,
        }
        return item, make_docset_failure(
            docset,
            "invalid_config",
            str(exc),
        )
    item: dict[str, Any] = {
        "id": docset_id,
        "name": str(docset.get("name") or ""),
        "root": raw_root,
        "doc_root": doc_root.as_posix(),
        "root_exists": doc_root.exists(),
        "index_path": db_path.resolve().as_posix(),
        "index_exists": db_path.exists(),
        "status": "indexed",
        "documents": None,
        "chunks": None,
        "built_at": None,
        "build_signature_match": None,
    }

    if not item["root_exists"]:
        item["status"] = "missing-root"
        return item, make_docset_failure(
            docset,
            "missing_root",
            f"docset root 不存在: {doc_root}",
            index_path=db_path,
            doc_root=doc_root,
        )

    if not db_path.exists():
        item["status"] = "missing-index"
        return item, make_docset_failure(
            docset,
            "missing_index",
            f"索引缺失: {db_path}",
            index_path=db_path,
            doc_root=doc_root,
        )

    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(db_path)
        item["documents"] = int(conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
        item["chunks"] = int(conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
        item["built_at"] = meta_value(conn, "built_at")
        current_signature = meta_value(conn, "build_signature")
        expected_signature = compute_build_signature(merge_config(defaults, docset))
        item["build_signature_match"] = current_signature == expected_signature
    except sqlite3.Error as exc:
        item["status"] = "invalid-index"
        return item, make_docset_failure(
            docset,
            "invalid_index",
            f"索引不可读: {exc}",
            index_path=db_path,
            doc_root=doc_root,
        )
    finally:
        if conn is not None:
            conn.close()

    if not item["build_signature_match"]:
        item["status"] = "stale-index"
        return item, make_docset_failure(
            docset,
            "stale_index",
            "索引构建签名已过期，需要 refresh 或 reinit",
            index_path=db_path,
            doc_root=doc_root,
        )

    return item, None


def collect_docset_status(hub_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cfg = load_docsets(hub_root)
    defaults = cfg.get("defaults", {})
    docsets: list[dict[str, Any]] = []
    failed_docsets: list[dict[str, Any]] = []
    for docset in cfg.get("docsets", []):
        item, failure = docset_index_status(hub_root, docset, defaults)
        docsets.append(item)
        if failure is not None:
            failed_docsets.append(failure)
    return docsets, failed_docsets


def list_docsets(hub_root: Path) -> None:
    docsets, _failed_docsets = collect_docset_status(hub_root)
    for d in docsets:
        extra = ""
        if d.get("documents") is not None and d.get("chunks") is not None:
            extra = f" docs={d['documents']} chunks={d['chunks']}"
        print(f"- {d['id']:<12} {d['name']:<20} root={d['root']}  [{d['status']}]{extra}")


def status_payload(explicit_hub_root: str | None) -> dict[str, Any]:
    root = Path(__file__).parent.parent
    state = load_init_state(root)
    state_hub_root = str(state.get("hub_root") or "") if state else ""
    dependency_problem = dependency_cache_problem(state, root) if state else "尚未初始化"
    setup_errors: list[str] = []
    if not state:
        setup_errors.append("尚未初始化")
    elif dependency_problem:
        setup_errors.append(dependency_problem)

    hub_root: Path | None = None
    docsets: list[dict[str, Any]] = []
    failed_docsets: list[dict[str, Any]] = []
    hub_root_error: str | None = None
    try:
        hub_root = resolve_query_hub_root(explicit_hub_root, state_hub_root)
    except SystemExit as exc:
        hub_root_error = str(exc)
        setup_errors.append(hub_root_error)

    if hub_root is not None:
        try:
            docsets, failed_docsets = collect_docset_status(hub_root)
        except Exception as exc:  # noqa: BLE001
            hub_root_error = f"读取 docsets 状态失败: {exc}"
            setup_errors.append(hub_root_error)

    healthy_docsets = [docset["id"] for docset in docsets if docset.get("status") == "indexed"]
    ok = not setup_errors and not failed_docsets
    partial = not setup_errors and bool(failed_docsets) and bool(healthy_docsets)
    failed = not ok and not partial
    return {
        "ok": ok,
        "partial": partial,
        "failed": failed,
        "initialized": bool(state),
        "state_path": init_state_path(root).resolve().as_posix(),
        "runtime_root": runtime_root(root).resolve().as_posix(),
        "dependency_problem": dependency_problem,
        "hub_root": hub_root.resolve().as_posix() if hub_root is not None else None,
        "hub_root_error": hub_root_error,
        "setup_errors": setup_errors,
        "healthy_docsets": healthy_docsets,
        "docsets": docsets,
        "results": [],
        "failed_docsets": failed_docsets,
    }


def print_status(payload: dict[str, Any]) -> None:
    print("DocsHub status")
    print(f"- initialized: {'yes' if payload['initialized'] else 'no'}")
    print(f"- state: {payload['state_path']}")
    print(f"- runtime: {payload['runtime_root']}")
    print(f"- hub_root: {payload['hub_root'] or '(unresolved)'}")
    dependency_problem = payload.get("dependency_problem")
    print(f"- dependency_cache: {'ok' if not dependency_problem else dependency_problem}")
    if payload.get("hub_root_error"):
        print(f"- hub_root_error: {payload['hub_root_error']}")
    print("- docsets:")
    if not payload.get("docsets"):
        print("  (none)")
    for docset in payload.get("docsets", []):
        extra = ""
        if docset.get("documents") is not None and docset.get("chunks") is not None:
            extra = f" docs={docset['documents']} chunks={docset['chunks']}"
        print(f"  - {docset['id']:<12} [{docset['status']}] root={docset['root']}{extra}")


def print_failed_docsets(failed_docsets: list[dict[str, Any]]) -> None:
    for failure in failed_docsets:
        print(
            f"[error] failed docset={failure['id']} reason={failure['reason']}: {failure['message']}",
            file=sys.stderr,
        )


def ensure_index_ready(
    hub_root: Path,
    docset: dict[str, Any],
    defaults: dict[str, Any],
    rebuild_stale: bool,
) -> tuple[Path | None, dict[str, Any] | None]:
    """返回可用 db 路径和失败信息。rebuild_stale=True 时允许触发 build。"""
    try:
        docset_id = safe_docset_id(docset)
        db = docset_index_path(hub_root, docset)
        doc_root = resolve_docset_root(hub_root, docset)
    except DocsetBuildError as exc:
        return None, make_docset_failure(
            docset,
            "invalid_config",
            str(exc),
        )
    if not doc_root.exists():
        return None, make_docset_failure(
            docset,
            "missing_root",
            f"docset root 不存在: {doc_root}",
            index_path=db,
            doc_root=doc_root,
        )
    if db.exists() and not rebuild_stale:
        _status, failure = docset_index_status(hub_root, docset, defaults)
        if failure is not None:
            return None, failure
        return db, None
    if not db.exists() and not rebuild_stale:
        message = (
            f"索引缺失: {db}; "
            f"可手动运行: {format_python_command(Path(__file__).parent.parent / 'run.py', 'reinit', '--hub-root', hub_root, '--docset', docset_id)}"
        )
        return None, make_docset_failure(
            docset,
            "missing_index",
            message,
            index_path=db,
            doc_root=doc_root,
        )
    # refresh 模式：直接调用 build_docset 函数，免去起子进程 + 重新 import 的启动开销。
    action = "增量刷新" if db.exists() else "先构建"
    print(f"[build] {docset_id} 索引{action}…", file=sys.stderr)
    try:
        stats = build_docset(hub_root, docset, defaults, rebuild=False)
    except DocsetBuildError as exc:
        return None, make_docset_failure(
            docset,
            "build_failed",
            str(exc),
            index_path=db,
            doc_root=doc_root,
        )
    except Exception as exc:  # noqa: BLE001
        return None, make_docset_failure(
            docset,
            "build_failed",
            str(exc),
            index_path=db,
            doc_root=doc_root,
        )
    if not db.exists():
        return None, make_docset_failure(
            docset,
            "build_failed",
            f"构建结束后索引仍不存在: {db}",
            index_path=db,
            doc_root=doc_root,
        )
    print(f"  stats: {stats}", file=sys.stderr)
    return db, None


def query_like(
    conn: sqlite3.Connection,
    short_tokens: list[str],
    mode: str,
    section: str | None,
    top: int,
    include_nav: bool,
) -> list[sqlite3.Row]:
    if not short_tokens:
        return []

    ctes: list[str] = []
    params: list[Any] = []
    doc_filters: list[str] = []
    if not include_nav:
        doc_filters.append("is_nav = 0")
    if section:
        doc_filters.append("section = ?")
        params.append(section)

    from_clause = "FROM chunks c"
    if doc_filters:
        ctes.append(f"eligible_docs AS (SELECT id FROM documents WHERE {' AND '.join(doc_filters)})")
        from_clause = "FROM chunks c JOIN eligible_docs ed ON ed.id = c.doc_id"

    union_sql, union_params = build_short_token_hit_union(
        short_tokens,
        from_clause=from_clause,
        chunk_rowid_expr="c.rowid",
        weighted_columns=[
            ("c.title", 10.0),
            ("c.symbols", 6.0),
            ("c.body", 1.0),
        ],
    )
    params.extend(union_params)
    ctes.append(f"short_hits AS ({union_sql})")

    having_sql = ""
    if mode == "all":
        having_sql = "HAVING COUNT(DISTINCT token_ord) = ?"
        params.append(len(short_tokens))
    ctes.append(
        """
        short_agg AS (
            SELECT chunk_rowid, SUM(weight) AS like_score, COUNT(DISTINCT token_ord) AS matched_short_tokens
            FROM short_hits
            GROUP BY chunk_rowid
            """
        + having_sql
        + """
        )
        """
    )

    sql = f"""
        WITH {', '.join(ctes)}
        SELECT d.rel_path, d.title, d.section, d.doc_type, d.source_url, d.is_nav,
               c.chunk_idx, c.body, c.title AS chunk_title, c.symbols AS chunk_symbols,
               -sa.like_score AS score
        FROM short_agg sa
        JOIN chunks c ON c.rowid = sa.chunk_rowid
        JOIN documents d ON d.id = c.doc_id
        ORDER BY sa.like_score DESC, d.rel_path ASC, c.chunk_idx ASC
        LIMIT ?
    """
    params.append(top * 3)
    return conn.execute(sql, params).fetchall()


def query_fts(
    conn: sqlite3.Connection,
    match_expr: str,
    section: str | None,
    top: int,
    include_nav: bool,
    required_short_tokens: list[str],
) -> list[sqlite3.Row]:
    where = ["chunks MATCH ?"]
    params: list[Any] = [match_expr]
    if not include_nav:
        where.append("d.is_nav = 0")
    if section:
        where.append("d.section = ?")
        params.append(section)

    ctes = [
        f"""
        match_rows AS (
            SELECT c.rowid AS chunk_rowid,
                   d.rel_path, d.title, d.section, d.doc_type, d.source_url, d.is_nav,
                   c.chunk_idx, c.body, c.title AS chunk_title, c.symbols AS chunk_symbols,
                   bm25(chunks, 10.0, 6.0, 1.0) AS bm25_score
            FROM chunks c JOIN documents d ON d.id = c.doc_id
            WHERE {' AND '.join(where)}
        )
        """
    ]
    score_expr = "mr.bm25_score"
    join_short = ""
    if required_short_tokens:
        union_sql, union_params = build_short_token_hit_union(
            required_short_tokens,
            from_clause="FROM match_rows mr",
            chunk_rowid_expr="mr.chunk_rowid",
            weighted_columns=[
                ("mr.chunk_title", 10.0),
                ("mr.chunk_symbols", 6.0),
                ("mr.body", 1.0),
            ],
        )
        ctes.append(f"short_hits AS ({union_sql})")
        ctes.append(
            """
            short_agg AS (
                SELECT chunk_rowid, SUM(weight) AS like_score, COUNT(DISTINCT token_ord) AS matched_short_tokens
                FROM short_hits
                GROUP BY chunk_rowid
                HAVING COUNT(DISTINCT token_ord) = ?
            )
            """
        )
        params.extend(union_params)
        params.append(len(required_short_tokens))
        join_short = "JOIN short_agg sa ON sa.chunk_rowid = mr.chunk_rowid"
        # 短词只提供轻量加权，避免压过 bm25 主排序。
        score_expr = "mr.bm25_score - (sa.like_score / 1000.0)"

    sql = f"""
        WITH {', '.join(ctes)}
        SELECT mr.rel_path, mr.title, mr.section, mr.doc_type, mr.source_url, mr.is_nav,
               mr.chunk_idx, mr.body, mr.chunk_title, mr.chunk_symbols,
               {score_expr} AS score
        FROM match_rows mr
        {join_short}
        ORDER BY score ASC, mr.rel_path ASC, mr.chunk_idx ASC
        LIMIT ?
    """
    params.append(top * 3)
    return conn.execute(sql, params).fetchall()


def search_one(
    db_path: Path,
    keywords: list[str],
    mode: str,
    section: str | None,
    top: int,
    include_nav: bool,
) -> list[dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row_items = collect_query_rows(conn, keywords, mode, section, top, include_nav)
        highlight_keywords = keywords
        ranking_keywords = expand_keywords_for_fallback(keywords) or keywords
        if not row_items:
            row_items, expanded_keywords = collect_fallback_rows(conn, keywords, section, top, include_nav)
            if row_items:
                highlight_keywords = expanded_keywords
                ranking_keywords = expanded_keywords
    finally:
        conn.close()

    for item in row_items:
        item["matched_terms_count"] = max(
            int(item.get("matched_terms_count", 0)),
            count_row_keyword_matches(item["row"], ranking_keywords),
        )

    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    row_items.sort(
        key=lambda item: (
            -int(item.get("matched_terms_count", 0)),
            item["row"]["score"],
            item["row"]["rel_path"],
            item["row"]["chunk_idx"],
        )
    )
    for item in row_items:
        r = item["row"]
        if r["rel_path"] in seen:
            continue
        seen.add(r["rel_path"])
        # heading_path = chunk_title 去掉文档 title 前缀
        chunk_title = r["chunk_title"] or ""
        heading_path = chunk_title
        if chunk_title.startswith((r["title"] or "") + " "):
            heading_path = chunk_title[len((r["title"] or "")) + 1 :]
        snippet_text, snippet_source = choose_snippet_text(r, highlight_keywords)
        out.append({
            "rel_path": r["rel_path"],
            "title": r["title"],
            "heading_path": heading_path,
            "section": r["section"],
            "doc_type": r["doc_type"],
            "source_url": r["source_url"],
            "is_nav": bool(r["is_nav"]),
            "score": round(r["score"], 3),
            "matched_terms_count": int(item.get("matched_terms_count", 0)),
            "snippet_source": snippet_source,
            "snippet": build_highlighted_snippet(snippet_text, highlight_keywords, 200),
        })
        if len(out) >= top:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hub-root", default=None, help="DocsHub 根目录；未传时按 env/祖先目录自动发现")
    ap.add_argument("--docset", default=None, help="限定 docset id；不指定则跨 docset 查询")
    ap.add_argument("--section", default=None, help="限定 section（如 指南/API参考/FAQ）")
    ap.add_argument("--match", default="or", choices=["or", "all"], help="多关键词匹配策略")
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--include-nav", action="store_true")
    ap.add_argument("--rebuild-stale", action="store_true", help="查询前先做一次增量刷新（refresh 模式）")
    ap.add_argument("--list-docsets", action="store_true")
    ap.add_argument("--status", action="store_true", help="检查初始化、hub root 与索引状态，不触发重建")
    ap.add_argument("--json", action="store_true", help="输出 JSON 而非纯文本")
    ap.add_argument("keywords", nargs="*")
    args = ap.parse_args()

    if args.status:
        payload = status_payload(args.hub_root)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print_status(payload)
        return 0 if payload["ok"] else 1

    state = ensure_initialized("查询文档")
    hub_root = resolve_query_hub_root(args.hub_root, str(state.get("hub_root") or ""))

    if args.list_docsets:
        if args.json:
            payload = status_payload(str(hub_root))
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if payload["ok"] else 1
        list_docsets(hub_root)
        return 0

    if not args.keywords:
        ap.error("需要至少一个关键词")

    if not expand_keywords_for_fallback(args.keywords):
        ap.error("关键词清洗后为空")

    cfg = load_docsets(hub_root)
    defaults = cfg.get("defaults", {})
    all_docsets = cfg.get("docsets", [])
    targets = all_docsets if not args.docset else [d for d in all_docsets if str(d.get("id") or "") == args.docset]
    if not targets:
        if args.json:
            failed_docsets = [
                {
                    "id": str(args.docset or ""),
                    "reason": "unknown_docset",
                    "message": f"未找到 docset: {args.docset}",
                }
            ]
            print(
                json.dumps(
                    search_payload(
                        hub_root=hub_root,
                        results=[],
                        failed_docsets=failed_docsets,
                        searched_docsets=[],
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 1
        raise SystemExit(f"未找到 docset: {args.docset}")

    all_results: list[dict[str, Any]] = []
    failed_docsets: list[dict[str, Any]] = []
    searched_docsets: list[str] = []
    for ds in targets:
        db, failure = ensure_index_ready(hub_root, ds, defaults, args.rebuild_stale)
        if failure is not None:
            failed_docsets.append(failure)
        if db is None:
            continue
        try:
            rows = search_one(db, args.keywords, args.match, args.section, args.top, args.include_nav)
        except sqlite3.Error as e:
            failed_docsets.append(
                make_docset_failure(
                    ds,
                    "query_failed",
                    str(e),
                    index_path=db,
                    doc_root=hub_root / str(ds.get("root") or ""),
                )
            )
            continue
        searched_docsets.append(str(ds["id"]))
        doc_root = resolve_docset_root(hub_root, ds)
        for r in rows:
            try:
                abs_path = resolve_indexed_abs_path(doc_root, str(r["rel_path"]))
            except UnsafeIndexedPathError as exc:
                failed_docsets.append(
                    make_docset_failure(
                        ds,
                        "invalid_index_entry",
                        str(exc),
                        index_path=db,
                        doc_root=doc_root,
                    )
                )
                continue
            r["docset"] = ds["id"]
            r["doc_root"] = doc_root.as_posix()
            r["abs_path"] = abs_path.as_posix()
            all_results.append(r)

    # 跨 docset 合并后按 score 再排，取 top
    all_results.sort(key=lambda x: (-int(x.get("matched_terms_count", 0)), x["score"], x["rel_path"]))
    all_results = all_results[: args.top]

    if args.json:
        print(
            json.dumps(
                search_payload(
                    hub_root=hub_root,
                    results=all_results,
                    failed_docsets=failed_docsets,
                    searched_docsets=searched_docsets,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if not failed_docsets else 1

    if failed_docsets:
        print_failed_docsets(failed_docsets)
    if not all_results:
        if not failed_docsets:
            print("(无结果)")
        return 0 if not failed_docsets else 1

    for i, r in enumerate(all_results, 1):
        print(f"[{i}] ({r['docset']}) {r['abs_path']}")
        if r.get("heading_path"):
            print(f"    # {r['heading_path']}")
        if r.get("source_url"):
            print(f"    url: {r['source_url']}")
        meta_bits = []
        if r.get("section"):
            meta_bits.append(f"section={r['section']}")
        if r.get("doc_type"):
            meta_bits.append(f"type={r['doc_type']}")
        meta_bits.append(f"score={r['score']}")
        print(f"    meta: {' '.join(meta_bits)}")
        print(f"    » {r['snippet']}")
        print()
    return 0 if not failed_docsets else 1


if __name__ == "__main__":
    raise SystemExit(main())
