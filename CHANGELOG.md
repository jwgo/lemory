# Changelog

All notable changes to Lemory. Dates are the merge date of the release.

## 0.3.0 · Stronger local embeddings (Harrier), dedicated reranker, KorMapleQA v2

### Local embeddings

- **In-process Harrier-OSS-0.6B is the new default local embedder**
  (`pip install "lemory[llama]"`). Microsoft's Qwen3-based multilingual
  embedder (Q8 GGUF) runs inside the process via llama.cpp on Metal/GPU, no
  daemon, the same runtime qmd uses. Measured hybrid **doc@8 0.853 on
  KorMapleQA vs fastembed MiniLM's 0.788** (+6.5pt), closing over half the gap
  to the Gemini ceiling (0.906) with zero keys. The GGUF auto-downloads from
  HuggingFace once. `local_embed_backend = "auto"` falls back to fastembed
  MiniLM (0.788, pure-Python, no native compile) when llama-cpp-python is not
  installed; `provider = "ollama"` runs the identical GGUF via a shared daemon.
- The same Harrier GGUF is the Ollama embed default too
  (`hf.co/mradermacher/harrier-oss-v1-0.6b-GGUF:Q8_0`), resolvable by a plain
  `ollama pull`.

### Retrieval quality

- **Dedicated cross-encoder reranker** (`reranker = true`): Qwen3-Reranker
  scores fused candidates instead of a chat model grading itself. +6.7pt
  recall@1 on hard single/masked questions (it reorders, so it cannot fix a
  deep-multi-hop recall miss). Off by default; seconds per query.

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
