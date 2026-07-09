"""Guarded fusion sweep on real-data KorQuAD.

KorQuAD questions are written while looking at the passage, so lexical overlap
is unusually high — BM25 alone edges out the default hybrid there. Candidates
must improve KorQuAD recall@1 WITHOUT degrading multihop full-support or
robustness (original/korean/typo). All local, embeddings cached.
"""

from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import DATA, WORK, answer_in_text, make_engine, rank_metrics

VAULT_KQ = WORK / "korquad_vault"


def eval_korquad(engine, questions, k=8):
    flags = []
    for q in questions:
        hits = engine.search(q["q"], k=k, mode="hybrid", graph=True)
        flags.append([h.title == q["article"] and answer_in_text(h.text, q["answers"]) for h in hits])
    return rank_metrics(flags)["recall@1"]


def eval_multihop(engine, questions, k=8):
    n = 0
    for q in questions:
        hits = engine.search(q["q"], k=k, mode="hybrid", graph=True)
        if set(q["gold_notes"]) <= {h.title for h in hits}:
            n += 1
    return n / len(questions)


def eval_robust(engine, questions, variants, kind, k=8):
    n = t = 0
    for q in questions:
        text = q["q"] if kind == "original" else variants.get(q["q"], {}).get(kind)
        if not text:
            continue
        t += 1
        hits = engine.search(text, k=k, mode="hybrid", graph=True)
        if set(q["gold_notes"]) <= {h.title for h in hits}:
            n += 1
    return n / max(1, t)


def main() -> None:
    import run_korquad

    kq = run_korquad.prepare()[:250]
    mh = json.loads((DATA / "multihop" / "questions.json").read_text())
    rv = json.loads((DATA / "multihop" / "robust_queries.json").read_text())

    base = None
    print("w_bm25 kw_boost | korquad@1 | mh_full | rb_orig rb_kr rb_typo")
    for w, kb in itertools.product([0.6, 0.9, 1.2], [1.8, 2.4]):
        kq_eng = make_engine(VAULT_KQ, tag="korquad", w_bm25=w, keyword_bm25_boost=kb, gemini_api_key="x")
        mh_eng = make_engine(DATA / "multihop" / "vault", tag="multihop", w_bm25=w, keyword_bm25_boost=kb, gemini_api_key="x")
        r1 = eval_korquad(kq_eng, kq)
        fs = eval_multihop(mh_eng, mh)
        ro = eval_robust(mh_eng, mh, rv, "original")
        rk = eval_robust(mh_eng, mh, rv, "korean")
        rt = eval_robust(mh_eng, mh, rv, "typo")
        tag = ""
        if w == 0.6 and kb == 1.8:
            base = (r1, fs, ro, rk, rt)
            tag = "  <- current default"
        print(f"{w:5.1f} {kb:8.1f} | {r1:.4f}    | {fs:.3f}   | {ro:.3f}  {rk:.3f}  {rt:.3f}{tag}", flush=True)
        kq_eng.close(), mh_eng.close()


if __name__ == "__main__":
    main()
