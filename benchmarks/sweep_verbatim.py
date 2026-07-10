"""Offline sweep: close the verbatim-question gap vs BM25 without breaking
robustness. All embeddings are cached — zero API calls.

Target   : KorQuAD recall@1 / MRR (Lemory 0.887 vs BM25 0.923 — our published loss)
Guards   : multihop full-support@8 must stay 1.000
           robustness variants (paraphrase/korean/keyword/typo) must not drop

    python benchmarks/sweep_verbatim.py
"""

from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (DATA, WORK, answer_in_text, load_env, make_engine,
                    prewarm_queries, rank_metrics)

from run_korquad import VAULT as KORQUAD_VAULT, prepare


def eval_korquad(eng, questions):
    flags = []
    for q in questions:
        hits = eng.search(q["q"], k=8, mode="hybrid", graph=True)
        flags.append([h.title == q["article"] and answer_in_text(h.text, q["answers"])
                      for h in hits])
    return rank_metrics(flags)


def eval_multihop(eng, questions):
    full = 0
    for q in questions:
        hits = eng.search(q["q"], k=8, mode="hybrid", graph=True)
        titles = {h.title for h in hits}
        if len(titles & set(q["gold_notes"])) >= len(q["gold_notes"]):
            full += 1
    return full / len(questions)


def eval_robust(eng, variants_by_name):
    """full-support@8 per phrasing variant."""
    out = {}
    for name, qs in variants_by_name.items():
        full = 0
        for vq, gold in qs:
            hits = eng.search(vq, k=8, mode="hybrid", graph=True)
            titles = {h.title for h in hits}
            if len(titles & set(gold)) >= len(gold):
                full += 1
        out[name] = full / len(qs)
    return out


def main() -> None:
    load_env()
    korquad_q = prepare()
    mh_q = json.loads((DATA / "multihop" / "questions.json").read_text())
    raw_variants = json.loads((DATA / "multihop" / "robust_queries.json").read_text())
    gold_by_q = {q["q"]: q["gold_notes"] for q in mh_q}
    variants: dict[str, list] = {}
    for orig, forms in raw_variants.items():
        if orig not in gold_by_q:
            continue
        for name, vq in forms.items():
            variants.setdefault(name, []).append((vq, gold_by_q[orig]))

    # sync both indexes to the committed corpora and warm the query caches —
    # a stale index silently zeroes every metric (been there)
    kq0 = make_engine(KORQUAD_VAULT, tag="korquad")
    kq0.index()
    prewarm_queries(kq0, [q["q"] for q in korquad_q])
    kq0.store.close()
    mh0 = make_engine(DATA / "multihop" / "vault", tag="multihop")
    mh0.index()
    all_variant_qs = [vq for qs in variants.values() for vq, _ in qs]
    prewarm_queries(mh0, [q["q"] for q in mh_q] + all_variant_qs)
    mh0.store.close()

    grid = {
        "verbatim_gate": [0.60, 0.68, 0.75],
        "keyword_bm25_boost": [1.8, 2.4, 3.0],
    }
    keys = list(grid)
    for combo in itertools.product(*grid.values()):
        params = dict(zip(keys, combo))
        kq = make_engine(KORQUAD_VAULT, tag="korquad", **params)
        mh = make_engine(DATA / "multihop" / "vault", tag="multihop", **params)
        k_m = eval_korquad(kq, korquad_q)
        mh_full = eval_multihop(mh, mh_q)
        rb = eval_robust(mh, variants) if variants else {}
        rb_s = " ".join(f"{n[:4]}={v:.3f}" for n, v in rb.items())
        print(f"{json.dumps(params)}  KQ r@1={k_m['recall@1']:.3f} mrr={k_m['mrr@10']:.3f}"
              f" | MH full={mh_full:.3f} | {rb_s}", flush=True)
        kq.store.close(); mh.store.close()


if __name__ == "__main__":
    main()
