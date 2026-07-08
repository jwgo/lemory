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
| **Lemory** (hybrid + graph) | 1.000 | 1.000 | 1.000 | 1.000 | 2.004 |
| Lemory w/o graph (ablation) | 0.381 | 0.544 | 1.000 | 1.000 | 1.271 |
| Vector-only (naive RAG) | 0.381 | 0.544 | 0.965 | 0.982 | 0.381 |
| BM25 (lexical) | 0.429 | 0.579 | 0.825 | 0.912 | 0.813 |

## 3. End-to-end QA (same Gemini generator, only retrieval differs)

40 LemoryBench questions; token-F1 / containment-EM vs gold answers.

| System | F1 | EM (contain) | F1 (2-hop) | F1 (1-hop) | n |
|---|---|---|---|---|---|

## 4. External system: mem0 (OSS)

mem0 with the identical Gemini LLM/embedder, default fact-extraction
pipeline, local Qdrant. Shared metric: answer-in-context@8 — the gold
answer string appears in the top-8 retrieved texts (LemoryBench, 57 q).

| System | Answer-in-context@8 |
|---|---|
| **Lemory** (hybrid + graph) | 1.000 |
| Vector-only (naive RAG) | 0.561 |
| BM25 (lexical) | 0.667 |

## Second-brain scale (948 mixed KR/EN notes, LLM-free)

Diverse realistic vault (people, projects, daily logs, meetings, tastes,
clippings) with 50 planted facts; deterministic local embedder, so this
verifies ingest/sync/graph/lexical retrieval at scale (semantic quality
is covered by the corpora above on real embeddings).

| Metric | value |
|---|---|
| Notes / chunks / links | 948 / 1428 / 1176 |
| Full index | 4.5 s |
| Incremental sync (1 edit) | 0.08 s |
| Planted-fact hit@1 (hybrid) | 1.00 |
| Planted-fact hit@1 (BM25) | 0.92 |
| Planted-fact hit@5 (hybrid) | 1.00 |
| Search latency (hybrid) | 3.6 ms |


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
