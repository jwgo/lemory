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
(**1** ⭐ best local — fully on-device on one llama.cpp engine: Harrier
embeddings + Qwen3-Reranker + Gemma 4 answers · **2** light local, search-only ·
**3** Gemini free API),
health-checks the connection, and runs the first index. Then:

```bash
lemory ask "what did we decide in last week's meeting?"
```

## 4. How to use it — set up once, then keep using it

The mental model is simple: **Lemory is a local backend that stays running**,
and everything else (the Obsidian plugin, Claude/MCP, the web UI, the CLI)
talks to it.

**1. Once (setup)**
```bash
lemory up ~/Obsidian/MyVault      # config + first index + serve, in one go
```
Search works with no key at all (local embeddings). Want AI answers (`ask`)?
run `lemory setup` and pick **best local** (on-device Gemma 4, no key) or a
Gemini key.

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
Linux/Windows, CPU offload otherwise), the way qmd uses node-llama-cpp. Pick a
number in `lemory setup`:

**Mode 1 — ⭐ best local (recommended): even answers run offline**

The whole stack on-device, keyless. `lemory setup` → `1` offers to
`pip install "lemory[llama]"` for you; the three GGUFs auto-download once.

- Embeddings: **Harrier-OSS-0.6B** (Q8 GGUF, ~640 MB, 1024d, Qwen3-based
  multilingual). Measured hybrid **doc@8 0.853** on KorMapleQA.
- Reranker: **Qwen3-Reranker-0.6B** (2025 SOTA small reranker, GGUF), scored by
  its `P("yes")` method on GPU — on by default in this mode.
- Answers: **Gemma 4 E4B** (Q4_K_M GGUF, Google's recommended size), streamed.
  Switch to the lighter **E2B** in the web console.
- All three run on the same llama.cpp GPU engine. Not a byte of your vault ever
  leaves the machine.

**Mode 2 — light local (search-only): smallest footprint**

- **e5-small-ko-v2 (default): `pip install "lemory[local]"`** — dragonkue's
  Korean-tuned multilingual-e5-small via fastembed (pure-Python ONNX, 384d,
  ~9 ms/embed). No native compile, tiny footprint, yet **far stronger on Korean
  than the old MiniLM default** — measured dense doc@8 0.86 vs 0.14 on a
  KorMapleQA subcorpus. The right pick if `lemory[llama]` won't build on your
  box, or on Raspberry-Pi-class hardware. Search + semantic embeddings, no `ask()`.

`local_embed_backend = auto` uses Harrier when `lemory[llama]` is installed, else
e5-small-ko-v2. Everything except `ask()` works with embeddings alone; `ask()`
needs a generator — on-device Gemma 4 (best local) or a Gemini key.

**Minimum specs**

| Mode | RAM | Disk | Notes |
|---|---|---|---|
| 1 best local (Harrier + Gemma 4 E4B) | **8 GB+ (16 GB nice)** | ~4.5 GB | CPU works; Metal/GPU makes answers snappy. Drop to E2B on 8 GB |
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
On a 40-question 2-hop sample over the namuwiki corpus, with a generic small
local model (`qwen2.5:3b`):

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
**Qwen3-Reranker-0.6B** (2025 SOTA small reranker) on the same llama.cpp engine,
by its official `P("yes")` relevance method on GPU, instead of asking a chat
model to grade itself.

A cross-encoder can only reorder what retrieval already surfaced: it lifts the
right retrieved note toward the top (doc@1) but leaves doc@8 unchanged, and it
does **not** help deep multi-hop, whose failure is recall (the answer note never
entered the candidate set), not ranking — a reranker cannot surface what
retrieval missed. So it is on by default in best-local setup, and pays off most
when the right note is *in* the results but not at #1.

### The local stack, in tiers

Everything above is opt-in on top of a fast, free default. Pick the tier you
want in `lemory setup` or `lemory.toml`:

1. **Best local, no daemon (`lemory[llama]`, Harrier-OSS-0.6B):** in-process
   llama.cpp (Metal/GPU), the same runtime qmd uses. Hybrid **doc@8 0.853**,
   closing over half the gap to the Gemini ceiling (0.906) with zero keys and
   no server to run. Gains land on the hard types (masked +11, 2-hop
   full-support 0.18 to 0.29, typo +7). Costs: a native wheel (compiles if no
   prebuilt), ~640 MB GGUF (auto-downloaded once), and query latency ~100 ms vs
   the light tier's ~9 ms. `pip install "lemory[llama]"`.
2. **Lightest local (`lemory[local]`, e5-small-ko-v2):** dragonkue's Korean-tuned
   multilingual-e5-small via fastembed (pure-Python ONNX, 384d, ~9 ms/embed), no
   native compile. Measured dense doc@8 **0.86 vs the old MiniLM's 0.14** on a
   KorMapleQA subcorpus — a big Korean jump for zero extra weight. The fallback
   when the llama wheel won't build, or when index speed matters more than the
   last few hybrid points.
3. **Precision mode (+ dedicated reranker):** `reranker = true` reorders the top
   candidates with **Qwen3-Reranker-0.6B** on the same llama.cpp engine (GPU, no
   daemon). ~57 ms/candidate on Metal (≈0.7 s for the default top-12) — on by
   default in best-local setup, worth it when the right note is *in* the results
   but not at #1.
4. **Grounded answers (+ Gemma 4, on-device):** the same `lemory[llama]` engine
   runs **Gemma 4 E4B** (Q4_K_M GGUF) so `lemory ask` and the web console answer
   fully offline. Switch to the lighter **E2B** in the console. Retrieval never
   needs it; only `ask` does.

Second, when you do run an LLM, run it **on-device, not the free-tier API**. The
slowness of an LLM pipeline is almost never the model, it is the API queue
(we hit the exact `429 credits depleted` wall measuring this). Gemma 4 on
llama.cpp Metal answers with no per-query bill and no queue. Point Lemory at it
with `lemory setup` → best local.

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
