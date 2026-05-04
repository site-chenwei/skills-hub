# DocsHub Layout

The bundled scripts expect an external DocsHub root with this shape:

```text
<hub-root>/
├── docsets.json
├── docs/
│   └── <docset folders>
└── index/                 # created on demand
```

## `docsets.json`

Minimal shape:

```json
{
  "version": 1,
  "defaults": {
    "include": ["*.md", "**/*.md"],
    "exclude": ["**/*:Zone.Identifier", "**/README.md", "**/catalog.md"],
    "section_from": ["menu_path[0]", "rel_path[0]"],
    "doc_type_rules": [],
    "nav_rules": {
      "filenames": ["README.md", "catalog.md", "index.md"],
      "min_body_chars": 300
    },
    "chunk": {
      "target_chars": 1200,
      "max_chars": 1500,
      "overlap_chars": 150
    }
  },
  "docsets": [
    {
      "id": "example",
      "name": "Example Docs",
      "root": "docs/example",
      "description": "短句说明这个 docset 适合回答的问题类型",
      "topics": ["API", "FAQ", "best practices"],
      "recommended_queries": ["Example API auth", "Example FAQ"],
      "source_sets": [
        {"id": "official-docs", "description": "官方原文快照"},
        {"id": "engineering-notes", "description": "工程摘要或本地笔记"}
      ],
      "catalog_file": "docs/example/DOCSET.md"
    }
  ]
}
```

Catalog fields are optional and intentionally short. They are for agent discovery
only; the source Markdown files remain the evidence used in final answers.

## Commands

`<python_cmd>` means the available Python launcher in the current environment. On Windows/PowerShell prefer `py -3`, then `python`, then `python3`; on Unix prefer `python3`, then `python`.

Read-only search:

```bash
<python_cmd> <skill_root>/run.py search --hub-root <hub_root> 输入法 --top 8
<python_cmd> <skill_root>/run.py search --hub-root <hub_root> 光标 跟随 --match all --docset harmonyos --top 5
<python_cmd> <skill_root>/run.py catalog --hub-root <hub_root> --json
```

Refresh only on explicit user request:

```bash
<python_cmd> <skill_root>/run.py refresh --hub-root <hub_root> 输入法 --top 8
<python_cmd> <skill_root>/run.py reinit --hub-root <hub_root> --docset harmonyos
```

## Notes

- Search results include `abs_path`, which is the path to open for verification.
- The skill keeps its runtime `.deps/` and init state in a user-local cache directory outside the synced skill bundle; do not write initialization state into the external hub.
- By default that runtime directory follows the shared `skills-hub/<skill-name>` convention; `SKILLS_HUB_RUNTIME_DIR` overrides the shared root.
- Running `init` refreshes that local runtime cache and rebuilds indexes that are missing or stale for the current build logic.
- `init`, `refresh`, and `reinit` refresh `index/catalog.json`, a compact agent-facing discovery file.
- Index-building commands auto-discover direct child directories under `docs/` that are not already present in `docsets.json`. They append minimal entries with `id`, `name`, `root`, and `auto_discovered`.
- Dependency installation uses `uv pip install --python <current-python>` when `uv` is available, otherwise `<current-python> -m pip`, so PATH-level `pip3` from another Python is not reused accidentally.
- A repeated `init` reuses the local runtime dependency cache only when the requirements hash, Python version/interpreter, site-packages directory, and required distributions still match; pass `--refresh-deps` only when you need to force a reinstall.
- `search`, `refresh`, and `reinit` validate the same init state before activating cached dependencies. If the Python version or dependency cache no longer matches, rerun `$docs-hub init`.
- Large docsets may still override `chunk` at the docset level to trade index size/build time against retrieval granularity.
- Incremental build now prefers a fast stat-based skip (`mtime_ns + ctime_ns + size`) and falls back to sha256 when metadata is not conclusive.
