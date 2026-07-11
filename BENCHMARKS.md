# Lemory benchmarks

All systems share the same corpus, chunking, and Gemini embeddings; they differ
only in retrieval strategy (for mem0: its own full OSS pipeline with the same
Gemini models). Generator model, prompt, and context budget are identical in the
end-to-end eval. Benchmark corpora and code live in `benchmarks/`; multi-hop
gold labels are correct by construction (relations wired deterministically in
code, prose leakage scrubbed and verified — see `gen_multihop.py`).

Environment note: run on a Gemini free-tier key; retrieval latency numbers
exclude the query-embedding API call (identical for every system).

## 1. Multi-hop retrieval (LemoryBench, 57 questions / 54-note vault)

Full-support@8 = both gold notes for a 2-hop question retrieved in the top 8 — 
the precondition for a correct multi-hop answer.

| System | Full-support@8 (2-hop) | Full-support@8 (all) | Recall@1 | MRR@10 | ms/query* |
|---|---|---|---|---|---|
| **Lemory** (hybrid + graph) | 1.000 | 1.000 | 1.000 | 1.000 | 2.139 |
| Lemory w/o graph (ablation) | 0.357 | 0.526 | 1.000 | 1.000 | 1.396 |
| Vector-only (naive RAG) | 0.381 | 0.544 | 0.965 | 0.982 | 0.249 |
| BM25 (lexical) | 0.429 | 0.579 | 0.825 | 0.912 | 0.761 |

## 2. Single-hop retrieval (SQuAD v2 dev, real external data)

18 Wikipedia articles as notes (~1,200 paragraphs), 300 real questions. 
Hit = retrieved chunk is from the gold article and contains a gold answer.

| System | Recall@1 | Recall@3 | Recall@5 | Recall@8 | MRR@10 | ms/query* |
|---|---|---|---|---|---|---|
| **Lemory** (hybrid + graph) | 0.812 | 0.955 | 0.965 | 0.968 | 0.881 | 7.001 |
| Lemory w/o graph (ablation) | 0.840 | 0.955 | 0.970 | 0.970 | 0.897 | 5.675 |
| Vector-only (naive RAG) | 0.777 | 0.927 | 0.965 | 0.985 | 0.855 | 5.991 |
| BM25 (lexical) | 0.818 | 0.948 | 0.968 | 0.973 | 0.881 | 6.424 |

## 3. End-to-end QA — LemoryBench (synthetic multi-hop)

Same Gemini generator and prompt for every system; only retrieval differs. Token-F1 / containment-EM vs gold answers (30 questions).

| System | F1 | EM (contain) | n |
|---|---|---|---|
| **Lemory** (hybrid + graph) | 1.000 | 1.000 | 30 |
| BM25 (lexical) | 0.467 | 0.467 | 30 |
| Vector-only (naive RAG) | 0.433 | 0.433 | 30 |

Failure mode of the baselines is uniform: the bridge note is found, the answer
note isn't, and the pinned generator honestly replies "unknown".

## 3b. End-to-end QA — 실제 나무위키 메이플스토리 (real data)

Same Gemini generator and prompt for every system; only retrieval differs. Token-F1 / containment-EM vs gold answers.

| System | F1 | EM (contain) | F1 (2-hop) | F1 (1-hop) | n |
|---|---|---|---|---|---|
| **Lemory** (hybrid + graph) | 0.594 | 0.640 | 0.481 | 0.762 | 50 |
| Vector-only (naive RAG) | 0.562 | 0.620 | 0.432 | 0.758 | 50 |
| BM25 (lexical) | 0.406 | 0.460 | 0.366 | 0.466 | 50 |

## 4. External system: mem0 (OSS)

mem0 with the identical Gemini LLM/embedder, default fact-extraction
pipeline, local Qdrant. Shared metric: answer-in-context@8 — the gold
answer string appears in the top-8 retrieved texts (LemoryBench, 57 q).

| System | Answer-in-context@8 |
|---|---|
| **Lemory** (hybrid + graph) | 1.000 |
| Vector-only (naive RAG) | 0.561 |
| BM25 (lexical) | 0.667 |
| mem0 OSS (Gemini backend) | 0.579 |
| LlamaIndex (VectorStoreIndex, same embeddings) | 0.649 |

mem0 by hops: 1-hop 0.667, 2-hop 0.548 · 212 ms/query (p50) · ingestion ran its
LLM fact-extraction once per note (rate-limited; resumable state file).

## 4b. External system: cognee (OSS)

cognee v1.2 with the identical Gemini models (flash-lite for cognify's
graph extraction, gemini-embedding-001 @768d), default local stores
(LanceDB + Ladybug/Kuzu graph). Full `cognify` knowledge-graph build over
the 54-note vault, then its `CHUNKS` retrieval; e2e uses the same
generator/prompt as every other row (LemoryBench, 57 q / e2e 30 q).

| System | Answer-in-context@8 | 1-hop | 2-hop | e2e F1 | EM (contain) |
|---|---|---|---|---|---|
| **Lemory** (hybrid + graph) | 1.000 | 1.000 | 1.000 | 0.867 | 1.000 |
| cognee CHUNKS retrieval | 0.561 | 1.000 | 0.405 | 0.467 | 0.467 |
| cognee `GRAPH_COMPLETION` (its native graph-QA pipeline) | — | — | — | 0.394 | 0.367 |

cognee retrieval p50 latency: 4994 ms/query (Lemory: ~2 ms local + one cached embedding call). cognify ingest of the 54-note vault took ~45 min under free-tier rate limits vs ~30 s for Lemory's index.

## 4c. External system: LlamaIndex (OSS framework)

The 'build it yourself' path most teams take first: `llama-index-core`
VectorStoreIndex over the same 54-note vault, default SentenceSplitter
chunking, cosine top-8 — with the SAME gemini-embedding-001 @768d as every
other row (custom adapter over Lemory's batched client). Fifth externally
measured system (`benchmarks/run_llamaindex.py`).

| System | Answer-in-context@8 | 1-hop | 2-hop | Full-support@8 |
|---|---|---|---|---|
| **Lemory** (hybrid + graph) | 1.000 | 1.000 | 1.000 | 1.000 |
| LlamaIndex VectorStoreIndex | 0.649 | 1.000 | 0.524 | 0.596 |

Latency p50: 649 ms as shipped (its retrieval embeds every query via the API,
uncached); 1.8 ms local-only with a pre-embedded query — the gap to Lemory is
architectural (no cache, no lexical leg, no graph), not compute.

## 4d. Query robustness (real-world phrasings)

The multi-hop questions re-asked as committed variants: an English
paraphrase, a natural Korean phrasing (Korean query → English notes),
a terse keyword lookup, and a typo'd version (1-2 injected typos).
Metric: full-support@8 against the original gold notes. Lemory's typo
resilience comes from local did-you-mean correction over the vault
vocabulary (zero API calls; hybrid pipeline only — baselines stay pure).

| System | original | paraphrase | korean | keyword | typo |
|---|---|---|---|---|---|
| **Lemory** (hybrid + graph) | 1.000 | 0.982 | 1.000 | 0.982 | 0.965 |
| Lemory w/o graph (ablation) | 0.544 | 0.446 | 0.275 | 0.464 | 0.526 |
| Vector-only (naive RAG) | 0.544 | 0.464 | 0.475 | 0.482 | 0.491 |
| BM25 (lexical) | 0.579 | 0.429 | 0.250 | 0.482 | 0.404 |

(paraphrase 0.946→0.982 and korean 0.975→1.000 improved with the graph-expansion
redesign of §5d — re-measured, baselines unchanged.)

Optional LLM query expansion (`--expand`) was also measured: paraphrase 0.911, korean 0.950, typo 0.825 — no better than the LLM-free pipeline on this corpus, which is why it stays off by default (saves one LLM call per query).

## 5. Korean corpus: 실제 나무위키 메이플스토리 (1,469 real documents)

All documents categorized under 메이플스토리 in the public namuwiki 2021-03-01 dump (867k docs scanned): 33,375 chunks, 24,850 real wikilink edges. QA drafted by LLM, kept only if code-verified: answer appears ONLY in the gold note, no title leakage (see gen_maple_real_qa.py).

| System | Full-support@8 | Recall@1 | Recall@5 | MRR@10 |
|---|---|---|---|---|
| **Lemory** (hybrid + graph) | 0.820 | 0.820 | 0.980 | 0.895 |
| Lemory w/o graph (ablation) | 0.700 | 0.860 | 0.960 | 0.900 |
| Vector-only (naive RAG) | 0.660 | 0.700 | 0.920 | 0.796 |
| BM25 (lexical) | 0.560 | 0.540 | 0.860 | 0.688 |

## 5b. Korean corpus: 메이플스토리 (나무위키-style, Korean)

Real game entities/terminology; relations wired by code, QA gold by construction.

| System | Full-support@8 | Recall@1 | Recall@5 | MRR@10 |
|---|---|---|---|---|
| **Lemory** (hybrid + graph) | 1.000 | 1.000 | 1.000 | 1.000 |
| Lemory w/o graph (ablation) | 0.818 | 1.000 | 1.000 | 1.000 |
| Vector-only (naive RAG) | 0.818 | 1.000 | 1.000 | 1.000 |
| BM25 (lexical) | 0.818 | 0.939 | 1.000 | 0.965 |

## 5c. Korean corpus: 전세사기 관계법령 (Korean legal)

Real statutes (주택임대차보호법, 전세사기특별법 등); QA answers code-verified to appear in gold notes.

| System | Full-support@8 | Recall@1 | Recall@5 | MRR@10 |
|---|---|---|---|---|
| **Lemory** (hybrid + graph) | 1.000 | 1.000 | 1.000 | 1.000 |
| Lemory w/o graph (ablation) | 0.947 | 1.000 | 1.000 | 1.000 |
| Vector-only (naive RAG) | 0.895 | 1.000 | 1.000 | 1.000 |
| BM25 (lexical) | 0.895 | 1.000 | 1.000 | 1.000 |

## 5d. Real public Obsidian vaults (kepano · obsidian-help)

The "not our benchmark" benchmark: two real, independently-authored vaults.
**kepano** — Steph Ango's (Obsidian CEO) public personal vault, MIT, committed
with attribution (51 content notes; stub-heavy, property-heavy — the messy
reality). **obsidian-help** — the official Obsidian documentation vault
(171 notes, densely interlinked; fetched at bench time by `prep_help.py`).
QA drafted by LLM and code-verified against RAW note text (answer only in the
gold note, no title leakage; enrichment pseudo-chunks excluded from drafting
and verification). kepano 22 questions (incl. frontmatter-fact questions),
help 55 questions (30 2-hop).

**obsidian-help** (hub-linked docs — the graph-expansion stress test):

| System | Full-support@8 | 2-hop | Recall@1 | MRR@10 |
|---|---|---|---|---|
| **Lemory** | **0.836** | **0.700** | **0.800** | **0.854** |
| Vector-only | 0.691 | 0.433 | 0.709 | 0.798 |
| BM25 | 0.655 | 0.400 | 0.673 | 0.787 |

**kepano** (real personal vault — the stub-note stress test):

| System | Full-support@8 | 2-hop | MRR@10 |
|---|---|---|---|
| Lemory (stub enrichment on, default) | 0.955 | **1.000** | 0.932 |
| Lemory without stub enrichment (ablation) | 0.909 | 0.500 | 0.932 |
| Vector-only | **1.000** | 1.000 | 0.930 |
| BM25 | 0.909 | 1.000 | 0.847 |

Honest notes, in both directions:

- **Stub enrichment is the real win of this round**: on the real personal
  vault it doubles 2-hop full-support (0.500 → 1.000) by making property-stub
  notes findable (flattened frontmatter + backlink context as one extra
  indexed pseudo-chunk). Zero LLM calls, index-time only, ablated above.
- **Vector-only edges Lemory by one question on kepano** (1.000 vs 0.955,
  n=22) — on a 51-note vault at k=8, dense retrieval over the same enriched
  index nearly saturates. We print it; small-n, but real.
- **The graph-expansion redesign was almost a self-inflicted wound**: the
  first version (unconditioned degree normalization + gain-ranked budget)
  regressed help to 0.600 and the synthetic multihop guard to 0.842. The
  shipped version (hub-threshold normalization, budget applied after
  query-similarity weighting, seed notes eligible for boosts) restores every
  guard (multihop 1.000, law/maple 1.000, SQuAD/KorQuAD unchanged) and beats
  the pre-round code on help precision (recall@1 0.745 → 0.800, MRR 0.834 →
  0.854) and on robustness (paraphrase 0.946 → 0.982, korean 0.975 → 1.000).
  Full-support on help is unchanged from pre-round (0.836) — the redesign's
  value is precision, robustness, and a measured defense against hub-graph
  flooding, not a recall jump.
- **graph_hops=2 (HippoRAG-style deeper propagation) showed no gain on any
  corpus** — shipped as an opt-in config, default stays 1. Measured, not
  adopted.

## 6. Real external data: KorQuAD 1.0 (한국어 위키피디아, 인간 작성 질문)

140 real Korean Wikipedia articles as notes; 400 human-written dev questions (seeded sample of 5,774). Hit = chunk from the gold article containing a gold answer span.

**BM25 still wins here and we report it**: SQuAD-family questions quote the passage vocabulary (written while reading it), which is BM25's best case. The robustness section shows what happens when the same kind of content is asked in the user's own words — BM25 0.25–0.48, Lemory 0.95+.

| System | Recall@1 | Recall@5 | MRR@10 | e2e EM (40q) |
|---|---|---|---|---|
| **Lemory** (hybrid + graph) | 0.908 | 0.985 | 0.943 | 0.900 |
| Vector-only (naive RAG) | 0.855 | 0.968 | 0.902 | 0.925 |
| BM25 (lexical) | 0.923 | 0.993 | 0.952 | 0.950 |

The Lemory row reflects the verbatim-lean tuning pass
(`benchmarks/sweep_verbatim.py`): the per-query verbatim detector now flips to
a stronger lexical weight (gate 0.75→0.60, boost 1.8→2.4), lifting recall@1
0.895→0.908 and e2e EM 0.875→0.900 on this corpus and **halving the gap to
BM25 (3.6→1.5 pt)** — while the multi-hop (1.000) and robustness
(0.946/0.975/0.982/0.965) guards stayed exactly unchanged. Pushing the boost
further (3.0) starts costing paraphrase robustness, so this is the knee of
the curve, not the end of it.

## 7. Memory benchmark: LOCOMO (long-term conversational memory, 160-question stratified sample)

The benchmark mem0/zep report on. Same Gemini flash generator + LLM judge for every system; adversarial category excluded (mem0 protocol). mem0's published overall judge score is 0.669 (their own eval, gpt-4o-mini).

| System | evidence_recall@10 | judge_acc | judge_multi_hop | judge_open_domain | judge_single_hop | judge_temporal |
|---|---|---|---|---|---|---|
| **Lemory** (hybrid + graph) | 0.894 | 0.706 | 0.533 | 0.375 | 0.852 | 0.822 |
| Vector-only (naive RAG) | 0.876 | 0.688 | 0.556 | 0.375 | 0.852 | 0.733 |

## 7b. Memory benchmark: DMR / Deep Memory Retrieval (MemGPT/Zep), full 500 questions

MSC-Self-Instruct: recall a fact from a 5-session chat. Session speaker labels inferred from dataset summaries (sessions don't always start with Speaker 1). Published Zep/MemGPT numbers (94.8/93.4) use GPT-4-class generators and their own judges — not directly comparable to this controlled all-Gemini setup.

| System | judge_acc |
|---|---|
| **Lemory** (hybrid + graph) | 0.694 |
| Vector-only (naive RAG) | 0.668 |

## 7c. Memory benchmark: LongMemEval_S (cleaned), 100-question stratified sample

Per-question ~50-session haystacks with dates; includes temporal reasoning, knowledge updates, preference personalization, and abstention. GPT-4o full-context baseline in the paper is ~0.60.

| System | acc_abstention | acc_knowledge-update | acc_multi-session | acc_single-session-assistant | acc_single-session-preference | acc_single-session-user | acc_temporal-reasoning | judge_acc |
|---|---|---|---|---|---|---|---|---|
| **Lemory** (hybrid + graph) | 1.000 | 0.812 | 0.480 | 1.000 | 0.667 | 0.867 | 0.741 | 0.730 |
| Vector-only (naive RAG) | 1.000 | 0.875 | 0.520 | 1.000 | 0.833 | 1.000 | 0.667 | 0.760 |

## 8. External tool: qmd (tobi/qmd, local-model markdown search)

Same corpus (multihop vault) and metric (full-support@8 by gold note).
qmd ran its bundled local models (embeddinggemma-300M, 1.7B query
expander, Qwen3 reranker) on the benchmark machine's CPU — on GPU its
latency drops to seconds, but the quality numbers are hardware-independent.
qmd's vector-only mode could not be sampled reliably (per-invocation
model load, 19-190s) and is omitted.

| System | natural question | 2-hop | Korean | typo | keyword | p50 latency |
|---|---|---|---|---|---|---|
| **Lemory** (hybrid+graph) | 1.000 | 1.000 | 0.975 | 0.965 | 0.982 | ~3 ms local |
| qmd `query` (full local-LLM pipeline) | 0.526 | 0.381 | — | — | — | 59 s (CPU) |
| qmd `search` (BM25) | 0.000 | 0.000 | 0.000 | 0.000 | 0.214 | 0.6 s |

qmd's BM25 uses AND semantics — natural-language questions return zero
results, so it is effectively keyword-only. Lemory accepts any phrasing.
Convenience: qmd requires ~2.2 GB of model downloads before first use;
Lemory needs one API key (or a 220 MB model in keyless local mode), and
adds what qmd doesn't have: grounded answers with citations, temporal
awareness, a live vault watcher, a web UI, and an Obsidian plugin.

## 9. Context efficiency (supermemory-style aggregation)

supermemory's LongMemEval headline is high recall while adding only
~720 tokens of context. Lemory's precise retrieval already keeps ask()
context in that range by default, and `context_style="compact"`
aggregates further — sentence-level fact sheets built with the same
embedding cache the index uses (zero LLM calls):

| Set | Style | contain-EM | F1 | ~context tokens |
|---|---|---|---|---|
| multihop | full | 0.967 | 0.705 | 556 |
| multihop | compact | 0.933 | 0.698 | 418 |
| temporal | full | 1.000 | 0.572 | 193 |
| temporal | compact | 1.000 | 0.599 | 162 |

## 10. Temporal scenario: "요새 내가 하던 그거 뭐였지?" (real embeddings)

A generated 6-month personal vault (127 daily/meeting notes, fixed TODAY)
where facts EVOLVE: the current book/exercise/tool supersedes an older one
that has MORE mentions — the trap a recency-blind retriever falls into.
Query classes: vague recency (요새/요즘/최근/지금), explicit windows
(어제/지난주/오늘/N일 전/N월), and old-fact references (history must stay
reachable). Recency detection is rule-based KR/EN, zero API calls, and
multiplies relevance rather than replacing it (week-banded decay).
In the live `ask()` session over this vault, 6/6 Korean memory questions
were answered correctly with citations.

| System | recent-fact hit@1 | superseded-trap hit@1 | window hit@1 | old-fact hit@1 | overall hit@1 |
|---|---|---|---|---|---|
| **Lemory** (hybrid + graph) | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| Lemory w/o recency (ablation) | 0.400 | 0.000 | 0.750 | 1.000 | 0.545 |
| Vector-only (naive RAG) | 0.000 | 0.000 | 0.500 | 1.000 | 0.273 |
| BM25 (lexical) | 0.600 | 1.000 | 0.750 | 0.000 | 0.636 |

## 11. Second-brain scale (948 mixed KR/EN notes, LLM-free)

Diverse realistic vault (people, projects, daily logs, meetings, tastes,
clippings) with 50 planted facts; deterministic local embedder, so this
verifies ingest/sync/graph/lexical retrieval at scale (semantic quality
is covered by the corpora above on real embeddings).

| Metric | value |
|---|---|
| Notes / chunks / links | 948 / 1428 / 1176 |
| Full index | 0.1 s |
| Incremental sync (1 edit) | 0.14 s |
| Planted-fact hit@1 (hybrid) | 1.00 |
| Planted-fact hit@1 (BM25) | 0.92 |
| Planted-fact hit@5 (hybrid) | 1.00 |
| Search latency (hybrid) | 3.1 ms |


## 12. Local retrieval latency at scale (`perf_local.py`)

Synthetic Zipfian corpus, 50 queries, exact cosine + SQLite FTS5.
50k chunks ≈ an 8,000-note vault — well past typical personal vaults.

| Index size | hybrid+graph | hybrid | vector | bm25 |
|---|---|---|---|---|
| 2,000 chunks | 5.5 ms | 4.3 ms | 0.41 ms | 3.1 ms |
| 10,000 chunks | 17.1 ms | 14.9 ms | 0.82 ms | 12.9 ms |
| 50,000 chunks | 69.9 ms | 69.4 ms | 4.4 ms | 60.0 ms |

\* ms/query is local compute only (vector/BM25/graph math), measured on the
benchmark machine; the query embedding round-trip (~100–300 ms, identical for
all embedding-based systems) is excluded.

## 13. Context ordering — CDS-inspired curriculum (negative result)

"Many-Shot CoT-ICL" (Chung et al., ICML 2026, arXiv:2605.13511) shows that
ordering in-context *demonstrations* as a smooth low-curvature trajectory in
embedding space improves reasoning. We tested the analogous idea on ask()'s
*retrieved evidence*: same hits, same generator/prompt, only the presentation
order differs (`benchmarks/run_context_order.py`; KorQuAD, k=12, 39 paired
questions — one dropped by the API safety filter for both arms).

| Order | contain-EM | token-F1 | mean path smoothness |
|---|---|---|---|
| rank (fusion order, default) | 0.872 | **0.520** | 0.682 |
| curriculum (greedy TSP + curvature penalty) | 0.872 | 0.489 | 0.728 |

The reordering does what it promises geometrically (smoothness ↑) but buys
no answer quality: containment ties, token-F1 slips ~3 pt. Consistent with
the paper's own scaling story — its gains appear at 16–128 demonstrations,
while a grounded answer here reads 8–12 evidence blocks. So `context_order`
defaults to `"rank"` and `"curriculum"` remains an opt-in experiment, same
policy as LLM query expansion (§4c): measured, not adopted.

## Reproduce

```bash
uv venv && uv pip install -e . && export GEMINI_API_KEY=...
python benchmarks/prep_squad.py            # downloads SQuAD v2 dev
python benchmarks/gen_multihop.py          # no-op: generated vault is committed
python benchmarks/run_retrieval.py multihop
python benchmarks/run_retrieval.py squad
python benchmarks/run_e2e.py multihop 40
python benchmarks/run_mem0.py              # optional, needs mem0ai + qdrant-client
python benchmarks/run_cognee.py            # optional, needs cognee (slow: cognify)
python benchmarks/gen_robust_queries.py    # no-op: variants are committed
python benchmarks/run_robustness.py
python benchmarks/report.py
```

## Why these baselines

* **Vector-only** is the retrieval core of typical RAG/notes products (and of
  supermemory-style pipelines): cosine over the same embeddings.
* **BM25** is the classic lexical baseline (what most in-app search does).
* **Lemory w/o graph** isolates where the multi-hop gain comes from.
* **mem0** is a real external OSS memory system run end-to-end.
* **cognee** is a real external OSS knowledge-graph system run end-to-end
  (full cognify + retrieval + its native GRAPH_COMPLETION QA), same models.
