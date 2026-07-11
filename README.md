<div align="center">

# 🍋 Lemory

### Your memory should belong to you.
**Not rows in someone's database — Markdown files, in your own vault.**
<sub>기억은 당신의 것이어야 합니다 · **[한국어 README](README.ko.md)**</sub>

[![CI](https://github.com/jwgo/lemory/actions/workflows/ci.yml/badge.svg)](https://github.com/jwgo/lemory/actions)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)
[![Benchmarks](https://img.shields.io/badge/benchmarks-reproducible-orange.svg)](BENCHMARKS.md)

<img src="docs/assets/demo-read.gif" alt="Real demo on the Obsidian CEO's public vault: a 2-hop question answered with citations in one shot" width="820">

<sub>Not a mock — this is the search console on **Steph Ango's (Obsidian CEO)
real public vault**: a 2-hop question ("meeting with Steph" note → "Out of
Control" note) answered with citations. Reproducible from
[`benchmarks/data/kepano`](benchmarks/data/kepano).</sub>

</div>

---

**Lemory is local memory middleware for your Markdown.** It sits between your
notes and every AI you use — Claude Desktop, Claude Code, Cursor, your own
scripts — so that anything you ever wrote down becomes something they can
recall, and anything worth remembering becomes a Markdown file you own.

- **AI reads your memory**: hybrid retrieval (semantic + keyword + your
  `[[wikilink]]` graph) that we benchmark against every competitor we can run,
  and publish the losses too.
- **AI writes your memory**: decisions and facts land as plain `.md` notes in
  your vault — visible in Obsidian, versionable, greppable, one `rm` from gone.
  No proprietary store, no export button needed, nothing to migrate off of.
- **You watch the middleware**: a dashboard shows what flowed through — every
  query, every note an AI wrote (with one-click undo to Obsidian's trash),
  per-client usage. All of it local, in one SQLite file.

The industry's memory products want your knowledge as rows in *their*
database — Postgres, Qdrant, a hosted API. We think the file you already own
is the better database, and we spent the benchmarks proving it doesn't cost
you accuracy: the opposite, measurably.

## Start with one command

```bash
pipx install "git+https://github.com/jwgo/lemory"
lemory up ~/Obsidian/MyVault     # 딸깍: detect key → pick mode → index → dashboard
lemory ask "요새 내가 하던 그 프로젝트 어디까지 했지?"
```

`lemory up` asks zero questions: a Gemini key in the environment → full mode;
no key but fastembed installed → local search mode; neither → **keyless mode**
(BM25 + your link graph — still useful, and it upgrades in place the moment a
key appears). Prefer a guided wizard? `lemory setup`. No LLM pipeline runs at
ingest either way — **indexing 1,000 notes costs 0 LLM calls** and is
searchable in seconds, not the ~45 minutes of LLM graph-building some
competitors need for a 54-note vault. Your wikilinks already *are* the
knowledge graph; we just read them.

**New here? Step-by-step: [docs/GUIDE.md](docs/GUIDE.md)
(한국어: [docs/GUIDE.ko.md](docs/GUIDE.ko.md)).**

## Give your AI a memory — any AI

```bash
claude mcp add lemory -- lemory mcp --vault ~/Obsidian/MyVault --client claude-desktop
```

| Client | Setup |
|---|---|
| Claude Code / Desktop | `claude mcp add lemory -- lemory mcp --vault <vault> --client claude-code` |
| Cursor | add to `.cursor/mcp.json`: `{"lemory": {"command": "lemory", "args": ["mcp", "--vault", "<vault>", "--client", "cursor"]}}` |
| Windsurf / VS Code / Codex CLI / any MCP client | same stdio command — `lemory mcp --vault <vault> --client <name>` |
| Scripts / your own agent | REST with an `X-Lemory-Client` header (below) |

The `--client` name is how each app shows up in the dashboard's per-client
usage — you always know who is reading and writing your memory.

Ten tools (with MCP behavior annotations, so clients know what's read-only).
Read: `search_notes` · `ask_notes` · `recent_notes` · `read_note` ·
`list_notes` · `related_notes` · `vault_status` · `vault_context` (one-call
session context: recent activity, hot notes, hubs, tags — Zep-style, ~ms,
zero LLM). Write: `save_memory` · `append_note` — never overwrites, can't
escape the vault, append-only edits.

### Automatic session memory (one command)

```bash
lemory hooks install claude-code
```

Registers a SessionEnd lifecycle hook: when a Claude Code session ends, the
decisions, facts and open threads worth keeping are summarized into **one
dated Markdown note** in your vault — no discipline required, and unlike the
hook-based memory tools, every capture lands in the dashboard feed with
attribution and one-click undo. Prefer manual control? The `CLAUDE.md`
instruction pattern still works:

```markdown
At the start of a session, call lemory's vault_context once for situational
awareness. When we settle a decision, a fact worth keeping, or a preference,
save it with save_memory (concise, one memory per note). Search the vault
with search_notes before asking me things my notes already answer.
```

**Privacy is a file property**: put `lemory: false` in any note's frontmatter
and it is never indexed, never retrieved, never sent to any model — and if it
was indexed before, the flag removes it.

Every write shows up in the dashboard's **AI 메모리 피드** with who wrote it
and an undo button (moves the note to `<vault>/.trash` — Obsidian's own
trash; human-authored notes are refused by construction). Every query shows
up in **최근 질의** with its top sources. That's the middleware contract:
nothing passes through invisibly.

<img src="docs/assets/demo-write.gif" alt="Claude saves a memory — it appears in the feed as a Markdown file, attributed to claude-desktop, with one-click undo" width="820">

## The dashboard

`lemory serve` → `127.0.0.1:8377`. Not a second Obsidian — a view of the
*middleware*:

- **현황** — the timeline: AI memory feed (with undo), recent queries and
  their sources, per-client usage (`claude-desktop` vs `cursor` vs `cli`),
  index activity, which vector index is active
- **지식** — per-note detail: chunks as indexed, links in/out, a local graph
  that shows the *mention* edges Obsidian's graph can't see, related notes by
  content, reference counts
- **검색** — hybrid/vector/BM25 playground with score bars and latency readout
- **설정** — retrieval knobs with live apply; the timeline itself is a
  setting (`event_log`) and all of it stays in your local SQLite file

<img src="docs/assets/console-knowledge.png" alt="지식 — 노트 상세, 로컬 그래프, 관련 노트" width="820">

## Files vs rows — why this beats a memory API for personal knowledge

The closest thing to Lemory is mem0's OpenMemory (local MCP memory with a
dashboard). The difference is what a "memory" *is*:

| | **Lemory** | OpenMemory (mem0) | supermemory self-host | basic-memory | qmd |
|---|---|---|---|---|---|
| A memory is | **a Markdown file you own** | a row in Postgres+Qdrant | a record in its binary's store | a Markdown file | (read-only index) |
| Runs as | 1 process, 1 SQLite file | Docker: Postgres + Qdrant + UI | 1 binary + external embeddings | pip package | bun CLI |
| Ingests your existing notes | **yes — that's the point** | no (chat-extracted memories) | uploads | partially | yes |
| Ingest LLM calls | **0** | per-conversation extraction | API-side | 0 | 0 |
| Dashboard | timeline + undo + clients | memory CRUD UI | console | — | — |
| Retrieval, measured by us | **multi-hop 1.000 · ~3 ms** | mem0 OSS: 0.579 · 212 ms | 0.579 · 327 ms | not benchmarkable¹ | 0.526 · 0.6–59 s |
| Korean retrieval | **Hangul-bigram FTS, 0.975 measured** | EN-first | EN-first | EN-first | EN-first |
| Leaving costs | nothing — files stay | export/migrate | export/migrate | nothing | nothing |

<sub>¹ basic-memory is graph-navigation-first; it has no ranked retrieval to
measure. All measured numbers from the same harness, same models, same corpus
— [methodology](BENCHMARKS.md).</sub>

Extraction-based memories (rows) are *summaries of* what you said — lossy at
write time, unverifiable later. File-based memory retrieves the actual note,
with the date, in context. That's also why retrieval quality is measurable
here at all.

## Proof on real data — not our own synthetic sets

**Questions the way people actually ask them** (paraphrased / Korean question
→ English notes / keyword shorthand / typos; full-support@8):

| | original | paraphrase | 한국어 질문 | keyword | typo |
|---|---|---|---|---|---|
| **Lemory** | **1.000** | **0.964** | **0.975** | **1.000** | **1.000** |
| Vector-only | 0.544 | 0.464 | 0.475 | 0.482 | 0.491 |
| BM25 | 0.579 | 0.429 | 0.250 | 0.482 | 0.404 |

**Against the field** — 7 systems run by us on the same corpus, same models
wherever the system allows it. Including the two biggest names of 2026:
LightRAG (37.6k stars, EMNLP) and MemPalace (57.2k stars):

| | **Lemory** | LightRAG | MemPalace | mem0 | cognee | supermemory | LlamaIndex | qmd |
|---|---|---|---|---|---|---|---|---|
| Multi-hop answer-in-context@8 | **1.000** | 0.807¹ | 0.596 | 0.579 | 0.561 | 0.579 | 0.649 | 0.526 |
| — 2-hop questions only | **1.000** | 0.738 | 0.452 | — | — | — | — | — |
| Ingest, 54 notes | **0 LLM calls, ~30 s** | 165 calls, 14 min | local embeds | 1-2 calls/note | ~45 min | API-side | 0 | 0 |
| Retrieval latency (p50) | **~3 ms** | 7.5 s² | ~1 s³ | 212 ms | ~5 s | 327 ms | 649 ms⁴ | 0.6–59 s |
| 한국어 질문 (full-support) | **0.975** | — | 0.350 | — | — | — | — | — |

<sub>¹ Generous to LightRAG: its merged entity+relation+chunk context blob is
larger than the 8 chunks every other system gets. Its LLM-built graph is
real — best competitor 2-hop score — it just costs an LLM pipeline at ingest
AND at query. ² Includes its per-query LLM keyword-extraction call under our
free-tier rate limit; ~1–2 s on a paid tier. ³ MemPalace CLI wall-clock incl.
process startup, sqlite_exact backend — its marketed zero-API config.
⁴ LlamaIndex embeds every query via API, uncached; local-only ~2 ms.
Also: **full 500-question LongMemEval_S retrieval, zero API calls** (local
MiniLM embedder) — Recall@5 = 0.972 any-session / 0.857 all-evidence-sessions
([§7d](BENCHMARKS.md)); [LOCOMO](https://github.com/snap-research/locomo)
LLM-judge 0.706 vs mem0's published 0.669; DMR (500 q) 0.694 vs 0.648
same-harness naive RAG.</sub>

**[KorQuAD 1.0](https://korquad.github.io/)** — 140 real Korean Wikipedia
articles, 400 human-written questions:

| System | Recall@1 | Recall@5 | MRR@10 |
|---|---|---|---|
| **Lemory** (hybrid+graph) | 0.908 | 0.985 | 0.943 |
| Vector-only RAG | 0.855 | 0.968 | 0.902 |
| BM25 | **0.923** | **0.993** | **0.952** |

<sub>Yes, **BM25 wins this table** and we print it anyway: SQuAD-family
questions are written while looking at the passage, so vocabulary overlap is
total — grep is genuinely enough for quote-the-document questions. Nobody
queries their own memory in verbatim quotes; that's what the robustness table
above measures, and that's the product.</sub>

Real vaults we didn't write are in the suite too: Steph Ango's (Obsidian CEO)
public vault and the official Obsidian Help vault ([§5d](BENCHMARKS.md)), plus
1,469 real 나무위키 documents (33k chunks, 24,850 real wikilink edges).
Everything reproduces from [`benchmarks/`](benchmarks/).

## What it feels like

```
$ lemory ask "3분기 킥오프에서 예산 얼마로 잡았지?"                 # meetings
$ lemory ask "데이터플랫폼팀 리드가 누구고 무슨 일 하는 팀이지?"      # org / people
$ lemory ask "재택근무 정책, 작년이랑 지금이랑 뭐가 달라졌지?"        # policy diff over time
$ lemory ask "자바스크립트 이벤트 루프 뭐였지? 내 노트 기준으로"      # study notes
$ lemory ask "카오스 벨룸 가기 전에 준비물 뭐라고 적어놨더라?"        # game prep notes
$ lemory ask "알러지 올라올 때 대처 순서 뭐였지?"                    # health protocols
$ lemory ask "오사카에서 갔던 그 라멘집 이름이 뭐였지?"              # travel log
```

The ones plain RAG structurally can't do:

```
$ lemory ask "프로젝트 아틀라스 리드가 좋아하는 DB가 뭐더라?"
# multi-hop: Atlas note → [[lead]] wikilink → that person's note has the answer

$ lemory ask "요새 내가 읽던 책 뭐였지?"
요즘 읽는 책은 어스시의 마법사이다 [1, 3].     # temporal: the *current* book,
$ lemory ask "3월에 읽던 책은?"                # …but asking about March reaches history

$ lemory search "tag:회의록 folder:2026 예산"   # scoping operators, all modes
$ lemory remember "VPN 갱신은 매년 3월, 담당 김하늘" --tags ops   # write from the CLI
$ lemory import-chats conversations.json        # ChatGPT/Claude export → searchable notes
$ lemory context                                # one-call vault digest for any agent
```

Typos are repaired against your vault's own vocabulary (no API). Renames,
deletes, aliases, Korean filenames — the watcher keeps up live.

## Why it performs — mechanism, not magic

- **Multi-hop 1.000 vs 0.53–0.65 (everyone else)** — your `[[wikilinks]]` and
  unlinked title mentions *are* the knowledge graph. Retrieval expands 1 hop
  along them, gated by query similarity and capped below direct evidence.
  Mined at index time without an LLM — free, and it scored higher than the
  graphs competitors pay LLM pipelines to build.
- **Robustness 0.95+ vs 0.25–0.54** — dense vectors and BM25 fail in
  *different* ways; weighted RRF fusion covers both. Korean gets Hangul-bigram
  FTS (agglutinative morphology breaks word-token BM25).
- **Milliseconds, not seconds** — everything in-process: SQLite FTS5 +
  numpy. Above 20k chunks the vector side auto-switches to an IVF-int8 index
  (still numpy only): **1M chunks = 5.9 ms/query, recall@10 1.000 vs exact,
  732 MB RAM** ([§12b](BENCHMARKS.md)). We also benchmarked *replacing*
  SQLite (DuckDB, LanceDB) and published why we didn't ([report](docs/STORAGE.md)).
- **Cost that rounds to zero** — content-addressed embedding cache; free
  Gemini tier runs ~250 questions/day; two fully-offline modes (Ollama
  full-local, fastembed search-only) for airgapped/망분리 environments where
  zero bytes may leave the machine.
- **Time awareness** — "지난주", "요새", "3월에" parse to date ranges; changed
  facts resolve to the newest note unless you ask about the past.

## For developers

```python
import lemory
lemory.configure(vault="~/Obsidian/MyVault")
lemory.index()
print(lemory.ask("what did I decide about pricing?").text)
```

REST on `lemory serve`: `GET /search` · `POST /ask` · `GET /context` ·
`POST /memory` · `POST /append` · `POST /memory/trash` · `POST /index` ·
`GET /status`, plus the dashboard API (`/api/events`, `/api/clients`,
`/api/notes`, `/api/related`, …). Identify your integration with the
`X-Lemory-Client` header (or `lemory mcp --client <name>`) and it shows up
attributed in the dashboard timeline.

Obsidian sidebar plugin (3-file copy install), PDF indexing
(`pip install 'lemory[pdf]'`, `index_pdf = true`), every retrieval knob in
[`lemory.toml`](docs/GUIDE.md), engineering deep-dives in
[BENCHMARKS.md](BENCHMARKS.md) · [docs/STORAGE.md](docs/STORAGE.md) ·
[docs/COMPETITIVE.md](docs/COMPETITIVE.md).

## How it works

```
 your vault (*.md) ──watch──► parse: frontmatter · tags · [[links]] · dates
                                 │
                                 ▼
              one SQLite file: chunks · BM25 · link graph · embed cache
                              + event timeline        + IVF-int8 (big vaults)
                                 │
 query ─► typo repair ─► dense + lexical (RRF fusion) ─► title & recency boosts
                                 │
                        1-hop graph expansion   ← multi-hop answers come from here
                                 │
                                 ▼
              dated, cited context (~550 tokens) ─► LLM ─► answer [n]

 save_memory ─► plain .md in your vault ─► indexed ─► searchable next question
```

Search is local and LLM-free (~3 ms). One embedding call per query (cached),
one generation call per `ask()`.

## Honesty section

- KorQuAD-style verbatim questions favor pure BM25 (we show it above). Lemory
  detects verbatim phrasing per-query and leans lexical, but we tuned for the
  robustness table — real questions aren't quotes.
- LOCOMO/LongMemEval numbers use stratified samples (160/100 q) sized for API
  budgets; `--all` flags run the full sets. Other teams' published numbers use
  different generators/judges and are quoted as context, not victory laps.
- Zep reports DMR 94.8 with a GPT-4-class setup; in our identical-model harness
  Lemory beats naive RAG by +4.6 pt. We don't claim their number's beaten.
- We benchmarked replacing SQLite itself (DuckDB, LanceDB — [full report](docs/STORAGE.md)).
  LanceDB's FTS is genuinely ~5× faster than our FTS5 path on a worst-case
  corpus; we publish that and stay on SQLite anyway — it wins the other four
  axes (incremental sync ×82, PK lookups ×75, two-process access, zero native
  deps), and its vector story loses to our IVF-int8 on every axis measured.

## Roadmap

- [ ] PyPI (`pip install lemory`) · [ ] Obsidian community plugin listing
- [x] AI write path + dashboard timeline with undo · [x] client attribution
- [x] PDF indexing (opt-in) · [x] ANN index for 1M-chunk vaults
- [x] chat-export import (ChatGPT/Claude)
- [ ] image OCR / audio transcription (opt-in extras) · [ ] web clipper
- [ ] multi-vault profiles

## Contributing

`uv venv && uv pip install -e ".[dev]" && pytest` — 315 tests, fully offline.
[CONTRIBUTING.md](CONTRIBUTING.md) · 한국어 이슈/PR 환영합니다.

Local-first by design — the trust model, the localhost server's guards
(CORS + Host-allowlist against DNS-rebinding), and how to report a
vulnerability are in [SECURITY.md](SECURITY.md).

**[한국어 README](README.ko.md)** · MIT
