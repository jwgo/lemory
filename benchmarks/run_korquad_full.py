"""Full-scale KorQuAD validation: EVERY train paragraph, EVERY train question.

Not a sample: 9,663 unique Korean Wikipedia paragraphs indexed as one vault
(distractor-rich — every other paragraph competes), then all 60,407 human-
written questions run end-to-end through the real engine. Keyless local
(e5-small-ko-v2), so anyone can reproduce without an API key:

    python benchmarks/run_korquad_full.py [--fast-only|--hybrid-only] [--limit N]

Reports paragraph recall@1/@5 and p50/p95 end-to-end latency at scale.

Data (38 MB, gitignored):
    curl -o benchmarks/data/korquad/KorQuAD_v1.0_train.json \
        https://korquad.github.io/dataset/KorQuAD_v1.0_train.json
"""
from __future__ import annotations

import json
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
DATA = Path(__file__).parent / "data" / "korquad" / "KorQuAD_v1.0_train.json"
OUT = Path(__file__).parent / "work" / "results_korquad_full.json"


def load_full():
    d = json.loads(DATA.read_text())
    seen: dict[str, int] = {}
    corpus: list[str] = []
    questions: list[str] = []
    gold: list[int] = []
    for art in d["data"]:
        for p in art["paragraphs"]:
            ctx = p["context"]
            if ctx not in seen:
                seen[ctx] = len(corpus)
                corpus.append(ctx)
            for qa in p["qas"]:
                questions.append(qa["question"])
                gold.append(seen[ctx])
    return corpus, questions, gold


def main():
    args = sys.argv[1:]
    limit = None
    if "--limit" in args:
        limit = int(args[args.index("--limit") + 1])
    modes = ["hybrid", "fast"]
    if "--fast-only" in args:
        modes = ["fast"]
    if "--hybrid-only" in args:
        modes = ["hybrid"]

    import tempfile

    from lemory.config import LemoryConfig
    from lemory.engine import Engine

    corpus, questions, gold = load_full()
    if limit:
        questions, gold = questions[:limit], gold[:limit]
    print(f"corpus: {len(corpus)} paragraphs (ALL of KorQuAD train) · "
          f"{len(questions)} questions · keyless local (e5-small-ko-v2)", flush=True)

    d = Path(tempfile.mkdtemp())
    vault = d / "vault"
    vault.mkdir()
    for i, ctx in enumerate(corpus):
        (vault / f"p{i:05d}.md").write_text(ctx, encoding="utf-8")
    eng = Engine(LemoryConfig(vault=vault, data_dir=d / "data", provider="local"))
    t0 = time.time()
    eng.index()
    index_s = time.time() - t0
    st = eng.status()
    print(f"indexed in {index_s:.0f}s · {st['chunks']} chunks", flush=True)

    results = {"corpus": len(corpus), "questions": len(questions),
               "chunks": st["chunks"], "index_seconds": round(index_s, 1), "modes": {}}
    for mode in modes:
        hit1 = hit5 = 0
        lat: list[float] = []
        t_mode = time.time()
        for n, (q, g) in enumerate(zip(questions, gold)):
            t = time.perf_counter()
            hits = eng.search(q, k=5, mode=mode)
            lat.append(time.perf_counter() - t)
            paths = [h.path for h in hits]
            if paths and paths[0] == f"p{g:05d}.md":
                hit1 += 1
            if f"p{g:05d}.md" in paths:
                hit5 += 1
            if (n + 1) % 5000 == 0:
                print(f"  [{mode}] {n+1}/{len(questions)} "
                      f"r@1={hit1/(n+1):.3f} r@5={hit5/(n+1):.3f}", flush=True)
        lat.sort()
        m = {
            "recall@1": round(hit1 / len(questions), 4),
            "recall@5": round(hit5 / len(questions), 4),
            "p50_ms": round(lat[len(lat) // 2] * 1000, 1),
            "p95_ms": round(lat[int(len(lat) * 0.95)] * 1000, 1),
            "total_seconds": round(time.time() - t_mode, 1),
        }
        results["modes"][mode] = m
        print(f"[{mode}] recall@1={m['recall@1']} recall@5={m['recall@5']} "
              f"p50={m['p50_ms']}ms p95={m['p95_ms']}ms", flush=True)
    eng.close()
    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"saved -> {OUT}", flush=True)


if __name__ == "__main__":
    main()
