"""Does a stronger LOCAL text embedder close the keyless Korean gap?

Re-embeds maple_real with Ollama's Qwen3-Embedding-0.6B (1024d) and re-runs
KorMapleQA, so the local-regime doc8 (MiniLM 384d baseline ~0.76) can be
compared against the Gemini-embedding ceiling (~0.91) WITHOUT any multimodal
2B model or torch dependency. Retrieval-only; no generator needed.

    python benchmarks/embed_swap_kormapleqa.py
"""
import json, sys, time
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from collections import defaultdict
from pathlib import Path
from common import DATA, WORK, prewarm_queries
from lemory.config import LemoryConfig
from lemory.engine import Engine
from lemory.retrieval.search import hybrid_search
import re

def norm(s): return re.sub(r"[^\w가-힣]+", "", s.lower())

cfg = LemoryConfig(vault=DATA/"maple_real"/"vault",
                   data_dir=WORK/"index-maple_real-qwen3",
                   provider="ollama",
                   ollama_embed_model="qwen3-embedding:0.6b",
                   ollama_embed_dim=1024)
eng = Engine(cfg)
t0=time.time()
rep = eng.index()
print(f"re-embed: chunks={eng.store.chunk_count()} embedded={rep.embedded} ({time.time()-t0:.0f}s)", flush=True)

qs = [json.loads(l) for l in (DATA/"kormapleqa"/"questions.jsonl").read_text().splitlines()
      if json.loads(l).get("answerable", True)]
prewarm_queries(eng, [q["q"] for q in qs])
per = defaultdict(lambda: [0,0,0])  # doc1, doc8, n
for q in qs:
    hits = hybrid_search(eng, q["q"], k=8, mode="hybrid").hits
    titles = [h.title for h in hits]; gold = q["gold_notes"]
    st = per[q["type"]]
    st[0] += bool(titles and titles[0] in gold)
    st[1] += any(t in gold for t in titles)
    st[2] += 1
tot=[sum(v[i] for v in per.values()) for i in range(3)]
print(f"\nQwen3-Embedding-0.6B (local, 1024d):  all doc1={tot[0]/tot[2]:.3f} doc8={tot[1]/tot[2]:.3f}", flush=True)
for t,v in sorted(per.items()):
    print(f"  {t:9s} doc1={v[0]/v[2]:.3f} doc8={v[1]/v[2]:.3f}", flush=True)
print("\nref: MiniLM-384d local doc8=0.763  |  Gemini-768d doc8=0.906")
