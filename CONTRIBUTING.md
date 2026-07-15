# Contributing to Lemory

Thanks for helping! The codebase is small on purpose — one SQLite file, one
provider seam, no services — please keep it that way.

## Dev setup

```bash
uv venv && uv pip install -e ".[dev]"
pytest            # 344 tests, fully offline, no API key needed
```

The test suite must stay offline: use the `FakeGemini` embedder from
`tests/conftest.py` and never require network in unit tests.

## Where things live

| Area | Path |
|---|---|
| Config / provider selection | `src/lemory/config.py`, `src/lemory/providers/` |
| Ingestion (parse, chunk, sync, watcher) | `src/lemory/ingestion/` |
| Storage (SQLite + FTS5 + vectors + graph) | `src/lemory/storage/` |
| Retrieval (fusion, graph, temporal, typo, compact) | `src/lemory/retrieval/` |
| Surfaces (CLI, HTTP, web UI, MCP) | `src/lemory/interfaces/` |
| Obsidian plugin | `obsidian-plugin/` |
| Benchmarks (all reproducible) | `benchmarks/` |

## Rules of the road

1. **Benchmarks are honest.** Baselines stay pure (no Lemory-only boosts in
   `vector`/`bm25` modes); gold labels must be verifiable by code; any corpus
   change reruns the affected benchmarks and updates `BENCHMARKS.md` via
   `benchmarks/report.py`.
2. **Retrieval stays LLM-free by default.** Features that need LLM calls at
   search time go behind an off-by-default config flag.
3. **Every bug fix lands with a test** that fails without the fix.
4. 한국어로 이슈와 PR을 올리셔도 됩니다.

## Releasing (maintainers)

- Bump `pyproject.toml` version, tag, `python -m build`, `twine upload`.
