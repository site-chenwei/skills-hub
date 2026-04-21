---
name: docs-hub
description: Query and maintain an external local DocsHub markdown knowledge base. This is the default and primary retrieval path whenever you need to查本地文档、DocsHub、共享知识库、API/指南/FAQ/最佳实践/错误码/SDK 文档，or whenever you need documentation, API facts, guides, FAQ entries, best practices, error codes, SDK references, or other factual/reference material before answering. You must query the local DocsHub first and must not fall back to memory, web search, or other lookup methods unless the local hub is missing, cannot be resolved, returns no useful result after reasonable query refinement, or the user explicitly requires the latest online state. Also use when the user explicitly invokes $docs-hub for init, refresh, or reinit.
---

# Doc Hub

Use this skill as the default retrieval gateway for documentation and factual/reference lookups backed by an external DocsHub folder. The skill bundle provides the scripts; the actual documentation lives in a separate hub directory.

## Priority Rule

- For documentation or factual/reference lookup tasks, `$docs-hub` is the required first retrieval step.
- Do not answer from memory, generic repo search, or online search before attempting `$docs-hub`, unless one of these exceptions applies:
  - the local DocsHub root is missing, unresolved, or unusable
  - the local DocsHub returns no useful match after reasonable query refinement
  - the user explicitly asks for the latest online state or another non-local source

## Invocation Modes

- `$docs-hub init [hub-root]`
  If `hub-root` is explicitly provided, validate only that directory and fail if it is not a standard DocsHub root. Otherwise resolve from environment/current workspace. Then run the bundled init script, record that hub as the default working directory, cleanly refresh bundled dependencies, and auto-build missing or stale indexes.
- `$docs-hub <query>`
  Search the DocsHub and answer from the matched local files.
- `$docs-hub refresh <query>`
  Refresh the relevant local index first, then search.
- `$docs-hub reinit [hub-root]`
  Rebuild the target DocsHub indexes from scratch. Use this only when the user explicitly asks for a full rebuild or the index is broken.

## When to use

- The user wants to search a local markdown documentation hub instead of browsing online.
- The target is a DocsHub-style repository with `docsets.json`, `docs/`, optional `index/`, and markdown content.
- The user wants to refresh or rebuild a local docs index.
- The user explicitly invokes `$docs-hub`.
- You need to look up documentation, API facts, guides, FAQ entries, best practices, error codes, SDK references, or other factual material before answering, even if the user did not explicitly say “查本地文档”.
- The query might plausibly be answered from the local DocsHub, even if other tools or your own memory could also answer it.
- Default policy: if the local hub could reasonably contain the answer, search the local hub first and only then consider any other lookup route.

## Workflow

1. Resolve the DocsHub root in this order:
   - explicit `--hub-root`
   - the DocsHub root recorded during the last successful init
   - `CODEX_DOC_HUB`
   - current workspace / ancestor directories containing `docsets.json`, `doc-search/docsets.json`, or `DocsHub/docsets.json`
2. If the user explicitly asked for `init`, first resolve the DocsHub root from:
   - when a path is supplied after `init`, validate only that path
   - otherwise use `CODEX_DOC_HUB`
   - otherwise use current workspace / ancestor directories
   If none work, stop and report an error.
3. For `init`, run:
   - `python3 <skill_root>/scripts/local_doc_init.py --skill-root <skill_root> --hub-root <hub_root>`
   Then stop after reporting success/failure.
4. Otherwise, for every documentation or factual/reference query, run the bundled search script first:
   - `python3 <skill_root>/scripts/search_docs.py --hub-root <hub_root> <keywords> --top 8`
5. Search first, then open the top 1-3 matched files via the returned `abs_path` and answer from evidence.
6. Only if the local hub has no useful match after reasonable query refinement, or the user explicitly requires online-latest information, then fall back to other lookup methods.
7. If the user explicitly asks for `refresh`, use `--rebuild-stale`.
8. If the user explicitly asks for `reinit`, use `build_docset_index.py --rebuild`.

## Initialization

- This skill needs a one-time init after installation.
- Prefer performing init yourself when the user uses `$docs-hub init ...`.
- During init, if the DocsHub root resolves successfully, let the script detect missing or stale indexes and auto-build them.
- Init reuses the bundled local dependency cache when the requirements hash and Python version still match; use `--refresh-deps` only when you explicitly need a clean reinstall.
- Query and rebuild prefer the DocsHub root recorded during the last successful init.
- Explicit `init <hub-root>` is strict: it validates only that directory and does not fall back to env or workspace discovery.
- If any bundled script says the skill is not initialized during a normal search, tell the user to run `$docs-hub init` in Codex instead of showing raw shell commands first.
- Do not auto-install dependencies during search/build.

## Search Strategy

- Start with the user’s exact phrase.
- If results are noisy, split into 2-4 strong keywords and use `--match all`.
- Use `--docset <id>` when the documentation family is obvious.
- Use `--section` when the query is clearly in `FAQ` / `指南` / `参考` / `最佳实践`.
- For short tokens such as `UI`, `IME`, `光标`, the search script already falls back to LIKE across `title/symbols/body`; you do not need a separate grep unless the index is missing.

## Refresh / Reinit

- Only run `refresh` or `reinit` when the user explicitly uses those intents.
- Prefer query-scoped `refresh` first:
  - `python3 <skill_root>/scripts/search_docs.py --hub-root <hub_root> --rebuild-stale <keywords> --top 8`
- Use `reinit` only when the index is missing, corrupted, or the user explicitly asks for a docset-wide rebuild:
  - `python3 <skill_root>/scripts/build_docset_index.py --hub-root <hub_root> --docset <id> --rebuild`

## Answering rules

- Prefer local evidence over memory, and do not skip the local DocsHub lookup when it could plausibly answer the question.
- Return the resolved file path and `source_url` when available.
- If the local snapshot has no answer, or the user explicitly asks for the latest online state, say the local hub may be stale and then consult the official source or another appropriate lookup method.

## References

- If you need the expected hub layout or CLI semantics, read `references/hub-layout.md`.
