"""Shared Korean-retrieval harness for head-to-head competitor benchmarks.

Every competitor is ONE adapter: it receives the same corpus (real Korean
Wikipedia paragraphs from KorQuAD) + questions + gold indices, and returns
(recall@1, p50_latency_ms). Latency is END-TO-END including query embedding —
the number marketing pages hide.

Add a competitor by writing `run_<name>(corpus, questions, gold)` in its own
file and calling `bench(name, fn, ...)`. The Lemory baseline lives here so
every comparison shares an identical, honest reference.

    from harness_korean import load_korquad, bench, run_lemory
    corpus, questions, gold = load_korquad(120, cap=None)
    bench("lemory keyless (e5-ko)", run_lemory, corpus, questions, gold)
    bench("competitorX", run_competitorX, corpus, questions, gold)
"""
from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
DATA = Path(__file__).parent / "data" / "korquad" / "KorQuAD_v1.0_dev.json"


def load_korquad(n: int, cap: int | None = None, seed: int = 7):
    """Return (corpus, questions, gold). `cap` truncates each paragraph to N
    chars — set it ONLY for a system with a hard per-item limit (e.g. memvid
    v1's QR frames), and it is applied identically to every system in that run
    so the comparison stays fair. `cap=None` = full paragraphs (preferred)."""
    d = json.loads(DATA.read_text())
    pairs = [(p["context"], qa["question"])
             for art in d["data"] for p in art["paragraphs"] for qa in p["qas"]]
    random.Random(seed).shuffle(pairs)
    seen, corpus, questions, gold = {}, [], [], []
    for ctx, q in pairs:
        if cap:
            ctx = ctx[:cap]
        if ctx not in seen:
            seen[ctx] = len(corpus)
            corpus.append(ctx)
        questions.append(q)
        gold.append(seen[ctx])
        if len(questions) >= n:
            break
    return corpus, questions, gold


def bench(name: str, fn, corpus, questions, gold) -> dict | None:
    """Run one adapter, print + return its result. Adapters may raise if the
    competitor can't ingest the corpus (a real, reportable failure)."""
    try:
        r1, ms = fn(corpus, questions, gold)
        print(f"{name:38} recall@1={r1:.3f}  p50={ms:.1f}ms (end-to-end, local)")
        return {"system": name, "recall@1": round(r1, 4), "p50_ms": round(ms, 1)}
    except Exception as e:  # noqa: BLE001
        print(f"{name:38} FAILED: {type(e).__name__}: {str(e)[:110]}")
        return {"system": name, "error": f"{type(e).__name__}: {str(e)[:200]}"}


def run_lemory(corpus, questions, gold, provider: str = "local"):
    """Lemory baseline: keyless local (Korean e5) hybrid, one note per paragraph."""
    import tempfile

    from lemory.config import LemoryConfig
    from lemory.engine import Engine

    d = Path(tempfile.mkdtemp())
    vault = d / "vault"
    vault.mkdir()
    for i, ctx in enumerate(corpus):
        (vault / f"p{i:04d}.md").write_text(ctx, encoding="utf-8")
    eng = Engine(LemoryConfig(vault=vault, data_dir=d / "data", provider=provider))
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
