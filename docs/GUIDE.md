# 🍋 Lemory Getting-Started Guide

Ten minutes from zero to an Obsidian vault that answers questions.
**The whole path is free** (one free API key, no credit card — or no key at all).

*한국어 가이드: [GUIDE.ko.md](GUIDE.ko.md)*

---

## 0. What you need

| Requirement | How to check |
|---|---|
| Python 3.10+ | `python3 --version` |
| An Obsidian vault (any folder of `.md` files works) | you just need its path |
| A free Gemini API key (2 min, issued below) | — |

> You don't need Obsidian itself — any folder of markdown files is a vault.

## 1. Install

```bash
pipx install "git+https://github.com/jwgo/lemory"
# or: pip install "git+https://github.com/jwgo/lemory"
```

## 2. Get the free key (no credit card)

1. Open https://aistudio.google.com and sign in with a Google account
2. **Get API key** → **Create API key**
3. Copy the key

Without a billing account attached there is **no way to be charged** — hitting
the free limit means waiting, not paying. Lemory rate-limits itself to stay
inside it.

## 3. Setup — one click is enough

```bash
lemory up ~/Obsidian/MyVault   # zero questions: detect key → pick mode → index → dashboard
```

Key in the environment → full mode; no key → local/keyless mode, upgraded in
place when a key appears. Prefer choosing step by step? The wizard:

```bash
lemory setup
```

It asks for your vault path, lets you pick an execution mode
(**1** Gemini free API · **2** fully local via Ollama · **3** search-only
local), health-checks the connection, and runs the first index. Then:

```bash
lemory ask "what did we decide in last week's meeting?"
```

## 4. Leave it running — backend mode

```bash
lemory serve
```

Open **http://127.0.0.1:8377** for the web console:

- **Overview** — notes/chunks/graph stats, sync activity, one-click reindex
- **Knowledge** — browse the vault as a hierarchy: folder tree, tags,
  per-note chunks, outgoing links and backlinks
- **Search** — ms-fast hybrid search, or ask and get a cited answer
- **Settings** — retrieval knobs, applied live, saved to `lemory.toml`
- <kbd>⌘K</kbd> — jump anywhere, fuzzy-find any note

While it runs, edits to the vault are re-indexed **within seconds**.

---

## How free is free?

On the Gemini free tier, what Lemory actually consumes:

| Action | API cost | What the free tier allows |
|---|---|---|
| First index, 1,000 notes (~3,000 chunks) | ~47 embedding calls | ~5% of one day's quota |
| Re-index after editing a note | that note's chunks only | negligible |
| Full re-index, unchanged vault | **0 calls** (content-hash cache) | unlimited |
| Search | 1 embedding call (cached per query) | hundreds per day |
| `ask()` — cited answer | 1 embed + 1 generation | **~250 questions/day** |

The content-addressed embedding cache means a paragraph is never embedded
twice — editing back and forth, or a full rebuild, costs nothing.

### Zero keys, 100% offline — two local modes

Pick a number in `lemory setup`:

**Mode 2 — fully local (Ollama): even answers run offline**

- LLM: **Gemma 3n E4B** (4-bit quant, ~5.6 GB) — `ask()` answers locally
- Embeddings: **Harrier-OSS-0.6B** (Q8, ~640 MB, 1024d, Qwen3-based multilingual)
- Setup: install [ollama.com](https://ollama.com/download) → `lemory setup` → `2`.
  The wizard offers to run the `ollama pull`s for you.
- Not a byte of your vault ever leaves the machine.

**Mode 3 — light local (fastembed): search-only**

- Multilingual MiniLM embeddings (220 MB, 384d). Everything except `ask()`.
- Setup: `pip install "lemory[local]"` → `lemory setup` → `3`.

**Minimum specs**

| Mode | RAM | Disk | Notes |
|---|---|---|---|
| 1 Gemini API | anything | ~0 | needs internet, any machine |
| 2 fully local (Ollama) | **8 GB+ (16 GB nice)** | ~6.5 GB | CPU works; GPU makes answers snappy |
| 3 light local | 4 GB | ~250 MB | Raspberry-Pi-class hardware is fine |

Mixed mode works too: local embeddings + API generation — only the few
retrieved chunks are ever sent out, never the vault.

> **Re-index time is announced up front.** `lemory index` prints
> "N notes · M chunks to embed · ETA ~X" before running; the console's full
> reindex button shows the same estimate. First estimates use provider
> defaults; after one run they use your machine's measured speed.

> **⚠ Switching embedding models triggers a one-time full re-embed** —
> different models produce incompatible vector spaces, so Lemory detects the
> switch automatically and re-embeds rather than silently corrupting search.
> The cache is per-model, so switching *back* is free.

---

## Things people actually ask it

```bash
lemory ask "what budget did we settle on at the Q3 kickoff?"          # meetings
lemory ask "who leads the data platform team and what do they own?"  # org
lemory ask "how did the remote-work policy change since last year?"  # policy diff
lemory ask "explain the JS event loop from my own study notes"       # learning
lemory ask "what did I say to prep before the Chaos Vellum fight?"   # game notes
lemory ask "steps for handling an allergy flare-up, in order?"       # health
lemory ask "name of that ramen place I went to in Osaka?"            # travel
```

Multi-hop — where Lemory is structurally ahead:

```bash
lemory ask "what database does the Project Atlas lead prefer?"
# Atlas note → [[lead]] wikilink → the answer lives in that person's note
```

Time-aware:

```bash
lemory ask "what book am I reading these days?"   # the current one, not March's
lemory ask "what was I reading in March?"         # asking about the past reaches it
lemory recent                                     # recently-touched notes, no LLM
```

Scoped (khoj-style operators, all retrieval modes):

```bash
lemory search "tag:meetings budget decision"   # only inside #meetings
lemory search "folder:projects deadline"       # only under that folder
lemory search "tag:log"                        # bare filter = newest-first listing
```

Writing memories back (it's not a read-only index):

```bash
lemory remember "VPN renewal is every March, Kim owns it" --tags ops
lemory context                            # one-call vault digest (pipe to any agent)
lemory import-chats conversations.json    # ChatGPT/Claude export → searchable notes
```

Second-brain maintenance (all zero-LLM, all reading the index you already have):

```bash
lemory suggest-links          # notes that mention each other but were never linked
lemory drift                  # broken wikilinks, dead file links, unresolved dup flags
lemory drift --prompt         # the above as one agent-ready repair prompt
lemory graph --open           # export the whole vault as an interactive HTML graph
lemory skill install claude-code   # teach the assistant to search-first and cite notes
```

A suggested weekly/monthly routine for using this as a second brain is in
[docs/ROUTINE.ko.md](ROUTINE.ko.md).

## When to turn on the LLM (hard multi-hop questions)

The defaults are LLM-free on purpose: search is milliseconds and costs
nothing. That is the right trade for the overwhelming majority of questions,
and the benchmarks show it wins on paraphrase, Korean, keyword, and typo
robustness without any model in the loop.

The one place a language model genuinely helps is **deep multi-hop on a huge
vault** — "A가 위치한 지역의 X" where the answer note is only reachable through
a link and never mentions the query's words. On the 33k-chunk namuwiki corpus
this is hard for every system: Lemory's zero-LLM 2-hop full-support is ~0.14,
and the honest reason is that the answer note carries almost no lexical or
semantic signal of its own (BENCHMARKS 5e keeps this as a standing open
problem). The systems that crack it do so with an LLM: qmd's full local-LLM
pipeline reaches 2-hop doc-coverage 1.000 on the same corpus — at ~60 seconds
per query.

Lemory exposes the same two knobs, off by default:

```toml
# lemory.toml
query_expansion = true   # rewrite the query into variants before searching
rerank = true            # LLM-score the top candidates after fusion
```

or per call: `lemory search "..." --expand --rerank`.

**Two honest caveats, both measured.**

First, the model matters enormously, and small local models are not enough.
On a 40-question 2-hop sample over the namuwiki corpus, with a local
`qwen2.5:3b` through Ollama:

| setting | 2-hop full-support | latency |
|---|---|---|
| baseline (0 LLM) | 0.125 | 20 ms |
| + query_expansion | 0.150 | 1.5 s |
| + rerank | 0.100 | 6.5 s |
| + expand + rerank | 0.075 | 7.3 s |

Query expansion gave a small bump; **rerank with a 3B model actively hurt**,
demoting correct chunks with noisy relevance scores. qmd reaches 2-hop 1.000
because it ships purpose-built expansion and reranker models, not a generic
small LLM. So: try `query_expansion` on a *capable* model for a specific
multi-hop question that comes back empty, leave the generic `rerank` off, and
do not expect a small local model to crack deep multi-hop by itself.

A *dedicated* query-expansion model (measured: qmd's own
`qmd-query-expansion-1.7B`, MIT) roughly doubles the generic gain on 2-hop
(0.125 -> 0.175 vs a generic 3B's 0.150; specialization helps) but it
was trained on an English/tech query distribution and hallucinates on short
Korean queries ("스우 테마곡" -> "big data"), so it is a poor default for a
Korean-first vault. Worth trying, not worth hard-wiring.

**Use a dedicated reranker, not generic LLM scoring.** Lemory ships a proper
cross-encoder path: set `reranker = true` and it scores candidates with
Qwen3-Reranker (`ollama_reranker_model`) instead of asking a chat model to
grade itself. Measured on the namuwiki corpus, 30 single/masked questions,
local Qwen3-Reranker-0.6B:

| | recall@1 | recall@8 | latency |
|---|---|---|---|
| baseline | 0.633 | 0.767 | 36 ms |
| + dedicated reranker | **0.700** | 0.767 | 4.1 s |

That is the reranker doing exactly its job: recall@8 unchanged (it can only
reorder what was already retrieved), recall@1 up 6.7 pt (it promotes the
right retrieved note to the top). It does **not** help deep multi-hop, whose
failure is recall (the answer note never entered the candidate set), not
ranking — a reranker cannot surface what retrieval missed. So reach for
`reranker` when the right note is *in* the results but not at #1, accept the
seconds-per-query cost, and keep it off for everyday lookups.

### The local stack, in tiers

Everything above is opt-in on top of a fast, free default. Pick the tier you
want in `lemory setup` or `lemory.toml`:

1. **Default (fastembed MiniLM):** zero keys, ~220 MB, milliseconds. The
   right choice for almost everyone.
2. **Stronger embeddings (Ollama, Harrier-OSS-0.6B Q8):** `provider = ollama`
   swaps the vector leg to Microsoft's Qwen3-based multilingual embedder.
   Measured on KorMapleQA: hybrid **doc@8 0.788 → 0.853 (+6.5pt)**, closing
   over half the gap to the Gemini ceiling (0.906) with zero keys. The gains
   land on the hard types (masked +11, 2-hop full-support 0.18 to 0.29, typo
   +7). The trade is query latency (~100 ms vs ~18 ms: an Ollama embed
   round-trip) and slow first-index of a very large vault (Ollama embeds a
   33k-chunk corpus in ~2 h on an M4 vs fastembed's minutes; it is one-time).
   `ollama pull hf.co/mradermacher/harrier-oss-v1-0.6b-GGUF:Q8_0`.
3. **Precision mode (+ dedicated reranker):** `reranker = true` adds the
   Qwen3-Reranker pass above. Seconds per query, +recall@1.
4. **Grounded answers (+ Gemma):** `ollama_llm_model` (default `gemma3n:e4b`)
   powers `lemory ask` fully offline. Retrieval never needs it; only `ask`
   does.

Second, when you do run an LLM, run it **local, not the free-tier API**. The
slowness of an LLM pipeline is almost never the model, it is the API queue
(we hit the exact `429 credits depleted` wall measuring this). Ollama on an
M-series laptop answers a `generate_json` call in ~1.3 s with no per-query
bill and no queue. Point Lemory at it with `lemory setup` → local mode or
`LEMORY_PROVIDER=ollama`.

## Big vaults

- Benchmarked on **1,469 real namuwiki documents (33,375 chunks, 24,850 real
  wikilink edges)**: recall@8 1.00 at ~0.2 s/query, one SQLite file.
- Synthetic scaling: full hybrid+graph search in 70 ms at 50k chunks.
- A whole life + whole job ≈ 10k–50k notes — comfortably inside the envelope.
- Past 20k chunks Lemory auto-switches to an IVF-int8 vector index (numpy
  only): measured **1M chunks at 5.9 ms/query, recall@10 = 1.000 vs exact,
  732 MB RAM instead of 2.9 GB** (BENCHMARKS §12b). Small vaults keep exact
  search unchanged.
- PDFs index too, opt-in: `index_pdf = true` + `pip install 'lemory[pdf]'`.

## When something's off

```bash
lemory doctor     # one-shot: vault / key / API / index diagnosis
lemory status
```

| Symptom | Fix |
|---|---|
| `No API key found` | set `GEMINI_API_KEY` — `lemory setup` does it for you |
| 429 / brief stalls | free-tier limit; Lemory waits and retries. Not a charge |
| Odd results | `lemory index --full`; still odd → open an issue |
| Console won't open | is `lemory serve` running? port 8377 free? |

## Next steps

- **Inside Obsidian**: copy the 3 files from `obsidian-plugin/` into
  `<vault>/.obsidian/plugins/lemory/`, enable in Community plugins
- **Claude Code / Claude Desktop**: `claude mcp add lemory -- lemory mcp --vault <vault>`
- **The receipts**: [BENCHMARKS.md](../BENCHMARKS.md) — every number reproduces
