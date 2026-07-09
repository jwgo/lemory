<div align="center">

# 🍋 Lemory

### 기록은 당신이 한다. 기억은 Lemory가 한다.
**You take the notes. It does the remembering.**

[![CI](https://github.com/jwgo/lemory/actions/workflows/ci.yml/badge.svg)](https://github.com/jwgo/lemory/actions)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)
[![Benchmarks](https://img.shields.io/badge/benchmarks-reproducible-orange.svg)](BENCHMARKS.md)

<img src="docs/assets/webui.png" alt="Lemory — 지난주 회의 결정사항을 출처와 함께 답하는 장면" width="820">

</div>

---

## The problem

You've been taking notes for years. Daily logs, meeting notes, book highlights,
half-finished ideas — thousands of markdown files, faithfully accumulated.

And when you actually need something back, you `grep`. Or scroll. Or give up and
ask a coworker. **A second brain that can't answer back is just a filing cabinet.**

The memory-for-AI industry's answer is: upload everything to our cloud, we'll
extract "memories" with LLM pipelines, pay per API call. We think that's backwards.

## What we believe

1. **Your knowledge is already written down — and it's yours.** Lemory runs on
   *your* machine against *your* existing Obsidian vault. One SQLite file. No
   Docker, no vector DB, no sync to anyone's cloud. Delete the folder, it's gone.

2. **"When" is half of every memory.** Humans don't ask databases questions.
   They ask *"그거 뭐였지, 요새 내가 읽던 거?"* — vague, temporal, half-remembered.
   A real memory system must know that facts change, that "the current owner"
   means the newest note wins, and that "지난주" is a date range, not a keyword.

3. **Your links are already a knowledge graph.** Every `[[wikilink]]` you ever
   made is a curated edge. Others pay an LLM to reconstruct this structure;
   Lemory reads it for free — and that's exactly what answers multi-hop
   questions ("*그 프로젝트 리드가 좋아하는 DB가 뭐더라?*").

4. **Claims need receipts.** Every number below is reproducible from
   [`benchmarks/`](benchmarks/) — real public datasets, human-written questions,
   identical models for every system, and we publish where we *lose* too.

## Proof on real data — not our own synthetic sets

**[KorQuAD 1.0](https://korquad.github.io/)** — 140 real Korean Wikipedia
articles, 400 human-written questions (sampled from dev 5,774):

| System | Recall@1 | Recall@5 | MRR@10 | e2e answer EM (40q) |
|---|---|---|---|---|
| **Lemory** (hybrid+graph) | 0.888 | 0.985 | 0.930 | 0.875 |
| Vector-only RAG | 0.855 | 0.968 | 0.902 | 0.925 |
| BM25 | **0.923** | **0.993** | **0.952** | **0.950** |

<sub>Yes, **BM25 wins this table** and we print it anyway: SQuAD-family questions
are written while looking at the passage, so the vocabulary overlap is total —
grep-style search is genuinely enough for quote-the-document questions. But
nobody queries their own memory in verbatim quotes. Ask the same kind of corpus
in *your own words* — paraphrased, cross-lingual, typo'd — and BM25 collapses
while Lemory doesn't. That's the next two tables, and that's the product.</sub>

**나무위키 실문서 1,469편** (public 2021 dump, 33,375 chunks, **24,850 real
wikilink edges**) — code-verified QA (answer exists only in the gold note):

| System | Full-support@8 | Recall@1 | e2e F1 |
|---|---|---|---|
| **Lemory** | **0.820** | 0.820 | **0.594** |
| Vector-only RAG | 0.660 | 0.700 | 0.562 |
| BM25 | 0.560 | 0.540 | 0.406 |

**Questions the way people actually ask them** (paraphrased / Korean question →
English notes / keyword shorthand / typos; full-support@8):

| | original | paraphrase | 한국어 질문 | keyword | typo |
|---|---|---|---|---|---|
| **Lemory** | **1.000** | **0.946** | **0.975** | **0.982** | **0.965** |
| Vector-only | 0.544 | 0.464 | 0.475 | 0.482 | 0.491 |
| BM25 | 0.579 | 0.429 | 0.250 | 0.482 | 0.404 |

**Against the field** — same corpus, same embedding/generator/judge models
wherever the system allows it ([full methodology](BENCHMARKS.md)):

| | **Lemory** | mem0 | cognee | supermemory | qmd |
|---|---|---|---|---|---|
| Multi-hop full-support@8 | **1.000** | 0.579 | 0.561 | 0.579 | 0.526 |
| [LOCOMO](https://github.com/snap-research/locomo) LLM-judge | **0.706** | 0.669¹ | — | — | — |
| Retrieval latency (p50) | **~3 ms** | 212 ms | ~5 s | 327 ms | 0.6–59 s |

<sub>¹ mem0's own published number. LongMemEval_S: 0.76 (GPT-4o full-context
baseline ≈ 0.60). DMR (500 q): 0.694 vs 0.648 same-harness naive RAG.</sub>

## What it feels like

```
$ lemory ask "요새 내가 읽던 책 뭐였지?"
요즘 읽는 책은 어스시의 마법사이다 [1, 3].          # ← 넉 달 전 책이 아니라 지금 책

$ lemory ask "어제 회의에서 뭐 결정했지?"
정산 배치를 새벽 4시로 옮기기로 결정했다 [1].

$ lemory recent          # 요새 내가 뭐 만졌지? (LLM 없이, 즉시)
$ lemory doctor          # 뭔가 이상하면: 볼트/키/API/인덱스 원샷 진단
```

Typos are repaired against your vault's own vocabulary (no API). List questions
("읽은 책 전부?") auto-widen retrieval. Facts that changed resolve to the newest,
while *"3월에 읽던 책은?"* still reaches history. Renames, deletes, aliases,
Korean filenames — the watcher keeps up live.

## Quickstart — 2 minutes, 1 free key (or none)

```bash
pipx install "git+https://github.com/jwgo/lemory"
lemory setup      # vault path + free Gemini key → health check + first index
lemory ask "요새 내가 하던 그 프로젝트 어디까지 했지?"
lemory serve      # web UI (screenshot above) + live vault watcher
```

No API key at all? `pip install "lemory[local]"` — search runs fully offline on
local multilingual embeddings (220 MB once). Re-indexing an unchanged vault
costs zero API calls, ever (content-hash + embedding cache).

<details>
<summary><b>Obsidian</b> — sidebar panel, click a citation to open the note</summary>

```bash
cp obsidian-plugin/{main.js,manifest.json,styles.css} <vault>/.obsidian/plugins/lemory/
```
Enable in Settings → Community plugins. Needs `lemory serve` running.
</details>

<details>
<summary><b>Claude Code / Claude Desktop / VS Code</b> — MCP, six tools</summary>

```bash
claude mcp add lemory -- lemory mcp --vault ~/Obsidian/MyVault
```
`search_notes` · `ask_notes` · `recent_notes` · `read_note` · `list_notes` · `vault_status`
</details>

<details>
<summary><b>Python / HTTP</b></summary>

```python
import lemory
lemory.configure(vault="~/Obsidian/MyVault")
lemory.index()
print(lemory.ask("what did I decide about pricing?").text)
```
REST: `GET /search`, `POST /ask`, `POST /index`, `GET /status` on `lemory serve`.
</details>

## How it works

```
 your vault (*.md) ──watch──► parse: frontmatter · tags · [[links]] · dates
                                 │
                                 ▼
              one SQLite file: chunks · BM25 · link graph · embed cache
                                 │
 query ─► typo repair ─► dense + lexical (RRF fusion) ─► title & recency boosts
                                 │
                        1-hop graph expansion   ← multi-hop answers come from here
                                 │
                                 ▼
              dated, cited context (~550 tokens) ─► LLM ─► answer [n]
```

Search is local and LLM-free (~3 ms). One embedding call per query (cached),
one generation call per `ask()`. `context_style="compact"` aggregates retrieved
chunks into dated one-line facts — supermemory-style token efficiency with zero
extra LLM calls.

## Honesty section

- KorQuAD-style verbatim questions favor pure BM25 (we show it above). Lemory
  detects verbatim phrasing per-query and leans lexical, but we tuned for the
  robustness table — real questions aren't quotes.
- LOCOMO/LongMemEval numbers use stratified samples (160/100 q) sized for API
  budgets; `--all` flags run the full sets. Other teams' published numbers use
  different generators/judges and are quoted as context, not victory laps.
- Zep reports DMR 94.8 with a GPT-4-class setup; in our identical-model harness
  Lemory beats naive RAG by +4.6 pt. We don't claim their number's beaten.

## Roadmap

- [ ] PyPI (`pip install lemory`) · [ ] Obsidian community plugin listing
- [ ] PDF/attachment indexing · [ ] budget-aware entity-graph enrichment on by default
- [ ] multi-vault profiles

## Contributing

`uv venv && uv pip install -e ".[dev]" && pytest` — 236 tests, fully offline.
[CONTRIBUTING.md](CONTRIBUTING.md) · 한국어 이슈/PR 환영합니다.

**[한국어 README](README.ko.md)** · MIT
