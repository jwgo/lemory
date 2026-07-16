# Changelog

All notable changes to Lemory. Dates are the merge date of the release.

## Unreleased · the memory loop closes: auto-remember, distill, messy-chat bench

**A conversation is now a memory without anyone doing anything.**

- **Session auto-save (write half of the loop):** every console-assistant
  conversation persists as a dated session note in `chats/` - a plain,
  visible, editable Markdown file. Toggle: `assistant_log_sessions`
  (console: 답변 생성 › 비서 대화 기억). The skill teaches external
  assistants the same policy via `lemory remember`.
- **`lemory distill` (opt-in):** chat sessions → fact-sheet notes
  (기억요약/) with [[wikilink]] provenance, on-device Gemma, retraction-
  aware. Measured honestly on the messy bench: +3.1pt answer-presence at
  rank 1, mixed elsewhere - profile in BENCHMARKS §7e; stays opt-in.
- **RoleMemQA-messy:** retractions, joke-fakes, and vocabulary-poisoning
  small talk, all code-verified. Keyless hybrid: retraction recall 1.000
  (zero stale traps), overall doc@1 0.820 vs 0.984 clean - the honest cost
  of noise, and the target the loop features are measured against.
- New demo: `demo4_memoryloop.gif` - day-1 fact, day-30 recall in 4ms with
  citation, replayed from real pipeline output.

## Unreleased · roleplay memory, exact-recall vectors, linear mention pass

**Lemory measured as a roleplay long/short-term memory store, and two silent
recall taxes removed.**

- **RoleMemQA (new benchmark, §7e):** 8 personas × 30 dated chat sessions,
  144 code-verified questions over 7 memory types (short/long/episodic/
  preference-update/temporal/2-hop/abstention). Keyless hybrid **doc@1 0.984**
  (update-type 1.000 with zero stale-preference traps), above its own vector
  (0.938) and BM25 (0.820) legs; opt-in reranker 0.992.
- **Memory-timeline recency:** vague-recency queries ("요즘 ...") now anchor at
  the vault's newest note instead of the wall clock, and the verbatim-pin
  choice is recency-weighted - an archival or resumed chat vault keeps its
  internal order (RoleMemQA update doc@1 0.625 → 1.000).
- **Boilerplate-aware fusion:** when every query content token is
  corpus-common (chat greetings/reactions), the verbatim machinery abstains
  and BM25 is damped in fusion (`common_bm25_damp`, vector leg required).
- **Exact-recall vectors by default up to 60k chunks:** IVF at the old 20k
  threshold silently cost -4.5 pt vector doc@8 at 42k chunks (0.900 vs 0.945
  exact) and varied between builds. `ann_threshold` 20k → 60k, `ann_nprobe`
  48 → 256 past it. KorMapleQA doc@8 **0.889 → 0.899**, doc@1 0.628 → 0.641
  (masked +6.5 pt); the honest cost is ~0.11 s/query at 42k chunks.
- **Linear mention detection:** unlinked-mention scanning replaced the
  per-title regex loop (O(text × titles) - hours at 57k docs) with a
  pure-Python Aho-Corasick automaton with identical word-boundary semantics
  (~24 s for the same corpus). BEIR-scale ingests no longer appear to hang.
- **Dated daily notes get the title boost:** numeric date-stamp tokens no
  longer veto title-boost coverage ("2023-09-12 Meeting with Steph").
- LOCOMO gains a key-free retrieval table (§7, hybrid 0.771 evidence-recall);
  BEIR §4i and the qmd-329 rematch re-measured under the exact regime
  (rematch 0.875 → 0.887 vs qmd's 0.769).

## 0.3.0 · Korean-tuned e5 default (0.889 doc@8), one-command setup, on-device Gemma, no Ollama

**Better retrieval, simpler stack, one way in.** The keyless local default is now a
Korean-tuned e5 embedder that measures **hybrid doc@8 0.889 on KorMapleQA** -
above the old MiniLM default (0.788) and the llama.cpp Harrier tier
(0.853), second only to the Gemini config (0.906). Onboarding collapsed to a
single command (`lemory up`). On-device answers moved to
Gemma 4 on llama.cpp (GPU everywhere: Metal / CUDA / Vulkan / CPU offload), now
selectable in the web dashboard. A dedicated reranker is available but ships
**off** - measured, a small reranker doesn't help a strong embedder (details
below). Ollama and LiteRT-LM are gone.

### Local embeddings

- **The default local embedder is dragonkue's Korean-tuned
  `multilingual-e5-small-ko-v2`** (fastembed, 384d), replacing MiniLM. Registered
  from a community ONNX export so it stays pure-Python and torch-free, ~9 ms/embed,
  no native compile. Measured **hybrid doc@8 0.889 on the full KorMapleQA v2**
  (2,067) - above MiniLM's 0.788 **and the 1024-d Harrier's 0.853**, and it never
  lost to Harrier on the English/long-doc corpora tested. `local_embed_backend =
  "auto"` picks it everywhere.
- **Chunk size tuned to the embedder's window: `chunk_chars` 1400 → 882.**
  882 characters ≈ 512 tokens of Korean (measured 1.70 char/token), exactly the
  e5-small-ko-v2 context window - the largest chunk it encodes in full, so no
  content is truncated before embedding while each chunk stays maximally coherent.
  A full sweep on KorMapleQA (700–2200 chars) showed note-level doc@8 is flat
  within noise across the range (the 1024-token BM25 leg covers whatever the
  vector leg truncates), so we picked the principled point; 1400 happened to sit
  at the sweep's low. e5's Korean re-measurement lifts the local dense leg sharply
  - vector-only doc@8 0.149 → 0.863, masked-entity 0.461 → 0.777, 2-hop
  full-support 0.141 → 0.477 (now ahead of qmd's 0.333).
- **Harrier-OSS-0.6B is now an option, not the default.** The in-process
  llama.cpp Qwen3-based embedder (doc@8 0.853) measured *below* e5-small-ko-v2 and
  is heavier (~640 MB GGUF, ~100 ms/query), so it is demoted to an explicit
  choice (`local_embed_backend = "llamacpp"`); llama.cpp's job in the best-local
  stack is now the Gemma 4 *answer* model, not embeddings.

### Retrieval quality

- **Dedicated cross-encoder reranker** (`reranker = true`) - available but
  **off by default, and here is the honest reason.** On the full KorMapleQA v2
  over the e5 default (chunk 882): no reranker doc@1 0.628 / doc@8 0.889 (~16 ms/q);
  Qwen3-Reranker-0.6B doc@1 **0.605** (it *hurt* - a 0.6B reranker second-guessing
  an already-correct top result) at ~1.9 s/q. (An earlier fastembed jina-reranker-v2
  path, since retired, bought ~+1 pt doc@8 at ~40x latency.) A strong embedder +
  BM25 + link-graph fusion already ranks well, so retrieval ships without a
  reranker; `reranker` stays an opt-in precision knob.

### On-device answers & assistant

- **Local answers with no key, no daemon.** `lemory ask` and the web console's
  search view answer fully on-device via **Gemma 4** on llama.cpp (Q4_K_M GGUF -
  E4B default, switch to the lighter E2B in the console; `pip install
  "lemory[llama]"`). The answer model shares the engine with the embedder and
  reranker; it runs with an 8192-token context and the RAG prompt is fit to it.
- **Voice assistant mode** in the web console: grounded chat over the vault with
  local STT (faster-whisper) and on-device neural TTS (Supertonic), streamed
  sentence-by-sentence - no cloud round-trip. `pip install "lemory[assistant]"`.
### Onboarding & web console

- **One command to start: `lemory up`.** Onboarding was scattered across three
  overlapping commands - `init` (config only), `setup` (interactive wizard), and
  `up` (auto). Now there is one way: `lemory up` prompts for the vault when run
  bare, `lemory up ~/Vault` runs zero-question for scripts, `--key <KEY>` selects
  Gemini. It auto-detects the best mode and offers to install `lemory[llama]` for
  Gemma answers; the old number-menu is gone. `init`/`setup` remain as hidden
  deprecated aliases that forward to `up`.
- **Pick the answer model in the dashboard.** Settings gained a **Models** card -
  the one place to see and switch the on-device answer LLM (Gemma 4 E4B ⇄ E2B,
  with size/context/GPU shown) and read the resolved embedding and reranker
  identities. Previously the model toggle was buried in the assistant view - and
  silently broken: its switch request omitted the JSON `Content-Type`, so the
  server rejected it with 422. Fixed.

### Removed

- **Ollama is gone entirely.** No server to install, run, or `pull` from - the
  `ollama` provider, the `ollama_*` config keys, and the Ollama setup mode were
  removed.
- **LiteRT-LM dropped for a single llama.cpp engine.** An earlier build ran
  answers on Google's LiteRT-LM; consolidating on llama.cpp gives one GPU
  runtime for embeddings + reranker + answers across Mac/Linux/Windows, and
  retired the fastembed ONNX reranker path too.

### Benchmark

- **KorMapleQA v2**: question phrasing de-monotonized (the share ending in the
  identical `~은 무엇인가?` dropped 72% to 12%, varied by answer type) and the
  seeded typo now lands on the entity rather than the question word. Every
  zero-key system re-measured; ranking and story unchanged (all moved
  <2.5 doc@8 points). Published at github.com/jwgo/KorMapleQA.

## 0.2.0 · Korean-first retrieval, second-brain behaviors, KorMapleQA

### Retrieval quality (Korean)

- **CJK bigram indexing.** The Hangul bigram machinery now also covers kana
  and CJK ideographs, so mixed-script runs (`ナイトロード나이트로드`) and
  JMS/CMS name tables match instead of collapsing into one unmatchable token.
- **Morphology-aware verbatim detection.** IDF-weighted coverage over a
  top-8 BM25 window lets a quoted rare identifier carry the verbatim gate;
  jamo-level stem matching survives conjugation and 띄어쓰기 variation;
  question furniture (`~한 인물은?`) is stripped before scoring.
- **Reciting pin + covering-chunk anchor.** When a query recites a note,
  BM25's own top-3 ordering is preserved and the single best-covering chunk
  is pinned to the top wherever BM25 ranked it (masked-entity identifiers
  often sit at rank 4-8).
- **Syllable-level Korean typo repair.** `메플이스토리` corrects to
  메이플스토리 (Damerau-Levenshtein over syllables); first-syllable typos are
  reached via a second-character index. Corrections apply as spans over the
  original query so they can never corrupt a longer indexed word.
- **Lexical-evidence graph expansion.** A linked neighbor whose chunk already
  ranks in BM25 survives the expansion ceiling and gets the boost, gated by
  the stronger of cosine or BM25 rank.
- KorQuAD 1.0 recall@1 is now 0.940, ahead of pure BM25 (0.928) for the first
  time. Big Korean corpora: the BM25 leg is ~5.6x faster after dropping
  interior query unigrams.

### Second-brain behaviors

- **`save_memory` consolidation.** Every new memory is checked against the
  vault; related notes get `related:` wikilinks and near-duplicates get a
  `possible_duplicate_of:` flag. Links, does not rewrite.
- **`lemory suggest-links`** (+ MCP `suggest_links`): unlinked mentions as
  actionable `[[link]]` proposals with the mention's sentence.
- **`lemory graph`**: the whole vault as one self-contained interactive HTML
  knowledge graph, ~1s for 1,469 notes, zero LLM calls.
- **`lemory skill install claude-code|codex|cursor`**: writes a SKILL.md so
  the assistant treats the vault as long-term memory.
- **`lemory drift`**: broken wikilinks, dead file links, and unresolved
  duplicate flags, with `--prompt` rendering an agent-ready repair prompt.

### Benchmarks

- **KorMapleQA** (`benchmarks/data/kormapleqa/`): a new 2,075-question,
  100%-code-generated, machine-verified Korean RAG benchmark over the real
  namuwiki MapleStory domain (1,469 documents). Seven question types plus
  verified-absent abstention.
- Measured the memory-system field on it: qmd (3 modes), MemPalace, mem0,
  Smart-Connections-class, Omnisearch. On identical questions Lemory ties
  qmd's headline local-LLM mode at ~3,000x the speed and beats mem0 on every
  axis with an embeddings-only ingest.

### Fixes (from a high-effort review of the release diff)

- Korean typo replacement is span-based (no more corrupting a longer word
  that shares a substring).
- `lemory graph` HTML-escapes note-derived strings and splits `</` in the
  inline JSON (a note titled `</script>` can no longer break the export).
- `save_memory` YAML-escapes titles in the frontmatter it writes.
- `lemory skill` rejects unknown actions instead of silently installing.
- The graph sim-floor gates on max(cosine, BM25-rank), so a tail hit can't
  push an unrelated linked note into results.
- Lexical structures are background-warmed at index time on large vaults, so
  the first search doesn't pay a full-vocabulary scan inline.

## 0.1.0 · Initial

Local memory middleware: hybrid retrieval (vector + BM25 + wikilink graph)
on a SQLite + numpy stack, MCP read/write tools, dashboard with the AI
memory feed and undo, keyless / local / Gemini / Ollama modes, IVF-int8 for
million-chunk vaults, and the reproducible benchmark suite in BENCHMARKS.md.
