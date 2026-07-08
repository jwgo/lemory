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
| **Lemory** (hybrid + graph) | 1.000 | 1.000 | 1.000 | 1.000 | 2.255 |
| Lemory w/o graph (ablation) | 0.381 | 0.544 | 1.000 | 1.000 | 1.154 |
| Vector-only (naive RAG) | 0.381 | 0.544 | 0.965 | 0.982 | 0.376 |
| BM25 (lexical) | 0.429 | 0.579 | 0.825 | 0.912 | 0.771 |

## 4. External system: mem0 (OSS)

mem0 with the identical Gemini LLM/embedder, default fact-extraction
pipeline, local Qdrant. Shared metric: answer-in-context@8 — the gold
answer string appears in the top-8 retrieved texts (LemoryBench, 57 q).

| System | Answer-in-context@8 |
|---|---|
| **Lemory** (hybrid + graph) | 1.000 |
| Vector-only (naive RAG) | 0.561 |
| BM25 (lexical) | 0.667 |

## 5. Local retrieval latency at scale (`perf_local.py`)

Synthetic Zipfian corpus, 50 queries, exact cosine + SQLite FTS5.
50k chunks ≈ an 8,000-note vault — well past typical personal vaults.

| Index size | hybrid+graph | hybrid | vector | bm25 |
|---|---|---|---|---|
| 2,000 chunks | 7.3 ms | 4.6 ms | 0.56 ms | 3.7 ms |
| 10,000 chunks | 19.0 ms | 16.4 ms | 1.12 ms | 15.5 ms |
| 50,000 chunks | 80.1 ms | 74.1 ms | 6.05 ms | 69.0 ms |

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
