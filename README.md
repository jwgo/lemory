# Lemory

**A high-performance personal knowledge base backend for your Obsidian vault.**

Point Lemory at your vault and it becomes a live, queryable second brain: it watches
your notes, indexes them incrementally, builds a knowledge graph from your links —
and answers questions with citations. One API key, zero services, one SQLite file.

Inspired by [cognee](https://github.com/topoteretes/cognee)'s easy setup and
ECL pipeline, [mem0](https://github.com/mem0ai/mem0)'s incremental memory
updates, supermemory's fast hybrid retrieval, and the "your notes are an
interconnected wiki" idea — Lemory treats your `[[wikilinks]]` as a free
knowledge graph instead of paying an LLM to build one.

## Quickstart

```bash
pip install -e .
export GEMINI_API_KEY=...        # free-tier key from https://aistudio.google.com works

lemory index --vault ~/Obsidian/MyVault    # first index (incremental afterwards)
lemory ask "what did I decide about the pricing model?"
```

Or three lines of Python (cognee-style):

```python
import lemory

lemory.configure(vault="~/Obsidian/MyVault")
lemory.index()                                   # incremental; safe to re-run
print(lemory.ask("what did I decide about pricing?").text)   # cited answer
```

Run it as the always-on backend for your vault:

```bash
lemory serve --vault ~/Obsidian/MyVault    # HTTP API + live file watcher on :8377
```

```
GET  /search?q=...&k=8      hybrid search
POST /ask                   {"question": "..."}  → grounded, cited answer
GET  /status                index stats
POST /index                 force reindex
```

`lemory watch` does the same without HTTP: edit notes in Obsidian, Lemory keeps up.

### Try it in 60 seconds (no vault needed)

A 54-note interlinked demo vault ships in the repo:

```bash
export GEMINI_API_KEY=...
lemory index --vault benchmarks/data/multihop/vault
lemory ask "What is the hobby of the person who leads Project Atlas?" --vault benchmarks/data/multihop/vault
```

The answer requires two notes (the project note names the lead, the person note
holds the hobby) — that hop is what Lemory's graph retrieval does and naive RAG misses.

### Use it from Claude (MCP)

```bash
pip install -e ".[mcp]"
```

```json
{"mcpServers": {"lemory": {"command": "lemory", "args": ["mcp", "--vault", "~/Obsidian/MyVault"]}}}
```

Claude Desktop / Claude Code then get `search_notes`, `ask_notes`, and
`vault_status` tools over your live vault.

## How it works

```
Obsidian vault ──▶ watcher ──▶ incremental sync (content-hash diff)
                                 │
                                 ├─ heading-aware chunking (+ title breadcrumbs)
                                 ├─ Gemini embeddings (batched, cached in SQLite)
                                 └─ note graph: [[wikilinks]] + unlinked title
                                    mentions (+ optional LLM entity extraction)

query ─▶ (optional LLM query expansion) ─▶ vector top-k ─┐
                                       └─▶ BM25 (FTS5) ──┼─▶ adaptive RRF fusion
                                                         │      + title boost
         1-hop graph expansion (multi-hop recall)  ◀─────┘
         (optional LLM rerank) ─▶ per-note diversity cap ─▶ hits / ask()
```

Design choices that matter:

- **Zero services.** SQLite (FTS5 for BM25, tables for chunks/links/cache) plus an
  in-memory numpy matrix for exact cosine search. At personal-vault scale this is
  faster than running a vector DB — retrieval is ~1–3 ms after the query embedding.
- **Incremental everything.** Only changed notes are re-chunked; embeddings are
  cached by content hash, so re-indexing an unchanged vault costs **zero** API calls.
- **The graph is free.** Your wikilinks and unlinked title mentions already encode
  the entity graph other tools reconstruct with LLM calls. Lemory uses them at
  retrieval time: hits pull in their linked neighbors, which is what answers
  multi-hop questions ("what's the hobby of the person who leads Project X?").
  Optional `enrich_entities = true` adds cognee-style LLM entity edges for vaults
  with few links.
- **Free-tier friendly.** Everything runs on one Gemini free-tier key: batched
  embeddings, RPM throttling, 429/503 backoff with server-advised delays, and
  automatic model fallback.
- **Korean-ready retrieval.** Hangul is indexed as character bigrams alongside
  whole tokens (CJK-analyzer style), so 조사가 붙은 질의("윤하준**가**")도
  원형("윤하준")을 찾습니다; the title boost is particle-tolerant, and short
  keyword queries adaptively weight the lexical leg. On the 948-note mixed
  KR/EN second-brain benchmark this took planted-fact hit@1 from 56% to 100%.
- **qmd-style LLM stages (optional).** `--expand` rewrites the query into
  variants that are searched and fused; `--rerank` blends LLM relevance scores
  into the ranking — both off by default (each costs one LLM call), degrade
  gracefully, and are inspired by Tobi Lütke's qmd retrieval pipeline.

## Benchmarks

Lemory's hybrid retrieval is benchmarked against naive-RAG (pure vector, same
embeddings), BM25, an ablation without the graph, and mem0 (OSS) as an external
system — on real SQuAD v2 data and a multi-hop personal-wiki benchmark.
See [BENCHMARKS.md](BENCHMARKS.md) for numbers and methodology; headline: on
multi-hop questions Lemory retrieves the full supporting evidence for **100%**
of questions vs ~40% for vector-only RAG, at equal single-hop quality.

Reproduce with:

```bash
python benchmarks/prep_squad.py        # downloads SQuAD v2 dev (real data)
python benchmarks/run_retrieval.py squad
python benchmarks/run_retrieval.py multihop
python benchmarks/run_e2e.py multihop 40
```

## Configuration

Everything works with defaults; override via `lemory.toml`, env (`LEMORY_*`), or
`lemory.configure(...)`:

```toml
[lemory]
vault = "~/Obsidian/MyVault"
# provider = "auto"             # auto | gemini | openai (auto picks from available keys)
# chunk_chars = 1400
# graph_expansion = true
# mention_links = true          # unlinked title mentions as graph edges
# enrich_entities = false       # optional LLM entity extraction (uses quota)
# llm_model = "gemini-2.5-flash"
# openai_llm_model = "gpt-4o-mini"
# embed_dim = 768
```

### Providers

Lemory runs on **Gemini** (default; a free-tier key is enough) or **OpenAI** —
set `GEMINI_API_KEY` or `OPENAI_API_KEY` and `provider = "auto"` does the rest.
Both providers implement the same interface (LLM, batched embeddings, rate
limiting, retries). Switching embedding providers changes the vector space, so
run `lemory index --full` after a switch — the cache is keyed by model, nothing
mixes silently.

## Development

```bash
uv venv && uv pip install -e ".[dev]"
pytest              # offline test suite (fake embedder, no network)
```
