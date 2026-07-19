"""JSQuAD (JGLUE) — Japanese Wikipedia paragraph retrieval, keyless local.

Extends the CJK claim past Korean with data: ALL 4,442 human-written Japanese
questions of the JSQuAD validation set, every unique paragraph indexed as one
note (so every paragraph is a distractor for every question), paragraph
recall@1/@5, end-to-end latency. Same protocol as the KorQuAD rows.

Data (HF, downloads once):
    hf_hub_download("sbintuitions/JSQuAD", "data/validation-00000-of-00001.parquet",
                    repo_type="dataset", local_dir="benchmarks/data/jsquad")

    python benchmarks/run_jsquad.py [n_questions]
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from common import WORK, save_json  # noqa: E402

from lemory.config import LemoryConfig  # noqa: E402
from lemory.engine import Engine  # noqa: E402

PARQUET = Path(__file__).parent / "data" / "jsquad" / "data" / "validation-00000-of-00001.parquet"
ARMS = {"hybrid": {}, "fast": {"mode": "fast"},
        "vector": {"mode": "vector"}, "bm25": {"mode": "bm25"}}


def load_jsquad(limit: int | None = None):
    import pyarrow.parquet as pq

    t = pq.read_table(PARQUET)
    seen: dict[str, int] = {}
    corpus: list[str] = []
    questions: list[str] = []
    gold: list[int] = []
    for i in range(t.num_rows):
        ctx = t.column("context")[i].as_py()
        ctx = ctx.split(" [SEP] ", 1)[-1]  # strip the "title [SEP] " prefix
        if ctx not in seen:
            seen[ctx] = len(corpus)
            corpus.append(ctx)
        questions.append(t.column("question")[i].as_py())
        gold.append(seen[ctx])
        if limit and len(questions) >= limit:
            break
    return corpus, questions, gold


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    corpus, questions, gold = load_jsquad(limit)
    print(f"JSQuAD: {len(corpus)} unique paragraphs · {len(questions)} Japanese "
          f"questions · keyless local (e5-small-ko-v2 is multilingual)", flush=True)
    d = Path(tempfile.mkdtemp())
    vault = d / "vault"
    vault.mkdir()
    for i, ctx in enumerate(corpus):
        (vault / f"p{i:04d}.md").write_text(ctx, encoding="utf-8")
    eng = Engine(LemoryConfig(vault=vault, data_dir=d / "data", provider="local"))
    t0 = time.time()
    eng.index()
    print(f"indexed in {time.time()-t0:.0f}s · {eng.store.chunk_count()} chunks", flush=True)

    results = {"corpus": len(corpus), "questions": len(questions), "arms": {}}
    for arm, kw in ARMS.items():
        hit1 = hit5 = 0
        lat = []
        for q, g in zip(questions, gold):
            t = time.perf_counter()
            hits = eng.search(q, k=5, **kw)
            lat.append(time.perf_counter() - t)
            paths = [h.path for h in hits]
            if paths and paths[0] == f"p{g:04d}.md":
                hit1 += 1
            if f"p{g:04d}.md" in paths:
                hit5 += 1
        lat.sort()
        m = {"recall@1": round(hit1 / len(questions), 4),
             "recall@5": round(hit5 / len(questions), 4),
             "p50_ms": round(lat[len(lat) // 2] * 1000, 1)}
        results["arms"][arm] = m
        print(f"[{arm:6}] recall@1={m['recall@1']} recall@5={m['recall@5']} "
              f"p50={m['p50_ms']}ms", flush=True)
    eng.close()
    save_json(WORK / "results_jsquad.json", results)


if __name__ == "__main__":
    main()
