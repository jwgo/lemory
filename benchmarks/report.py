"""Assemble BENCHMARKS.md from the result JSONs in benchmarks/work/."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import WORK

OUT = Path(__file__).parent.parent / "BENCHMARKS.md"

NAMES = {
    "lemory": "**Lemory** (hybrid + graph)",
    "lemory-nograph": "Lemory w/o graph (ablation)",
    "vector": "Vector-only (naive RAG)",
    "bm25": "BM25 (lexical)",
    "mem0": "mem0 OSS (Gemini backend)",
}


def table(rows: list[dict], cols: list[tuple[str, str]], sys_order: list[str]) -> str:
    head = "| System | " + " | ".join(label for _, label in cols) + " |"
    sep = "|---" * (len(cols) + 1) + "|"
    lines = [head, sep]
    for s in sys_order:
        r = next((x for x in rows if x["system"] == s), None)
        if not r:
            continue
        cells = []
        for key, _ in cols:
            v = r.get(key)
            cells.append(f"{v:.3f}" if isinstance(v, float) else ("—" if v is None else str(v)))
        lines.append(f"| {NAMES.get(s, s)} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main() -> None:
    sections = []

    mh_file = WORK / "results_retrieval_multihop.json"
    if mh_file.exists():
        res = json.loads(mh_file.read_text())
        rows = [{"system": s, **m} for s, m in res.items()]
        sections.append(
            "## 1. Multi-hop retrieval (LemoryBench, 57 questions / 54-note vault)\n\n"
            "Full-support@8 = both gold notes for a 2-hop question retrieved in the top 8 — \n"
            "the precondition for a correct multi-hop answer.\n\n"
            + table(rows, [
                ("full_support@8_hops2", "Full-support@8 (2-hop)"),
                ("full_support@8", "Full-support@8 (all)"),
                ("recall@1", "Recall@1"),
                ("mrr@10", "MRR@10"),
                ("ms_per_query", "ms/query*"),
            ], ["lemory", "lemory-nograph", "vector", "bm25"])
        )

    sq_file = WORK / "results_retrieval_squad.json"
    if sq_file.exists():
        res = json.loads(sq_file.read_text())
        rows = [{"system": s, **m} for s, m in res.items()]
        sections.append(
            "## 2. Single-hop retrieval (SQuAD v2 dev, real external data)\n\n"
            "18 Wikipedia articles as notes (~1,200 paragraphs), 300 real questions. \n"
            "Hit = retrieved chunk is from the gold article and contains a gold answer.\n\n"
            + table(rows, [
                ("recall@1", "Recall@1"),
                ("recall@3", "Recall@3"),
                ("recall@5", "Recall@5"),
                ("recall@8", "Recall@8"),
                ("mrr@10", "MRR@10"),
                ("ms_per_query", "ms/query*"),
            ], ["lemory", "lemory-nograph", "vector", "bm25"])
        )

    e2e_file = WORK / "results_e2e_multihop.json"
    if e2e_file.exists():
        summary = json.loads(e2e_file.read_text()).get("summary", {})
        rows = [{"system": s, **m} for s, m in summary.items()]
        sections.append(
            "## 3. End-to-end QA (same Gemini generator, only retrieval differs)\n\n"
            "40 LemoryBench questions; token-F1 / containment-EM vs gold answers.\n\n"
            + table(rows, [
                ("f1", "F1"),
                ("contain_em", "EM (contain)"),
                ("f1_hops2", "F1 (2-hop)"),
                ("f1_hops1", "F1 (1-hop)"),
                ("n", "n"),
            ], ["lemory", "vector", "bm25"])
        )

    m0_file = WORK / "results_mem0.json"
    if m0_file.exists():
        d = json.loads(m0_file.read_text())
        aic = d.get("answer_in_context@8", {})
        rows = [{"system": s, "aic": v} for s, v in aic.items()]
        extra = ""
        if d.get("mem0_hops"):
            extra = (f"\n\nmem0 by hops: 1-hop {d['mem0_hops'].get('1')}, "
                     f"2-hop {d['mem0_hops'].get('2')} · "
                     f"{d.get('mem0_ms_per_query', 0):.0f} ms/query, "
                     f"ingest {d.get('add_seconds', 0):.0f}s for 54 notes")
        sections.append(
            "## 4. External system: mem0 (OSS)\n\n"
            "mem0 with the identical Gemini LLM/embedder, default fact-extraction\n"
            "pipeline, local Qdrant. Shared metric: answer-in-context@8 — the gold\n"
            "answer string appears in the top-8 retrieved texts (LemoryBench, 57 q).\n\n"
            + table(rows, [("aic", "Answer-in-context@8")],
                    ["lemory", "vector", "bm25", "mem0"]) + extra
        )

    perf_file = WORK / "results_perf.json"
    if perf_file.exists():
        perf = json.loads(perf_file.read_text())
        lines = ["| Index size | hybrid+graph | hybrid | vector | bm25 |", "|---|---|---|---|---|"]
        for n, r in perf.items():
            lines.append(
                f"| {int(n):,} chunks | {r['hybrid+graph']:.1f} ms | {r['hybrid']:.1f} ms "
                f"| {r['vector']:.2f} ms | {r['bm25']:.1f} ms |"
            )
        sections.append(
            "## 5. Local retrieval latency at scale (`perf_local.py`)\n\n"
            "Synthetic Zipfian corpus, 50 queries, exact cosine + SQLite FTS5.\n"
            "50k chunks ≈ an 8,000-note vault — well past typical personal vaults.\n\n"
            + "\n".join(lines)
        )

    body = "\n\n".join(sections)
    OUT.write_text(HEADER + body + FOOTER)
    print(f"wrote {OUT}")


HEADER = """# Lemory benchmarks

All systems share the same corpus, chunking, and Gemini embeddings; they differ
only in retrieval strategy (for mem0: its own full OSS pipeline with the same
Gemini models). Generator model, prompt, and context budget are identical in the
end-to-end eval. Benchmark corpora and code live in `benchmarks/`; multi-hop
gold labels are correct by construction (relations wired deterministically in
code, prose leakage scrubbed and verified — see `gen_multihop.py`).

Environment note: run on a Gemini free-tier key; retrieval latency numbers
exclude the query-embedding API call (identical for every system).

"""

FOOTER = """

\\* ms/query is local compute only (vector/BM25/graph math), measured on the
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
"""


if __name__ == "__main__":
    main()
