"""docs-hub 共用工具。

包含：
- front matter 解析器（PyYAML safe_load）
- Markdown 分块（纯 Python 扫 ATX 标题 + 代码围栏跳过 + 滑窗续切）
- 元信息派生（section / doc_type / is_nav）
- 符号抽取（用于 FTS5 symbols 列加权匹配 API 名/错误码）
- warnings 收集器
- 文件 sha256

设计原则：主路径严格，边界处才降级，降级时必须留 warning。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any


class FrontMatterError(ValueError):
    """front matter 语法不在支持子集内。调用方决定是否降级。"""


class DependencyMissingError(RuntimeError):
    """必需依赖缺失。调用方应直接失败，不做静默降级。"""


_FM_FENCE = "---"


def _normalize_front_matter_value(value: Any) -> Any:
    if isinstance(value, list):
        return [_normalize_front_matter_value(item) for item in value]
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (str, int, float)):
        return str(value)
    return value


def parse_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """解析 front matter；返回 (fm_dict, body)。

    支持子集：
        key: "value" | key: value
        key:
          - "item"
          - item

    子集之外的结构（嵌套映射、内联 JSON、多行字符串、!tag 等）一律抛 FrontMatterError。
    没有 front matter 时返回 ({}, text)。
    """
    if not text.startswith(_FM_FENCE + "\n") and not text.startswith(_FM_FENCE + "\r\n"):
        return {}, text

    lines = text.splitlines(keepends=False)
    if not lines or lines[0].strip() != _FM_FENCE:
        return {}, text

    # 找结束 fence
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == _FM_FENCE:
            end_idx = i
            break
    if end_idx is None:
        raise FrontMatterError("front matter 未闭合")

    fm_lines = lines[1:end_idx]
    body = "\n".join(lines[end_idx + 1 :])
    # 保留原 body 末尾换行语义
    if text.endswith("\n") and not body.endswith("\n"):
        body += "\n"

    try:
        import yaml
    except ImportError as exc:
        raise DependencyMissingError(f"缺少 PyYAML: {exc}") from exc

    raw_meta = "\n".join(fm_lines)
    try:
        parsed = yaml.safe_load(raw_meta) if raw_meta.strip() else {}
    except yaml.YAMLError as exc:  # type: ignore[attr-defined]
        raise FrontMatterError(f"front matter YAML 解析失败: {exc}") from exc

    if parsed is None:
        parsed = {}
    if not isinstance(parsed, dict):
        raise FrontMatterError("front matter 顶层必须是映射")

    result = {str(key): _normalize_front_matter_value(value) for key, value in parsed.items()}
    return result, body


@dataclass
class Chunk:
    heading_path: str  # "H1 > H2 > H3"
    body: str
    idx: int = 0


@dataclass(frozen=True)
class MarkdownAnalysis:
    headings: tuple[tuple[int, str, int, int], ...]
    segments: tuple[tuple[str, str], ...]
    visible_lines: tuple[str, ...]
    primary_heading: str


def _split_by_length(text: str, target: int, max_len: int, overlap: int) -> list[str]:
    """按目标长度切分，优先在换行/句号/空格处断开；块之间保留 overlap 字符重叠。"""
    text = text.strip()
    if len(text) <= max_len:
        return [text] if text else []
    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + target, n)
        if end < n:
            # 在 [start+target*0.6, start+max_len] 区间找最近的换行/句号
            search_end = min(start + max_len, n)
            window = text[start:search_end]
            candidates = [window.rfind("\n\n"), window.rfind("\n"), window.rfind("。"), window.rfind(". ")]
            best = max(candidates)
            if best >= int(target * 0.6):
                end = start + best + 1
        chunks.append(text[start:end].strip())
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return [c for c in chunks if c]


# ATX 标题：行首 0-3 空格 + 1-6 个 #，后跟至少一个空白和标题文本；尾部可选闭合 #。
_ATX_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
# Fenced code block 围栏：至少 3 个 ` 或 ~，允许行首 0-3 空格和可选 info string。
_FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})(.*)$")


def _is_setext_underline(line: str, char: str) -> bool:
    """setext 下划线：行首 0-3 空格 + 全由 `=` 或 `-` 组成、长度 >= 1 的字符串。"""
    if len(line) - len(line.lstrip(" ")) > 3:
        return False
    stripped = line.strip()
    if not stripped:
        return False
    return all(ch == char for ch in stripped)


def _scan_markdown_headings_from_lines(lines: tuple[str, ...]) -> list[tuple[int, str, int, int]]:
    """扫描 Markdown 标题，返回 (level, title, start_line, content_start_line)。"""
    headings: list[tuple[int, str, int, int]] = []
    fence_char: str | None = None
    fence_len = 0
    for i, line in enumerate(lines):
        if fence_char is not None:
            m = _FENCE_RE.match(line)
            if m and m.group(1)[0] == fence_char and len(m.group(1)) >= fence_len and not m.group(2).strip():
                fence_char = None
                fence_len = 0
            continue
        m = _FENCE_RE.match(line)
        if m:
            fence_char = m.group(1)[0]
            fence_len = len(m.group(1))
            continue
        if i > 0:
            prev_raw = lines[i - 1]
            prev = prev_raw.strip()
            # setext 下划线前一行必须是普通段落文本：非空、不是 ATX 标题、不是另一条下划线行。
            if (
                prev
                and not _ATX_HEADING_RE.match(prev_raw)
                and not _is_setext_underline(prev_raw, "=")
                and not _is_setext_underline(prev_raw, "-")
            ):
                if _is_setext_underline(line, "="):
                    headings.append((1, prev, i - 1, i + 1))
                    continue
                if _is_setext_underline(line, "-"):
                    headings.append((2, prev, i - 1, i + 1))
                    continue
        h = _ATX_HEADING_RE.match(line)
        if h:
            level = len(h.group(1))
            title = h.group(2).rstrip(" #").strip()
            headings.append((level, title, i, i + 1))
    return headings


def _scan_markdown_headings(body: str) -> list[tuple[int, str, int, int]]:
    return list(_analyze_markdown(body).headings)


def extract_primary_heading(body: str) -> str:
    """提取首个 Markdown 标题文本，支持 ATX / setext。"""
    return _analyze_markdown(body).primary_heading


def _segment_by_markdown_ast_from_lines(
    lines: tuple[str, ...],
    headings: tuple[tuple[int, str, int, int], ...],
) -> list[tuple[str, str]]:
    """基于已解析标题生成 (heading_path, segment_text) 列表。

    - 识别 `^\\s{0,3}#{1,6}\\s+title` 形式的 ATX 标题。
    - 识别 setext 标题：前一行非空文本、下一行由 `=`（H1）或 `-`（H2）组成。
      这正是 CommonMark 区分 `---` 是 setext 下划线还是 thematic break 的规则。
    - 跟踪 ``` / ~~~ fenced code block，围栏内的 `#` 与 `---` 都不作为标题。
    - 与 commonmark 严格语义相比做了简化：未处理 indented code block (4 空格)、HTML 块内标题、
      block quote 嵌套 setext 等罕见结构；真实 DocsHub 语料里这些模式不影响主路径。
    """
    if not headings:
        whole = "\n".join(lines).strip()
        return [("", whole)] if whole else []

    segments: list[tuple[str, str]] = []
    if headings[0][2] > 0:
        preface = "\n".join(lines[: headings[0][2]]).strip()
        if preface:
            segments.append(("", preface))

    stack: list[tuple[int, str]] = []
    for idx, (level, title, _start_line, content_start_line) in enumerate(headings):
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        next_start_line = headings[idx + 1][2] if idx + 1 < len(headings) else len(lines)
        seg_text = "\n".join(lines[content_start_line:next_start_line]).strip()
        if not seg_text:
            continue
        heading_path = " > ".join(text for _, text in stack if text)
        segments.append((heading_path, seg_text))
    return segments


@lru_cache(maxsize=512)
def _analyze_markdown(body: str) -> MarkdownAnalysis:
    """对同一份 Markdown 做一次解析，供标题提取、分块和导航页判断复用。"""
    lines = tuple(body.splitlines())
    headings = tuple(_scan_markdown_headings_from_lines(lines))
    segments = tuple(_segment_by_markdown_ast_from_lines(lines, headings))
    visible_lines = tuple(line for line in lines if line.strip() and not line.strip().startswith("#"))
    primary_heading = headings[0][1] if headings else ""
    return MarkdownAnalysis(
        headings=headings,
        segments=segments,
        visible_lines=visible_lines,
        primary_heading=primary_heading,
    )


def _segment_by_markdown_ast(body: str) -> list[tuple[str, str]]:
    return list(_analyze_markdown(body).segments)


def split_markdown(
    body: str,
    doc_title: str | None,
    target_chars: int = 1200,
    max_chars: int = 1500,
    overlap_chars: int = 150,
) -> list[Chunk]:
    """按标题树优先切块；超长滑窗续切；无标题整页一块。

    - heading_path 以 "A > B > C" 表示
    - doc_title 作为根标题（若 body 里没有 H1）
    """
    segments = _segment_by_markdown_ast(body)
    if not segments:
        whole = body.strip()
        if not whole:
            return []
        return [Chunk(heading_path=doc_title or "", body=whole, idx=0)]

    chunks: list[Chunk] = []
    for path, seg_text in segments:
        seg_text = seg_text.strip()
        if not seg_text:
            continue
        if len(seg_text) <= max_chars:
            chunks.append(Chunk(heading_path=path, body=seg_text))
        else:
            for sub in _split_by_length(seg_text, target_chars, max_chars, overlap_chars):
                chunks.append(Chunk(heading_path=path, body=sub))

    for i, c in enumerate(chunks):
        c.idx = i
    return chunks


def derive_section(
    fm: dict[str, Any],
    rel_path: Path,
    rules: list[str],
) -> str:
    """按 rules 顺序取 section；rules 元素支持 'menu_path[0]' / 'rel_path[0]'。"""
    for rule in rules:
        if rule == "menu_path[0]":
            mp = fm.get("menu_path")
            if isinstance(mp, list) and mp:
                return str(mp[0])
        elif rule == "rel_path[0]":
            parts = rel_path.parts
            if parts:
                return parts[0]
    return ""


def derive_doc_type(rel_path: Path, rules: list[dict[str, Any]]) -> str:
    rp = str(rel_path).replace("\\", "/")
    for rule in rules:
        if rule.get("match") == "path_contains":
            anys = rule.get("any", [])
            for kw in anys:
                if kw in rp:
                    return rule.get("type", "doc")
    return "doc"


_LINK_ONLY_LINE = re.compile(r"^\s*[-*]\s+\*?\*?\[.*\]\(.*\)\*?\*?\s*$")


def is_nav_page(rel_path: Path, fm: dict[str, Any], body: str, nav_rules: dict[str, Any]) -> bool:
    filenames = nav_rules.get("filenames", [])
    if rel_path.name in filenames:
        return True
    # 正文去掉标题后，全是链接行（或空行）→ 导航页
    lines = list(_analyze_markdown(body).visible_lines)
    if not lines:
        return True
    if all(_LINK_ONLY_LINE.match(l) for l in lines):
        return True
    min_body_chars = int(nav_rules.get("min_body_chars", 0) or 0)
    menu_path = fm.get("menu_path")
    has_menu_path = isinstance(menu_path, list) and bool(menu_path)
    plain_body = "\n".join(lines).strip()
    if min_body_chars > 0 and len(plain_body) < min_body_chars and not has_menu_path:
        return True
    return False


def extract_symbols(rel_path: Path, fm: dict[str, Any]) -> str:
    """组装 symbols 列：路径片段 + 文件名主干 + menu_path。

    目的是让 pdd.mall.info.get / @ohos.security.cert / 错误码等精确符号能被 trigram 命中。
    """
    parts: list[str] = []
    for p in rel_path.with_suffix("").parts:
        parts.append(p)
    stem = rel_path.stem
    parts.append(stem)
    # 拆分常见分隔符，便于匹配 API 名片段
    for sep in ["-", "_", "/", ".", " ", "（", "）", "(", ")"]:
        stem = stem.replace(sep, " ")
    parts.extend(t for t in stem.split() if t)
    mp = fm.get("menu_path")
    if isinstance(mp, list):
        parts.extend(str(x) for x in mp)
    # 去重保持顺序
    seen: set[str] = set()
    ordered: list[str] = []
    for p in parts:
        if p and p not in seen:
            seen.add(p)
            ordered.append(p)
    return " ".join(ordered)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class WarningSink:
    path: Path
    items: list[dict[str, Any]] = field(default_factory=list)

    def add(self, rel_path: str, kind: str, detail: str = "") -> None:
        self.items.append({"rel_path": rel_path, "kind": kind, "detail": detail})

    def flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as f:
            for item in self.items:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")


def read_text_safely(path: Path) -> tuple[str | None, str | None]:
    """读文件，UTF-8 失败时返回 (None, error)；不抛异常。"""
    try:
        return path.read_text(encoding="utf-8"), None
    except UnicodeDecodeError as e:
        return None, f"utf-8 decode error: {e}"
    except OSError as e:
        return None, f"io error: {e}"


def load_docsets(hub_root: Path) -> dict[str, Any]:
    cfg_path = hub_root / "docsets.json"
    with cfg_path.open("r", encoding="utf-8") as f:
        return json.load(f)
