"""External competitor: cognee (OSS) on the multi-hop vault.

cognee is configured with the same Gemini models Lemory uses (flash-lite for
its cognify/graph-extraction LLM, gemini-embedding-001 @768d) and its default
local stores (LanceDB vectors, Kuzu graph, SQLite relational). Notes are added
as files, cognify builds its knowledge graph, and retrieval is its CHUNKS
search. Shared metrics (same as the mem0 comparison):

  * answer-in-context@8 — gold answer string appears in the top-8 texts
  * end-to-end F1 with the identical Gemini generator and prompt

Run:  python benchmarks/run_cognee.py            (ingest+cognify+eval, resumable)
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import DATA, WORK, answer_in_text, best_f1, load_env, normalize_answer, save_json

load_env()
COGNEE_DIR = WORK / "cognee"
COGNEE_DIR.mkdir(parents=True, exist_ok=True)

# configure BEFORE importing cognee
os.environ.setdefault("LLM_PROVIDER", "gemini")
os.environ.setdefault("LLM_MODEL", "gemini/gemini-2.5-flash-lite")
os.environ.setdefault("LLM_API_KEY", os.environ["GEMINI_API_KEY"])
os.environ.setdefault("EMBEDDING_PROVIDER", "gemini")
os.environ.setdefault("EMBEDDING_MODEL", "gemini/gemini-embedding-001")
os.environ.setdefault("EMBEDDING_API_KEY", os.environ["GEMINI_API_KEY"])
os.environ.setdefault("EMBEDDING_DIMENSIONS", "768")
# stay inside the free tier instead of blasting 429s
os.environ.setdefault("LLM_RATE_LIMIT_ENABLED", "true")
os.environ.setdefault("LLM_RATE_LIMIT_REQUESTS", "12")
os.environ.setdefault("LLM_RATE_LIMIT_INTERVAL", "60")
os.environ.setdefault("EMBEDDING_RATE_LIMIT_ENABLED", "true")
os.environ.setdefault("EMBEDDING_RATE_LIMIT_REQUESTS", "80")
os.environ.setdefault("EMBEDDING_RATE_LIMIT_INTERVAL", "60")
os.environ.setdefault("ENABLE_BACKEND_ACCESS_CONTROL", "false")
os.environ.setdefault("SYSTEM_ROOT_DIRECTORY", str(COGNEE_DIR / "system"))
os.environ.setdefault("DATA_ROOT_DIRECTORY", str(COGNEE_DIR / "data"))
os.environ.setdefault("TELEMETRY_DISABLED", "1")

import cognee  # noqa: E402
from cognee.modules.search.types import SearchType  # noqa: E402

VAULT = DATA / "multihop" / "vault"
DATASET = "lemorybench"
K = 8
N_E2E = 30
STATE = COGNEE_DIR / "state.json"


def state() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def mark(key: str) -> None:
    s = state()
    s[key] = True
    STATE.write_text(json.dumps(s))


async def ingest() -> None:
    if state().get("cognified"):
        print("already cognified, skipping ingest")
        return
    files = sorted(str(p) for p in VAULT.glob("*.md"))
    print(f"adding {len(files)} notes...")
    t0 = time.time()
    await cognee.add(files, dataset_name=DATASET)
    print(f"add done in {time.time()-t0:.0f}s; cognify (this is the LLM-heavy part)...")
    t0 = time.time()
    await cognee.cognify(datasets=[DATASET])
    print(f"cognify done in {time.time()-t0:.0f}s")
    mark("cognified")


def result_texts(results) -> list[str]:
    out = []
    for r in results:
        if isinstance(r, dict):
            out.append(str(r.get("text") or r.get("content") or r.get("chunk") or r))
        else:
            out.append(str(r))
    return out


async def evaluate() -> None:
    questions = json.loads((DATA / "multihop" / "questions.json").read_text())

    # ---------- retrieval: answer-in-context@8 ----------
    aic_flags, by_hops = [], {1: [], 2: []}
    latencies = []
    for i, q in enumerate(questions):
        t = time.time()
        res = await cognee.search(
            query_text=q["q"], query_type=SearchType.CHUNKS, datasets=[DATASET], top_k=K
        )
        latencies.append(time.time() - t)
        texts = result_texts(res)[:K]
        ok = any(answer_in_text(t_, q["answers"]) for t_ in texts)
        aic_flags.append(ok)
        by_hops[q["hops"]].append(ok)
        if (i + 1) % 10 == 0:
            print(f"search {i+1}/{len(questions)}")
    retrieval = {
        "answer_in_context@8": sum(aic_flags) / len(aic_flags),
        "aic_1hop": sum(by_hops[1]) / max(1, len(by_hops[1])),
        "aic_2hop": sum(by_hops[2]) / max(1, len(by_hops[2])),
        "p50_latency_ms": sorted(latencies)[len(latencies) // 2] * 1000,
    }
    print("cognee retrieval:", retrieval)

    # ---------- e2e: same sample + generator prompt as run_e2e.py ----------
    from lemory.providers.gemini import GeminiClient

    rng = random.Random(11)
    two = [q for q in questions if q["hops"] == 2]
    one = [q for q in questions if q["hops"] == 1]
    rng.shuffle(two), rng.shuffle(one)
    n2 = min(len(two), int(N_E2E * 0.7))
    sample = two[:n2] + one[: N_E2E - n2]

    gen = GeminiClient(api_key=os.environ["GEMINI_API_KEY"], llm_rpm=8)
    f1s, ems, details = [], [], []
    for i, q in enumerate(sample):
        res = await cognee.search(
            query_text=q["q"], query_type=SearchType.CHUNKS, datasets=[DATASET], top_k=K
        )
        ctx = "\n".join(f"[{j+1}] {t_}" for j, t_ in enumerate(result_texts(res)[:K]))
        pred = gen.generate(
            f"NOTES:\n{ctx}\n\nQUESTION: {q['q']}\n\nANSWER:",
            system=(
                "Answer the question using ONLY the notes. Reply with the shortest exact "
                "answer span (a few words), no explanation. If the notes don't contain the "
                "answer, reply exactly: unknown"
            ),
            temperature=0.0, max_output_tokens=64,
        ).strip()
        f1 = best_f1(pred, q["answers"])
        em = float(any(normalize_answer(g) in normalize_answer(pred) or
                       normalize_answer(pred) == normalize_answer(g) for g in q["answers"]))
        f1s.append(f1), ems.append(em)
        details.append({"q": q["q"], "gold": q["answers"], "pred": pred, "f1": f1})
        if (i + 1) % 10 == 0:
            print(f"e2e {i+1}/{len(sample)}")
    e2e = {"f1": sum(f1s) / len(f1s), "contain_em": sum(ems) / len(ems), "n": len(sample)}
    print("cognee e2e:", e2e)

    save_json(WORK / "results_cognee.json", {"retrieval": retrieval, "e2e": e2e, "details": details})


async def main() -> None:
    await ingest()
    await evaluate()


if __name__ == "__main__":
    asyncio.run(main())
