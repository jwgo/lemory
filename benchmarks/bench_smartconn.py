"""Smart-Connections-class measurement: its default local embedding model
(TaylorAI/bge-micro-v2, confirmed from smart-embed-model's models.json),
pure cosine over note chunks — no lexical leg, no graph (the plugin's
connections view is vector-only). Run on the same corpora as every other row.
"""
import json, sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "benchmarks"))
sys.path.insert(0, str(REPO / "src"))

from fastembed import TextEmbedding
from fastembed.common.model_description import DenseModelDescription, ModelSource, PoolingType

try:
    TextEmbedding.add_custom_model(
        model="TaylorAI/bge-micro-v2",
        pooling=PoolingType.CLS,  # BGE family uses CLS pooling
        normalization=True,
        sources=ModelSource(hf="TaylorAI/bge-micro-v2"),
        dim=384,
    )
except Exception as e:
    print("add_custom_model:", e)

from common import DATA, WORK, make_engine, prewarm_queries
from lemory.retrieval.search import hybrid_search

def evaluate(vault, questions, tag):
    eng = make_engine(vault, tag=tag, local_embed_model="TaylorAI/bge-micro-v2")
    eng.index()
    prewarm_queries(eng, [q["q"] for q in questions])
    full = r1 = 0
    by = {1: [0, 0], 2: [0, 0]}
    for q in questions:
        hits = hybrid_search(eng, q["q"], k=8, mode="vector").hits
        titles = [h.title for h in hits]
        gold = set(q["gold_notes"])
        ok = gold <= set(titles)
        full += ok
        r1 += bool(titles and titles[0] in gold)
        h = 2 if len(gold) > 1 else 1
        by[h][0] += ok; by[h][1] += 1
    n = len(questions)
    return dict(n=n, full_support=round(full/n, 3), recall1=round(r1/n, 3),
                hops1=round(by[1][0]/by[1][1], 3) if by[1][1] else None,
                hops2=round(by[2][0]/by[2][1], 3) if by[2][1] else None)

out = {}
mh_qs = json.loads((DATA / "multihop" / "questions.json").read_text())
out["multihop"] = evaluate(DATA / "multihop" / "vault", mh_qs, "sc-multihop")

variants = json.loads((DATA / "multihop" / "robust_queries.json").read_text())
gold = {q["q"]: q["gold_notes"] for q in mh_qs}
eng = make_engine(DATA / "multihop" / "vault", tag="sc-multihop",
                  local_embed_model="TaylorAI/bge-micro-v2")
eng.index()
for key in ("paraphrase", "korean", "keyword", "typo"):
    vq = [dict(q=v[key], gold_notes=gold[orig]) for orig, v in variants.items()
          if isinstance(v, dict) and v.get(key) and orig in gold]
    prewarm_queries(eng, [q["q"] for q in vq])
    full = 0
    for q in vq:
        hits = hybrid_search(eng, q["q"], k=8, mode="vector").hits
        full += set(q["gold_notes"]) <= {h.title for h in hits}
    out[f"robust_{key}"] = dict(n=len(vq), full_support=round(full/len(vq), 3))

for name in ("maple", "law", "kepano"):
    qs = json.loads((DATA / name / "questions.json").read_text())
    out[name] = evaluate(DATA / name / "vault", qs, f"sc-{name}")

print(json.dumps(out, indent=2))
