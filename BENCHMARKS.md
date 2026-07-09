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
| **Lemory** (hybrid + graph) | 1.000 | 1.000 | 1.000 | 1.000 | 1.919 |
| Lemory w/o graph (ablation) | 0.381 | 0.544 | 1.000 | 1.000 | 1.326 |
| Vector-only (naive RAG) | 0.381 | 0.544 | 0.965 | 0.982 | 0.385 |
| BM25 (lexical) | 0.429 | 0.579 | 0.825 | 0.912 | 0.764 |

## 2. Single-hop retrieval (SQuAD v2 dev, real external data)

18 Wikipedia articles as notes (~1,200 paragraphs), 300 real questions. 
Hit = retrieved chunk is from the gold article and contains a gold answer.

| System | Recall@1 | Recall@3 | Recall@5 | Recall@8 | MRR@10 | ms/query* |
|---|---|---|---|---|---|---|
| **Lemory** (hybrid + graph) | 0.847 | 0.963 | 0.970 | 0.970 | 0.899 | 6.605 |
| Lemory w/o graph (ablation) | 0.863 | 0.960 | 0.967 | 0.967 | 0.908 | 5.552 |
| Vector-only (naive RAG) | 0.813 | 0.950 | 0.973 | 0.980 | 0.881 | 7.871 |
| BM25 (lexical) | 0.830 | 0.920 | 0.950 | 0.970 | 0.881 | 7.524 |

## 3. End-to-end QA (same Gemini generator, only retrieval differs)

40 LemoryBench questions; token-F1 / containment-EM vs gold answers.

| System | F1 | EM (contain) | F1 (2-hop) | F1 (1-hop) | n |
|---|---|---|---|---|---|
| **Lemory** (hybrid + graph) | 0.867 | 1.000 | 0.861 | 0.889 | 30 |
| Vector-only (naive RAG) | 0.428 | 0.500 | 0.283 | 0.905 | 30 |
| BM25 (lexical) | 0.491 | 0.567 | 0.370 | 0.889 | 30 |

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
python benchmarks/report.py
```

## Why these baselines

* **Vector-only** is the retrieval core of typical RAG/notes products (and of
  supermemory-style pipelines): cosine over the same embeddings.
* **BM25** is the classic lexical baseline (what most in-app search does).
* **Lemory w/o graph** isolates where the multi-hop gain comes from.
* **mem0** is a real external OSS memory system run end-to-end.
* **cognee** is not run in-harness: its cognify step requires per-chunk LLM
  calls beyond free-tier limits for a corpus this size; Lemory's optional
  `enrich_entities` implements the equivalent enrichment.
