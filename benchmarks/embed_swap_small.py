"""Does Qwen3-Embedding-0.6B (local, Ollama) beat MiniLM-384d on the SMALL
corpora? Fast re-embed (hundreds of chunks, not 33k) for a directional read
on whether fixing the local embedder to Qwen closes the keyless gap.

    python benchmarks/embed_swap_small.py
"""
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import DATA, WORK, full_support_metrics, prewarm_queries, rank_metrics
from lemory.config import LemoryConfig
from lemory.engine import Engine
from lemory.retrieval.search import hybrid_search

for name in ("multihop", "law", "maple"):
    vault = DATA/name/"vault"
    qs = json.loads((DATA/name/"questions.json").read_text())
    cfg = LemoryConfig(vault=vault, data_dir=WORK/f"index-{name}-qwen3",
                       provider="ollama", ollama_embed_model="qwen3-embedding:0.6b",
                       ollama_embed_dim=1024)
    eng = Engine(cfg); t0=time.time(); rep = eng.index()
    prewarm_queries(eng, [q["q"] for q in qs])
    full = r1 = n = 0
    for q in qs:
        hits = hybrid_search(eng, q["q"], k=8).hits
        titles = {h.title for h in hits}
        gold = set(q["gold_notes"])
        full += gold <= titles
        r1 += bool(hits and hits[0].title in gold)
        n += 1
    print(f"{name:9s} (Qwen3-0.6B) full_support@8={full/n:.3f} recall@1={r1/n:.3f} "
          f"embed={rep.embedded} ({time.time()-t0:.0f}s)", flush=True)
