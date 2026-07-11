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

## 3. Run the setup wizard

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
- Embeddings: **Qwen3-Embedding-0.6B** (~640 MB, 1024d, strong KR/EN)
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
