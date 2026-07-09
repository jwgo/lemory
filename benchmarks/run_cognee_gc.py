"""cognee GRAPH_COMPLETION e2e: let cognee answer with its own graph+LLM
pipeline (its intended usage), scored with the same F1/EM as everyone else.
Uses the already-cognified dataset from run_cognee.py."""

from __future__ import annotations

import asyncio
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import DATA, WORK, best_f1, load_env, normalize_answer, save_json

load_env()
COGNEE_DIR = WORK / "cognee"
os.environ.setdefault("LLM_PROVIDER", "gemini")
os.environ.setdefault("LLM_MODEL", "gemini/gemini-2.5-flash-lite")
os.environ.setdefault("LLM_API_KEY", os.environ["GEMINI_API_KEY"])
os.environ.setdefault("EMBEDDING_PROVIDER", "gemini")
os.environ.setdefault("EMBEDDING_MODEL", "gemini/gemini-embedding-001")
os.environ.setdefault("EMBEDDING_API_KEY", os.environ["GEMINI_API_KEY"])
os.environ.setdefault("EMBEDDING_DIMENSIONS", "768")
os.environ.setdefault("LLM_RATE_LIMIT_ENABLED", "true")
os.environ.setdefault("LLM_RATE_LIMIT_REQUESTS", "12")
os.environ.setdefault("LLM_RATE_LIMIT_INTERVAL", "60")
os.environ.setdefault("ENABLE_BACKEND_ACCESS_CONTROL", "false")
os.environ.setdefault("SYSTEM_ROOT_DIRECTORY", str(COGNEE_DIR / "system"))
os.environ.setdefault("DATA_ROOT_DIRECTORY", str(COGNEE_DIR / "data"))
os.environ.setdefault("TELEMETRY_DISABLED", "1")

import cognee  # noqa: E402
from cognee.modules.search.types import SearchType  # noqa: E402

DATASET = "lemorybench"
N_E2E = 30


async def main() -> None:
    questions = json.loads((DATA / "multihop" / "questions.json").read_text())
    rng = random.Random(11)
    two = [q for q in questions if q["hops"] == 2]
    one = [q for q in questions if q["hops"] == 1]
    rng.shuffle(two), rng.shuffle(one)
    n2 = min(len(two), int(N_E2E * 0.7))
    sample = two[:n2] + one[: N_E2E - n2]

    f1s, ems, details = [], [], []
    for i, q in enumerate(sample):
        try:
            res = await cognee.search(
                query_text=q["q"] + " Reply with the shortest exact answer span only.",
                query_type=SearchType.GRAPH_COMPLETION,
                datasets=[DATASET],
            )
            pred = str(res[0]) if isinstance(res, list) and res else str(res)
        except Exception as e:
            pred = f"<error: {str(e)[:60]}>"
        f1 = best_f1(pred, q["answers"])
        em = float(any(normalize_answer(g) in normalize_answer(pred) for g in q["answers"]))
        f1s.append(f1), ems.append(em)
        details.append({"q": q["q"], "gold": q["answers"], "pred": pred[:300], "f1": f1})
        if (i + 1) % 5 == 0:
            print(f"{i+1}/{len(sample)} f1so far={sum(f1s)/len(f1s):.3f}")
    out = {"f1": sum(f1s) / len(f1s), "contain_em": sum(ems) / len(ems), "n": len(sample)}
    print("cognee graph_completion e2e:", out)
    save_json(WORK / "results_cognee_gc.json", {"e2e_graph_completion": out, "details": details})


if __name__ == "__main__":
    asyncio.run(main())
