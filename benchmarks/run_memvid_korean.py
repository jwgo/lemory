"""Head-to-head: memvid vs Lemory on Korean retrieval (KorQuAD paragraphs).

Fair, controlled, local-only on BOTH sides (matching memvid's "zero-API local
embedder" pitch):
  * corpus = N real Korean Wikipedia paragraphs (KorQuAD dev)
  * task = for each human-written question, retrieve its gold paragraph; the
    same paragraphs are the haystack for every question. Metric: recall@1.
  * memvid  = the pip `memvid` package (v1), its DEFAULT embedder
    all-MiniLM-L6-v2 — English-only. (v1's video layer is deprecated, but its
    retrieval is FAISS+sentence-transformers; v2's advertised default
    embedders BGE-small/base/GTE are ALSO English-centric per its README, so
    the Korean axis measured here is architectural, not v1-specific.)
  * lemory  = keyless `local` provider (Korean-tuned e5-small-ko-v2) + hybrid.

Run:  python benchmarks/run_memvid_korean.py [n_questions]
"""
from __future__ import annotations

import json
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

DATA = Path(__file__).parent / "data" / "korquad" / "KorQuAD_v1.0_dev.json"


def load(n: int, seed: int = 7):
    import random
    d = json.loads(DATA.read_text())
    pairs = []
    for art in d["data"]:
        for p in art["paragraphs"]:
            for qa in p["qas"]:
                pairs.append((p["context"], qa["question"]))
    random.Random(seed).shuffle(pairs)
    # unique paragraphs, first n distinct questions whose gold para is unique
    seen, corpus, questions, gold = {}, [], [], []
    for ctx, q in pairs:
        ctx = ctx[:450]  # QR capacity cap (v1 storage) — applied to BOTH systems, identical corpus
        if ctx not in seen:
            seen[ctx] = len(corpus)
            corpus.append(ctx)
        questions.append(q)
        gold.append(seen[ctx])
        if len(questions) >= n:
            break
    return corpus, questions, gold


def run_memvid(corpus, questions, gold):
    from memvid import MemvidEncoder, MemvidRetriever
    import tempfile, os
    d = tempfile.mkdtemp()
    enc = MemvidEncoder()
    enc.add_chunks(list(corpus))
    v, idx = os.path.join(d, "m.mp4"), os.path.join(d, "m.json")
    enc.build_video(v, idx)
    r = MemvidRetriever(v, idx)
    hit, lat = 0, []
    for q, g in zip(questions, gold):
        t = time.perf_counter()
        res = r.search(q, top_k=1)
        lat.append(time.perf_counter() - t)
        if res and res[0].strip() == corpus[g].strip():
            hit += 1
    return hit / len(questions), sorted(lat)[len(lat) // 2] * 1000


def run_lemory(corpus, questions, gold):
    import tempfile
    from lemory.config import LemoryConfig
    from lemory.engine import Engine
    d = Path(tempfile.mkdtemp())
    vault = d / "vault"
    vault.mkdir()
    for i, ctx in enumerate(corpus):
        (vault / f"p{i:04d}.md").write_text(ctx, encoding="utf-8")
    eng = Engine(LemoryConfig(vault=vault, data_dir=d / "data", provider="local"))
    eng.index()
    hit, lat = 0, []
    for q, g in zip(questions, gold):
        t = time.perf_counter()
        hits = eng.search(q, k=1)
        lat.append(time.perf_counter() - t)
        if hits and hits[0].path == f"p{g:04d}.md":
            hit += 1
    eng.close()
    return hit / len(questions), sorted(lat)[len(lat) // 2] * 1000


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 150
    corpus, questions, gold = load(n)
    print(f"corpus={len(corpus)} paragraphs · {len(questions)} Korean questions "
          f"· recall@1, both fully local\n")
    for name, fn in [("memvid v1 (all-MiniLM-L6-v2, EN)", run_memvid),
                     ("lemory keyless (e5-small-ko-v2)", run_lemory)]:
        try:
            r1, ms = fn(corpus, questions, gold)
            print(f"{name:36} recall@1={r1:.3f}  p50={ms:.1f}ms (retrieval, local)")
        except Exception as e:
            print(f"{name:36} FAILED: {type(e).__name__}: {str(e)[:120]}")


if __name__ == "__main__":
    main()
