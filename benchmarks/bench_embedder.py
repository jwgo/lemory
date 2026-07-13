"""Measure any Ollama embedding model on KorMapleQA v2 (hybrid doc@8), with a
concurrent embed monkeypatch so the 33k-chunk index build finishes in minutes.

    python benchmarks/bench_embedder.py <ollama_model> <index_tag> "<label>"
    python benchmarks/bench_embedder.py harrier-emb:0.6b maple_real-harrier "Harrier-OSS-0.6B"
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from common import DATA, WORK, prewarm_queries  # noqa: E402
import lemory.providers.ollama as ollama_mod  # noqa: E402
from lemory.providers.ollama import normalize_embeddings  # noqa: E402
from lemory.config import LemoryConfig  # noqa: E402
from lemory.engine import Engine  # noqa: E402
from lemory.retrieval.search import hybrid_search  # noqa: E402

MODEL = sys.argv[1] if len(sys.argv) > 1 else "harrier-emb:0.6b"
TAG = sys.argv[2] if len(sys.argv) > 2 else "maple_real-harrier"
LABEL = sys.argv[3] if len(sys.argv) > 3 else MODEL
WORKERS, B = 8, 48


def _concurrent_embed(self, texts, task_type="RETRIEVAL_DOCUMENT"):
    if not texts:
        return np.zeros((0, self.embed_dim), dtype=np.float32)
    out = np.zeros((len(texts), self.embed_dim), dtype=np.float32)
    starts = list(range(0, len(texts), B))

    def do(i):
        batch = [t[:6000] for t in texts[i:i + B]]
        r = self._http.post(f"{self.host}/api/embed",
                            json={"model": self.embed_model, "input": batch},
                            timeout=300)
        r.raise_for_status()
        return i, np.asarray(r.json()["embeddings"], dtype=np.float32)

    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for i, arr in ex.map(do, starts):
            out[i:i + arr.shape[0]] = arr
    return normalize_embeddings(out)


ollama_mod.OllamaClient.embed = _concurrent_embed


def main():
    cfg = LemoryConfig(vault=DATA / "maple_real" / "vault",
                       data_dir=WORK / f"index-{TAG}",
                       provider="ollama", ollama_embed_model=MODEL,
                       ollama_embed_dim=1024)
    eng = Engine(cfg)
    t0 = time.time()
    rep = eng.index()
    print(f"index: chunks={eng.store.chunk_count()} embedded={rep.embedded} "
          f"({time.time() - t0:.0f}s, concurrent x{WORKERS})", flush=True)

    qs = [json.loads(l) for l in (DATA / "kormapleqa" / "questions.jsonl").read_text().splitlines()
          if json.loads(l).get("answerable", True)]
    prewarm_queries(eng, [q["q"] for q in qs])
    per = defaultdict(lambda: [0, 0, 0, 0])  # doc1, doc8, fs, n
    lat = []
    for q in qs:
        t = time.time()
        hits = hybrid_search(eng, q["q"], k=8, mode="hybrid").hits
        lat.append(time.time() - t)
        titles = [h.title for h in hits]
        gold = q["gold_notes"]
        st = per[q["type"]]
        st[0] += bool(titles and titles[0] in gold)
        st[1] += any(t2 in gold for t2 in titles)
        st[2] += set(gold) <= set(titles) if q["type"] == "twohop" else 0
        st[3] += 1
    tot = [sum(v[i] for v in per.values()) for i in range(4)]
    lat.sort()
    res = {"label": LABEL, "model": MODEL, "all_doc1": round(tot[0] / tot[3], 4),
           "all_doc8": round(tot[1] / tot[3], 4),
           "p50_ms": round(lat[len(lat) // 2] * 1000, 2), "n": tot[3],
           "by_type": {t: {"doc1": round(v[0] / v[3], 4), "doc8": round(v[1] / v[3], 4),
                           "fs": round(v[2] / v[3], 4) if t == "twohop" else None, "n": v[3]}
                       for t, v in sorted(per.items())}}
    print(f"\n=== {LABEL} (local, 1024d) ===", flush=True)
    print(f"  all  doc1={res['all_doc1']} doc8={res['all_doc8']} p50={res['p50_ms']}ms  n={res['n']}")
    for t, v in res["by_type"].items():
        fs = f" fs={v['fs']}" if v["fs"] is not None else ""
        print(f"  {t:9s} doc1={v['doc1']} doc8={v['doc8']}{fs}")
    print("\n  ref: MiniLM-384d 0.788  |  Qwen3-emb-0.6B ?  |  Gemini 0.906")
    (WORK / f"bench_embed_{TAG}.json").write_text(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
