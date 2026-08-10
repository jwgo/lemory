"""Hindsight (vectorize-io, pip `hindsight-api`) on the shared Korean harness.

Same corpus · same questions · both fully local · LLM 0회 for BOTH sides:
Hindsight runs its OWN officially supported no-LLM configuration
(`HINDSIGHT_API_LLM_PROVIDER=none` → chunks-mode retain, per their
none_llm.py docstring), embedded PostgreSQL (pg0), local embedders.

Three configs are measured:
  default        BAAI/bge-small-en-v1.5 + ms-marco CE reranker — what
                 `pip install hindsight-api` gives out of the box
  ml_e5          intfloat/multilingual-e5-small — their supported
                 multilingual option (same model family as Lemory's
                 Korean embedder), reranker at default (on)
  ml_e5_norerank same, with the English cross-encoder disabled — in case
                 the ms-marco CE hurts Korean ranking

Reproduce (hindsight needs its own venv; pg0's initdb refuses root, so run
as an unprivileged user):
    uv venv /tmp/hsenv && uv pip install hindsight-api --python /tmp/hsenv/bin/python
    python benchmarks/run_hindsight_korean.py --export /tmp/korbench.json
    HINDSIGHT_API_LLM_PROVIDER=none HINDSIGHT_API_ENABLE_OBSERVATIONS=false \
        /tmp/hsenv/bin/python benchmarks/run_hindsight_korean.py \
        --adapter /tmp/korbench.json default /tmp/out.json
    # ml_e5 / ml_e5_norerank: add HINDSIGHT_API_EMBEDDINGS_LOCAL_MODEL=
    # intfloat/multilingual-e5-small (and HINDSIGHT_API_ENABLE_RERANKING=false)

The --adapter path imports ONLY hindsight_api (runs inside their venv);
--export imports only the Lemory harness. Results land next to the other
challenger rows in benchmarks/work/.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path


# ---------------------------------------------------------------- adapter
# (runs inside the hindsight venv · no lemory imports on this path)
async def _run_hindsight(corpus, questions, gold, config_name):
    from hindsight_api import MemoryEngine
    from hindsight_api.models import RequestContext

    memory = MemoryEngine()
    await memory.initialize()
    bank = f"korbench_{config_name}"
    ctx = RequestContext()
    try:
        await memory.delete_bank(bank, request_context=ctx)
    except Exception:
        pass

    t0 = time.perf_counter()
    for i, text in enumerate(corpus):
        await memory.retain_async(bank_id=bank, content=text,
                                  document_id=f"p{i:04d}", request_context=ctx)
    ingest_s = time.perf_counter() - t0

    # chunks-mode fact text IS the paragraph (or a chunk of it) → map by prefix
    prefix = {c[:80]: i for i, c in enumerate(corpus)}
    hit, invalid, lat = 0, 0, []
    for q, g in zip(questions, gold):
        t = time.perf_counter()
        try:
            r = await memory.recall_async(bank_id=bank, query=q,
                                          request_context=ctx)
        except Exception:
            invalid += 1
            continue
        lat.append(time.perf_counter() - t)
        results = getattr(r, "results", None) or []
        if results:
            text = getattr(results[0], "text", "") or ""
            got = prefix.get(text[:80])
            if got is None:  # a chunk may start mid-paragraph · containment scan
                for p, idx in prefix.items():
                    if text[:60] and text[:60] in corpus[idx]:
                        got = idx
                        break
            if got == g:
                hit += 1
    await memory.close()
    n = len(questions) - invalid
    return {"config": config_name, "recall@1": round(hit / max(1, n), 4),
            "p50_ms": round(sorted(lat)[len(lat) // 2] * 1000, 1) if lat else None,
            "ingest_s": round(ingest_s, 1), "invalid": invalid, "answered": n}


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--adapter":
        data = json.loads(Path(sys.argv[2]).read_text())
        out = asyncio.new_event_loop().run_until_complete(
            _run_hindsight(data["corpus"], data["questions"], data["gold"],
                           sys.argv[3]))
        Path(sys.argv[4]).write_text(json.dumps(out, ensure_ascii=False))
        print(json.dumps(out, ensure_ascii=False))
        return
    if len(sys.argv) >= 2 and sys.argv[1] == "--export":
        sys.path.insert(0, str(Path(__file__).parent))
        from harness_korean import load_korquad

        corpus, questions, gold = load_korquad(120, cap=None)
        Path(sys.argv[2]).write_text(json.dumps(
            {"corpus": corpus, "questions": questions, "gold": gold},
            ensure_ascii=False))
        print(f"exported corpus={len(corpus)} questions={len(questions)}")
        return
    print(__doc__)


if __name__ == "__main__":
    main()
