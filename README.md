<div align="center">

# 🍋 Lemory

**Your Obsidian vault, answering back.**

A zero-service personal knowledge base backend: point it at your vault and it becomes a
live, queryable second brain — hybrid semantic + keyword + link-graph + **time-aware**
retrieval, with cited answers in any language you write in.

[![CI](https://github.com/jwgo/lemory/actions/workflows/ci.yml/badge.svg)](https://github.com/jwgo/lemory/actions)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)
[![Benchmarks](https://img.shields.io/badge/benchmarks-reproducible-orange.svg)](BENCHMARKS.md)

<img src="docs/assets/webui.png" alt="Lemory answering '요새 내가 읽던 책 뭐였지?' — the current book, with dated citations" width="820">

*"What was that book I've been reading lately?" — Lemory finds the **current** answer,
not the one from four months ago, and cites the exact notes.*

</div>

---

## Why Lemory

**🎯 Retrieval that measurably wins.** Same corpus, same embeddings, same generator,
same judge — only the retrieval differs:

| Benchmark | **Lemory** | naive RAG | mem0 | cognee | supermemory | qmd |
|---|---|---|---|---|---|---|
| Multi-hop (full-support@8) | **1.000** | 0.561 | 0.579 | 0.561 | 0.579 | 0.526 |
| [LOCOMO](https://github.com/snap-research/locomo) (LLM-judge) | **0.706** | 0.688 | 0.669¹ | — | — | — |
| [LongMemEval_S](https://github.com/xiaowu0162/LongMemEval) (LLM-judge) | **0.76** | 0.76 | — | — | — | — |
| DMR (500 q, LLM-judge) | **0.694** | 0.648 | — | — | — | — |
| Query robustness (KR/typo/paraphrase) | **0.95–0.98** | 0.25–0.49 | — | — | — | 0.00–0.21 |
| Retrieval latency (p50) | **~3 ms** | ~1 ms | 212 ms | ~5,000 ms | 327 ms | 0.6–59 s |

<sub>¹ mem0's published score (their own eval). All in-harness numbers and how to
reproduce them: **[BENCHMARKS.md](BENCHMARKS.md)**. External systems ran with the
same Gemini models wherever they allow it.</sub>

**🕐 It knows what "요새" and "recently" mean.** Notes get dates (frontmatter › daily-note
filename › mtime). "What did we decide yesterday?", "지난주 A/B 결과?", "what's the
current owner?" — recency multiplies relevance, explicit windows filter, and when facts
changed over time **the newest one wins** while history stays reachable. On a 6-month
scenario vault with evolving facts: hit@1 **1.000** vs 0.273 (vector) / 0.636 (BM25).

**🔌 Zero services, five surfaces.** One SQLite file + numpy. No Docker, no vector DB,
no graph DB. Use it from the **CLI**, the built-in **web UI**, **Obsidian** (bundled
plugin), **Claude Code / VS Code** (MCP), or **Python/HTTP**.

**🇰🇷 Korean-native.** Hangul unigram+bigram indexing (조사가 붙어도, 한 글자 단어도
매칭), particle-tolerant ranking, cross-lingual queries (Korean questions over English
notes: 0.975). Answers come back in your language.

**🔑 One key — or none.** Everything runs on a single free-tier Gemini key. Or run
`pip install "lemory[local]"` and search works **fully offline** with local multilingual
embeddings (220 MB, one-time).

## Quickstart

```bash
pipx install "git+https://github.com/jwgo/lemory"   # or: pip install ...
lemory setup      # vault path + free Gemini key → checks + first index
lemory ask "요새 내가 하던 그 프로젝트 어디까지 했지?"
```

Then keep it alive:

```bash
lemory serve      # web UI at http://127.0.0.1:8377 + live vault watcher
```

<details>
<summary><b>Use it from Obsidian</b></summary>

Copy the bundled plugin and enable it — the sidebar asks your vault with
clickable, dated citations:

```bash
cp obsidian-plugin/{main.js,manifest.json,styles.css} \
   <vault>/.obsidian/plugins/lemory/
```

Requires `lemory serve` running. See [obsidian-plugin/README.md](obsidian-plugin/README.md).
</details>

<details>
<summary><b>Use it from Claude Code / Claude Desktop / VS Code (MCP)</b></summary>

```bash
claude mcp add lemory -- lemory mcp --vault ~/Obsidian/MyVault
```

Six tools: `search_notes`, `ask_notes`, `recent_notes`, `read_note`, `list_notes`,
`vault_status` — search first, then drill into full notes filesystem-style.
</details>

<details>
<summary><b>Use it from Python</b></summary>

```python
import lemory

lemory.configure(vault="~/Obsidian/MyVault")
lemory.index()                                   # incremental; re-runs are free
print(lemory.ask("what did I decide about pricing?").text)
```
</details>

## How it works

```
 Obsidian vault (*.md)
    │  watcher: content-hash diff → only changed notes re-embed (cache!)
    ▼
 parse: frontmatter · tags · [[wikilinks]] · aliases · dates
    → heading-aware chunks, embedded with "Title > Heading" breadcrumbs
    → knowledge graph FOR FREE: wikilinks + unlinked title mentions
    ▼
 one SQLite file: chunks · FTS5 (BM25) · link graph · embedding cache
    ▼
 query ──► typo repair (local did-you-mean)
       ──► dense top-k  ┐
       ──► BM25 top-k   ├─ weighted RRF fusion ─► title boost ─► recency boost
                        ┘                                        (if temporal)
       ──► 1-hop graph expansion  ← this is what answers multi-hop questions
    ▼
 top-k diverse chunks ──► Gemini ──► answer with [n] citations & dates
```

Search itself is **local and LLM-free** (~3 ms after the cached query embedding).
The only per-query API cost is one embedding call. `ask()` adds one generation call
and keeps context small (~550 tokens typical; `context_style="compact"` aggregates
to dated one-line facts, cutting tokens a further 25% with zero extra LLM calls).

## Features that come from using it, not from a spec sheet

- **"아 그거 뭐였지?" queries work** — vague recency, explicit windows (어제/지난주/
  N일 전/3월에/yesterday/last week), superseded facts resolve to the latest.
- **Typos survive** — unknown words get a local did-you-mean pass against your
  vault's own vocabulary (0 API calls): typo robustness 0.825 → 0.965.
- **List questions get full answers** — "What books has she read?" auto-widens
  retrieval depth (adaptive-k) so every mention reaches the model.
- **Renames, deletes, aliases, date frontmatter, Korean filenames** — all handled
  live under the watcher; 236 offline tests cover the messy cases.
- **`lemory doctor`** diagnoses vault/key/API/index in one shot;
  **`lemory recent`** answers "요새 내가 뭐 만졌지?" without an LLM.
- **Crash-safe** — corrupted index quarantines and rebuilds itself (your vault is
  the source of truth); concurrent CLI+server access just works.

## Configuration

Everything has working defaults. Override via `lemory.toml`, env (`LEMORY_*`), or
`lemory.configure(...)`:

```toml
[lemory]
vault = "~/Obsidian/MyVault"
# provider = "auto"            # gemini | openai | local (keyless)
# recency_half_life_days = 21
# context_style = "full"       # or "compact" (fact-sheet context)
# graph_expansion = true
# enrich_entities = false      # optional cognify-style LLM entity graph
```

## Benchmarks & honesty

Every number above is generated by code in [`benchmarks/`](benchmarks/) with
committed corpora, seeded sampling, gold labels verified by construction, and
identical generator/judge across systems. Run them yourself:

```bash
python benchmarks/gen_multihop.py && python benchmarks/run_retrieval.py multihop
python benchmarks/run_locomo.py        # downloads LOCOMO, judged eval
python benchmarks/run_temporal.py      # the "요새 그거 뭐였지" scenario
```

Known limits (also in [BENCHMARKS.md](BENCHMARKS.md)): LOCOMO/LongMemEval use
stratified samples (160/100 questions) sized for API budgets — `--all` runs the
full sets; published numbers from other teams use different generators/judges and
are quoted as context, not as same-harness comparisons.

## Roadmap

- [ ] PyPI release (`pip install lemory`)
- [ ] Obsidian community plugin store listing
- [ ] Attachment & PDF indexing
- [ ] Entity-graph enrichment on by default (budget-aware)
- [ ] Multi-vault profiles

## Contributing

`uv venv && uv pip install -e ".[dev]" && pytest` — the suite is offline and needs
no API key. See [CONTRIBUTING.md](CONTRIBUTING.md). 한국어 이슈/PR 환영합니다.

**[한국어 README](README.ko.md)** · MIT © Lemory contributors
