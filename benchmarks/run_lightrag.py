"""External competitor: LightRAG (HKU, EMNLP 2025 — 10k+ stars) on the
multi-hop vault, same harness as mem0/cognee/supermemory.

Wiring: LightRAG's extraction LLM = gemini-2.5-flash-lite (same as the cognee
run), embeddings = gemini-embedding-001 @768d (same as Lemory), both behind
the same free-tier rate limiter. Retrieval = its flagship hybrid ("mix") mode
with only_need_context=True, top_k=8.

Metric: answer-in-context — the gold answer string appears in the retrieved
context. NOTE: LightRAG returns one merged context blob (entities + relations
+ source chunks), typically LARGER than the 8 chunks other systems get — this
comparison is generous to LightRAG, which we accept and disclose.

Run:  python benchmarks/run_lightrag.py     (ingest is resumable; ~30-60 min
      of extraction LLM calls on the free tier the first time)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from common import DATA, WORK, answer_in_text, load_env, save_json  # noqa: E402

load_env()
LR_DIR = WORK / "lightrag"
LR_DIR.mkdir(parents=True, exist_ok=True)

from lemory.providers.gemini import GeminiClient  # noqa: E402

VAULT = DATA / "multihop" / "vault"
K = 8
STATE = LR_DIR / "state.json"

_llm = GeminiClient(api_key=os.environ["GEMINI_API_KEY"], llm_rpm=8)


async def llm_model_func(prompt, system_prompt=None, history_messages=None, **kwargs) -> str:
    def _call():
        return _llm.generate(prompt, system=system_prompt,
                             model="gemini-2.5-flash-lite",
                             max_output_tokens=4096, temperature=0.0)
    return await asyncio.get_event_loop().run_in_executor(None, _call)


async def embedding_func(texts: list[str]) -> np.ndarray:
    def _call():
        return _llm.embed(texts)
    return await asyncio.get_event_loop().run_in_executor(None, _call)


async def build_rag():
    from lightrag import LightRAG
    from lightrag.kg.shared_storage import initialize_pipeline_status
    from lightrag.utils import EmbeddingFunc

    rag = LightRAG(
        working_dir=str(LR_DIR / "store"),
        llm_model_func=llm_model_func,
        embedding_func=EmbeddingFunc(embedding_dim=768, max_token_size=2048,
                                     func=embedding_func),
    )
    await rag.initialize_storages()
    await initialize_pipeline_status()
    return rag


async def main() -> None:
    from lightrag import QueryParam

    rag = await build_rag()
    state = json.loads(STATE.read_text()) if STATE.exists() else {}

    if not state.get("ingested"):
        files = sorted(VAULT.glob("*.md"))
        print(f"inserting {len(files)} notes (entity extraction — the LLM-heavy part)...")
        t0 = time.time()
        texts, ids = [], []
        for f in files:
            texts.append(f"# {f.stem}\n\n{f.read_text(encoding='utf-8')}")
            ids.append(f.stem)
        await rag.ainsert(texts, ids=ids, file_paths=[f.name for f in files])
        print(f"insert done in {time.time()-t0:.0f}s")
        state["ingested"] = True
        STATE.write_text(json.dumps(state))

    questions = json.loads((DATA / "multihop" / "questions.json").read_text())
    aic, by_hops, latencies = [], {1: [], 2: []}, []
    for i, q in enumerate(questions):
        t0 = time.time()
        ctx = await rag.aquery(q["q"], param=QueryParam(
            mode="mix", only_need_context=True, top_k=K, chunk_top_k=K))
        latencies.append(time.time() - t0)
        ok = answer_in_text(str(ctx), q["answers"])
        aic.append(ok)
        by_hops[q["hops"]].append(ok)
        if (i + 1) % 10 == 0:
            print(f"query {i+1}/{len(questions)} — running aic {sum(aic)/len(aic):.3f}")

    result = {
        "answer_in_context@8": sum(aic) / len(aic),
        "aic_1hop": sum(by_hops[1]) / max(1, len(by_hops[1])),
        "aic_2hop": sum(by_hops[2]) / max(1, len(by_hops[2])),
        "p50_latency_ms": sorted(latencies)[len(latencies) // 2] * 1000,
        "note": "mix mode, only_need_context, merged blob (generous vs 8-chunk systems)",
    }
    print("lightrag:", json.dumps(result, indent=2))
    save_json(WORK / "results_lightrag.json", result)


if __name__ == "__main__":
    asyncio.run(main())
