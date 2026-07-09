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
| **Lemory** (hybrid + graph) | 1.000 | 1.000 | 1.000 | 1.000 | 2.512 |
| Lemory w/o graph (ablation) | 0.381 | 0.544 | 1.000 | 1.000 | 1.750 |
| Vector-only (naive RAG) | 0.381 | 0.544 | 0.965 | 0.982 | 0.436 |
| BM25 (lexical) | 0.429 | 0.579 | 0.825 | 0.912 | 0.817 |

## 2. Single-hop retrieval (SQuAD v2 dev, real external data)

18 Wikipedia articles as notes (~1,200 paragraphs), 300 real questions. 
Hit = retrieved chunk is from the gold article and contains a gold answer.

| System | Recall@1 | Recall@3 | Recall@5 | Recall@8 | MRR@10 | ms/query* |
|---|---|---|---|---|---|---|
| **Lemory** (hybrid + graph) | 0.847 | 0.960 | 0.967 | 0.970 | 0.897 | 7.766 |
| Lemory w/o graph (ablation) | 0.863 | 0.960 | 0.967 | 0.970 | 0.908 | 6.626 |
| Vector-only (naive RAG) | 0.813 | 0.950 | 0.973 | 0.980 | 0.881 | 8.124 |
| BM25 (lexical) | 0.830 | 0.920 | 0.950 | 0.970 | 0.881 | 7.449 |

## End-to-end QA — LemoryBench (synthetic multi-hop)

Same Gemini generator and prompt for every system; only retrieval differs. Token-F1 / containment-EM vs gold answers.

| System | F1 | EM (contain) | F1 (2-hop) | F1 (1-hop) | n |
|---|---|---|---|---|---|

## End-to-end QA — 실제 나무위키 메이플스토리 (real data)

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

mem0 by hops: 1-hop 0.6666666666666666, 2-hop 0.5476190476190477 · 212 ms/query, ingest 0s for 54 notes

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

## 4c. Query robustness (real-world phrasings)

The multi-hop questions re-asked as committed variants: an English
paraphrase, a natural Korean phrasing (Korean query → English notes),
a terse keyword lookup, and a typo'd version (1-2 injected typos).
Metric: full-support@8 against the original gold notes. Lemory's typo
resilience comes from local did-you-mean correction over the vault
vocabulary (zero API calls; hybrid pipeline only — baselines stay pure).

| System | original | paraphrase | korean | keyword | typo |
|---|---|---|---|---|---|
| **Lemory** (hybrid + graph) | 1.000 | 0.946 | 0.975 | 0.982 | 0.965 |
| Lemory w/o graph (ablation) | 0.544 | 0.446 | 0.275 | 0.464 | 0.526 |
| Vector-only (naive RAG) | 0.544 | 0.464 | 0.475 | 0.482 | 0.491 |
| BM25 (lexical) | 0.579 | 0.429 | 0.250 | 0.482 | 0.404 |

Optional LLM query expansion (`--expand`) was also measured: paraphrase 0.911, korean 0.950, typo 0.825 — no better than the LLM-free pipeline on this corpus, which is why it stays off by default (saves one LLM call per query).

## Korean corpus: 실제 나무위키 메이플스토리 (1,469 real documents)

All documents categorized under 메이플스토리 in the public namuwiki 2021-03-01 dump (867k docs scanned): 33,375 chunks, 24,850 real wikilink edges. QA drafted by LLM, kept only if code-verified: answer appears ONLY in the gold note, no title leakage (see gen_maple_real_qa.py).

| System | Full-support@8 | Recall@1 | Recall@5 | MRR@10 |
|---|---|---|---|---|
| **Lemory** (hybrid + graph) | 0.820 | 0.820 | 0.980 | 0.895 |
| Lemory w/o graph (ablation) | 0.700 | 0.860 | 0.960 | 0.900 |
| Vector-only (naive RAG) | 0.660 | 0.700 | 0.920 | 0.796 |
| BM25 (lexical) | 0.560 | 0.540 | 0.860 | 0.688 |

## Korean corpus: 메이플스토리 (나무위키-style, Korean)

Real game entities/terminology; relations wired by code, QA gold by construction.

| System | Full-support@8 | Recall@1 | Recall@5 | MRR@10 |
|---|---|---|---|---|
| **Lemory** (hybrid + graph) | 1.000 | 1.000 | 1.000 | 1.000 |
| Lemory w/o graph (ablation) | 0.818 | 1.000 | 1.000 | 1.000 |
| Vector-only (naive RAG) | 0.818 | 1.000 | 1.000 | 1.000 |
| BM25 (lexical) | 0.818 | 0.939 | 1.000 | 0.965 |

## Korean corpus: 전세사기 관계법령 (Korean legal)

Real statutes (주택임대차보호법, 전세사기특별법 등); QA answers code-verified to appear in gold notes.

| System | Full-support@8 | Recall@1 | Recall@5 | MRR@10 |
|---|---|---|---|---|
| **Lemory** (hybrid + graph) | 1.000 | 1.000 | 1.000 | 1.000 |
| Lemory w/o graph (ablation) | 0.947 | 1.000 | 1.000 | 1.000 |
| Vector-only (naive RAG) | 0.895 | 1.000 | 1.000 | 1.000 |
| BM25 (lexical) | 0.895 | 1.000 | 1.000 | 1.000 |

## Temporal scenario: "요새 내가 하던 그거 뭐였지?" (real embeddings)

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

## Second-brain scale (948 mixed KR/EN notes, LLM-free)

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


## 5. Local retrieval latency at scale (`perf_local.py`)

Synthetic Zipfian corpus, 50 queries, exact cosine + SQLite FTS5.
50k chunks ≈ an 8,000-note vault — well past typical personal vaults.

| Index size | hybrid+graph | hybrid | vector | bm25 |
|---|---|---|---|---|
| 2,000 chunks | 6.9 ms | 4.4 ms | 0.54 ms | 3.4 ms |
| 10,000 chunks | 18.7 ms | 16.0 ms | 1.27 ms | 13.7 ms |
| 50,000 chunks | 79.3 ms | 75.7 ms | 5.54 ms | 68.5 ms |

\* ms/query is local compute only (vector/BM25/graph math), measured on the
benchmark machine; the query embedding round-trip (~100–300 ms, identical for
all embedding-based systems) is excluded.

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
