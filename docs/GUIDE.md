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

## 3. Setup — one command is enough

```bash
lemory up                        # interactive: asks for your vault, then indexes
lemory up ~/Obsidian/MyVault     # zero questions: detect mode → index → dashboard
lemory up ~/Vault --key <KEY>    # Gemini cloud mode
```

`up` auto-detects the best mode: a Gemini key → cloud; llama.cpp installed →
e5-small-ko-v2 embeddings + Gemma 4 answers on-device; otherwise search-only
local. Run it interactively and it offers to `pip install "lemory[llama]"` for
on-device Gemma answers. No number menu, no wizard. Then:

```bash
lemory ask "what did we decide in last week's meeting?"
```

Want a different answer model or embedder (Gemma E4B/E2B, embedder backend,
reranker)? Change it later in the dashboard's **Settings › Models** card.

## 4. How to use it — set up once, then keep using it

The mental model is simple: **Lemory is a local backend that stays running**,
and everything else (the Obsidian plugin, Claude/MCP, the web UI, the CLI)
talks to it.

**1. Once (setup)**
```bash
lemory up ~/Obsidian/MyVault      # config + first index + serve, in one go
```
Search works with no key at all (local embeddings). Want AI answers (`ask`)?
`lemory up` sets up on-device Gemma 4 by default (no key) when llama.cpp is
installed; pass `--key <KEY>` for Gemini instead.

**2. Keep it running (recommended — the always-on backend)**
```bash
lemory serve                       # http://127.0.0.1:8377
```
- Web console: **Overview** (stats, one-click reindex) · **Knowledge** (folder
  tree, backlinks) · **Search** (cited answers, or ms-fast search) · **Settings**
  (embedder + retrieval knobs, from the screen) · <kbd>⌘K</kbd> jump anywhere.
- **While it runs, vault edits re-index within seconds** — no manual indexing.
- **When you need it on:** the Obsidian plugin, the web dashboard, and the REST
  API all require `serve`. Start it on login and you have "always-there memory".

**3. One-off, no server needed**
```bash
lemory ask "where did I leave that project?"   # straight from the terminal
lemory search "pricing policy" · lemory recent · lemory remember "..."
```
These open the index directly, so they work whether or not `serve` is running.

**4. When to re-run something**
- Changed a lot of notes while `serve` was off → `lemory index` (incremental).
- **Switched the embedding model/provider** → `lemory index` (the vector space
  changes, so it re-embeds everything).
- Moved the vault, or a new machine → `lemory up` again.

**Wiring it into Claude/Cursor** — MCP spins its own engine, no `serve` needed:
```bash
claude mcp add lemory -- lemory mcp --vault ~/Obsidian/MyVault --client claude-code
```

Stuck? `lemory doctor` tells you which tier you're on, whether `ask` works, and
what to do next.

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

### Zero keys, 100% offline — everything on-device, no daemon

Every local path runs **in-process on one llama.cpp engine** — no Ollama, no
server to babysit, GPU everywhere it exists (Metal on Mac, CUDA/Vulkan on
Linux/Windows, CPU offload otherwise), the way qmd uses node-llama-cpp. `lemory
up` picks the right one for your machine:

**Mode 1 — ⭐ best local (recommended): even answers run offline**

The whole stack on-device, keyless — this is what `lemory up` sets up by default
when llama.cpp is present. It offers to `pip install "lemory[llama]"` (for the
answer model); the GGUFs auto-download once.

- Embeddings: **e5-small-ko-v2** (dragonkue's Korean-tuned multilingual-e5-small,
  fastembed, 384d, no compile). Measured hybrid **doc@8 0.889** on KorMapleQA —
  the strongest local embedder we measured, above the 1024-d Harrier (0.853).
- Answers: **Gemma 4 E4B** (Q4_K_M GGUF) on llama.cpp GPU, streamed. Switch to
  the lighter **E2B** in the web console. This is what `lemory[llama]` is for.
- A dedicated reranker is available (`reranker = true`) but ships **off** — a
  small reranker measured *worse* on the strong embedder (see below). Not a byte
  of your vault ever leaves the machine.

**Mode 2 — light local (search-only): no answer model**

- Same **e5-small-ko-v2** embedder, without the Gemma answer model — `pip
  install "lemory[local]"`, pure-Python ONNX, no native compile, tiny footprint.
  Search + semantic embeddings on Raspberry-Pi-class hardware, no `ask()`.

`local_embed_backend = auto` uses e5-small-ko-v2 (it measured strongest); set
`llamacpp` for the 1024-d Harrier if you prefer it. Everything except `ask()`
works with embeddings alone; `ask()` needs a generator — on-device Gemma 4 (add
`lemory[llama]`) or a Gemini key.

**Minimum specs**

| Mode | RAM | Disk | Notes |
|---|---|---|---|
| 1 best local (e5 + Gemma 4 E4B) | **8 GB+ (16 GB nice)** | ~4 GB | embeddings are light; Metal/GPU makes answers snappy. Drop to E2B on 8 GB |
| 2 light local (search-only) | 4 GB | ~250 MB | Raspberry-Pi-class hardware is fine |
| 3 Gemini API | anything | ~0 | needs internet, any machine |

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
a link and never mentions the query's words. On the ~42k-chunk namuwiki corpus
this is hard for every system. The Korean-tuned e5 default lifts Lemory's
zero-LLM 2-hop full-support to 0.477 (from ~0.14 under the old MiniLM), now
ahead of qmd's 0.333 even though qmd runs a full local-LLM pipeline at ~60 s per
query (BENCHMARKS 5e keeps this as a standing open problem). qmd does reach 2-hop
doc-coverage 1.000 — it surfaces the right note in the top-8 — but full-support,
retrieving *every* evidence note, is the harder bar.

Lemory exposes the same two knobs, off by default:

```toml
# lemory.toml
query_expansion = true   # rewrite the query into variants before searching
rerank = true            # LLM-score the top candidates after fusion
```

or per call: `lemory search "..." --expand --rerank`.

**Two honest caveats, both measured.**

First, the model matters enormously, and small local models are not enough.
On a 40-question 2-hop sample over the namuwiki corpus, with a generic small
local model (`qwen2.5:3b`):

| setting | 2-hop full-support | latency |
|---|---|---|
| baseline (0 LLM) | 0.125 | 20 ms |
| + query_expansion | 0.150 | 1.5 s |
| + rerank | 0.100 | 6.5 s |
| + expand + rerank | 0.075 | 7.3 s |

Query expansion gave a small bump; **rerank with a 3B model actively hurt**,
demoting correct chunks with noisy relevance scores. qmd reaches 2-hop
doc-coverage 1.000 because it ships purpose-built expansion and reranker models, not a generic
small LLM. So: try `query_expansion` on a *capable* model for a specific
multi-hop question that comes back empty, leave the generic `rerank` off, and
do not expect a small local model to crack deep multi-hop by itself.

A *dedicated* query-expansion model (measured: qmd's own
`qmd-query-expansion-1.7B`, MIT) roughly doubles the generic gain on 2-hop
(0.125 -> 0.175 vs a generic 3B's 0.150; specialization helps) but it
was trained on an English/tech query distribution and hallucinates on short
Korean queries ("스우 테마곡" -> "big data"), so it is a poor default for a
Korean-first vault. Worth trying, not worth hard-wiring.

**A dedicated reranker is available — but ships off by default, and here is
why.** Set `reranker = true` to reorder the top candidates with a cross-encoder
instead of fusion alone. A cross-encoder can only reorder what retrieval already
surfaced, so it can lift doc@1 but cannot fix a deep-multi-hop recall miss. On a
*strong* embedder it barely earns its keep — measured on KorMapleQA v2 (full
2,067) on top of the e5-small-ko-v2 default:

| reranker | doc@1 | doc@8 | latency |
|---|---|---|---|
| none (default) | 0.628 | 0.889 | ~16 ms/query |
| Qwen3-Reranker-0.6B | 0.605 | 0.892 | ~1.9 s/query |

Qwen3-Reranker actually **hurt** doc@1 (a 0.6B reranker second-guessing an
already-correct top result) for ~90x the query latency. (An earlier fastembed
jina-reranker-v2 path, since retired, bought ~+1 pt doc@8 at ~40x latency.) So
retrieval ships **without** a reranker — the embedder + BM25 + link-graph fusion
already rank well — and `reranker` stays an opt-in precision knob for corpora
where the right note lands in the results but not at #1.

### The local stack, in tiers

Everything above is opt-in on top of a fast, free default. Pick the tier you
want in the dashboard's **Settings › Models** card or `lemory.toml`:

1. **Default embedder (`lemory[local]`, e5-small-ko-v2):** dragonkue's
   Korean-tuned multilingual-e5-small via fastembed (pure-Python ONNX, 384d,
   ~9 ms/embed, no native compile). Measured **hybrid doc@8 0.889** on the full
   KorMapleQA v2 — the strongest local embedder we measured, above the 1024-d
   Harrier (0.853) and the old MiniLM (0.788), and it never lost to Harrier on
   the English or long-doc corpora tested. `local_embed_backend = auto` picks it.
2. **Optional 1024-d embedder (`lemory[llama]`, Harrier-OSS-0.6B):** in-process
   llama.cpp (Metal/GPU), doc@8 0.853. It measured *below* e5-small-ko-v2 here
   and is heavier (~640 MB GGUF, ~100 ms/query vs ~9 ms) — kept as an option
   (`local_embed_backend = "llamacpp"`) for those who want the larger dimension,
   but it is no longer the default.
3. **Precision mode (+ dedicated reranker), off by default:** `reranker = true`
   reorders the top candidates with a cross-encoder. Measured on the strong
   local embedders it barely helps or even hurts, at a large latency cost (table
   above), so it ships **off** — reach for it only on a corpus where the right
   note lands in the results but not at #1.
4. **Grounded answers (+ Gemma 4, on-device):** the same `lemory[llama]` engine
   runs **Gemma 4 E4B** (Q4_K_M GGUF) so `lemory ask` and the web console answer
   fully offline. Switch to the lighter **E2B** in the console. Retrieval never
   needs it; only `ask` does.

Second, when you do run an LLM, run it **on-device, not the free-tier API**. The
slowness of an LLM pipeline is almost never the model, it is the API queue
(we hit the exact `429 credits depleted` wall measuring this). Gemma 4 on
llama.cpp Metal answers with no per-query bill and no queue — it's what `lemory
up` sets up by default on-device.

## Big vaults

- Benchmarked on **1,469 real namuwiki documents (~42,000 chunks, 24,850 real
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
| `No API key found` | set `GEMINI_API_KEY` — `lemory up --key <KEY>` does it for you |
| 429 / brief stalls | free-tier limit; Lemory waits and retries. Not a charge |
| Odd results | `lemory index --full`; still odd → open an issue |
| Console won't open | is `lemory serve` running? port 8377 free? |

## Next steps

- **Inside Obsidian**: copy the 3 files from `obsidian-plugin/` into
  `<vault>/.obsidian/plugins/lemory/`, enable in Community plugins
- **Claude Code / Claude Desktop**: `claude mcp add lemory -- lemory mcp --vault <vault>`
- **The receipts**: [BENCHMARKS.md](../BENCHMARKS.md) — every number reproduces
