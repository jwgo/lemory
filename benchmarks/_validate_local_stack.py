"""Validate the local-stack changes on KorMapleQA v2 (local only).

- Embedder gain (MiniLM vs Harrier): FULL answerable set, reranker off (fast).
- Reranker gain (jina on/off): a 400-question deterministic sample, because the
  in-process ONNX cross-encoder is ~0.7 s/query on CPU (the full 2k set would be
  ~50 min). 400 is enough to detect the expected doc@1 delta.

Writes results incrementally to validate_local_stack.json so a partial run still
leaves usable numbers. No keys, no network beyond the one-time model downloads.
"""
import json
import os
import time

os.environ.pop("GOOGLE_API_KEY", None)
os.environ.pop("GEMINI_API_KEY", None)
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
from lemory.config import LemoryConfig
from lemory.engine import Engine

QF = Path("benchmarks/data/kormapleqa/questions.jsonl")
qs_all = [json.loads(l) for l in QF.read_text().splitlines()]
qs_all = [q for q in qs_all if q.get("answerable", True)]
qs_sample = qs_all[::5][:400]  # deterministic, spread across the file's type order

OUT = Path("benchmarks/work/validate_local_stack.json")
out: dict = {}


def run(tag, data_dir, backend, reranker, qs):
    cfg = LemoryConfig(vault=Path("benchmarks/data/maple_real/vault"), data_dir=Path(data_dir),
                       provider="local", local_embed_backend=backend, reranker=reranker)
    eng = Engine(cfg)
    rep = eng.index()
    d1 = d8 = 0
    per: dict = {}
    t0 = time.time()
    for q in qs:
        hits = eng.search(q["q"], k=8)
        titles = [h.title for h in hits]
        g = q["gold_notes"]
        h1 = bool(titles and titles[0] in g)
        h8 = any(x in g for x in titles)
        d1 += h1
        d8 += h8
        pt = per.setdefault(q["type"], [0, 0, 0])
        pt[0] += h1
        pt[1] += h8
        pt[2] += 1
    n = len(qs)
    dt = time.time() - t0
    r = {"n": n, "doc1": round(d1 / n, 4), "doc8": round(d8 / n, 4),
         "ms_per_q": round(dt / n * 1000, 1), "embedded": rep.embedded,
         "per": {t: [round(v[0] / v[2], 3), round(v[1] / v[2], 3), v[2]] for t, v in per.items()}}
    out[tag] = r
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"{tag:22} n={n:4} doc1={r['doc1']:.3f} doc8={r['doc8']:.3f} {r['ms_per_q']}ms/q", flush=True)
    return r


print(f"FULL={len(qs_all)}  SAMPLE={len(qs_sample)} (KorMapleQA v2 answerable, local only)\n", flush=True)
# Reranker gain first (MiniLM index is already embedded — no wait): the jina
# cross-encoder is embedder-agnostic, so MiniLM ± jina validates the mechanism.
run("MiniLM full", "benchmarks/work/index-maple_real-local", "fastembed", False, qs_all)
run("MiniLM sample", "benchmarks/work/index-maple_real-local", "fastembed", False, qs_sample)
run("MiniLM+jina sample", "benchmarks/work/index-maple_real-local", "fastembed", True, qs_sample)
# Harrier last — the provider change re-stamps the index signature, forcing a
# one-time re-embed of ~33k chunks via llama.cpp (slow, but migrates the index).
run("Harrier full", "benchmarks/work/index-maple_real-harrier-q8", "llamacpp", False, qs_all)
run("Harrier sample", "benchmarks/work/index-maple_real-harrier-q8", "llamacpp", False, qs_sample)
run("Harrier+jina sample", "benchmarks/work/index-maple_real-harrier-q8", "llamacpp", True, qs_sample)
print("\nsaved -> " + str(OUT))
