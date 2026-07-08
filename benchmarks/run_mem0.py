"""External competitor benchmark: mem0 (OSS) with a Gemini backend, on the
multi-hop vault.

mem0 is a memory layer rather than a document KB, so the fairest shared
metric is answer-in-context@8: does the gold answer string appear anywhere in
the top-8 retrieved texts (Lemory chunks / mem0 memories)? That is the
precondition for any downstream generator to answer correctly.

mem0 runs with its default pipeline (LLM fact extraction on add, vector
search on query), same Gemini models as Lemory.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import DATA, SYSTEMS, WORK, answer_in_text, load_env, make_engine, save_json

from lemory.config import LemoryConfig


def answer_in_texts(texts: list[str], answers: list[str]) -> bool:
    return answer_in_text(" ".join(texts), answers)


def eval_lemory_side(questions) -> dict:
    eng = make_engine(DATA / "multihop" / "vault", tag="multihop")
    eng.index()
    out = {}
    for sysname, kw in SYSTEMS.items():
        if sysname == "lemory-nograph":
            continue
        hits_ok = []
        for q in questions:
            hits = eng.search(q["q"], k=8, **kw)
            hits_ok.append(answer_in_texts([h.text for h in hits], q["answers"]))
        out[sysname] = sum(hits_ok) / len(hits_ok)
    return out


def main() -> None:
    load_env()
    questions = json.loads((DATA / "multihop" / "questions.json").read_text())

    state_file = WORK / "results_mem0.json"
    state = json.loads(state_file.read_text()) if state_file.exists() else {}

    from mem0 import Memory

    gemini_key = LemoryConfig().resolved_gemini_key()
    if not gemini_key:
        raise SystemExit("mem0 benchmark needs GEMINI_API_KEY (or GOOGLE_API_KEY)")

    config = {
        "llm": {
            "provider": "gemini",
            "config": {"model": "gemini-2.5-flash", "api_key": gemini_key,
                       "temperature": 0.0},
        },
        "embedder": {
            "provider": "gemini",
            "config": {"model": "models/gemini-embedding-001",
                       "api_key": gemini_key, "embedding_dims": 768},
        },
        "vector_store": {
            "provider": "qdrant",
            "config": {"embedding_model_dims": 768, "path": str(WORK / "mem0_qdrant"),
                       "on_disk": True},
        },
    }
    m = Memory.from_config(config)

    added = set(state.get("added", []))
    vault = DATA / "multihop" / "vault"
    files = sorted(vault.glob("*.md"))
    t_add0 = time.time()
    for i, f in enumerate(files):
        if f.stem in added:
            continue
        text = f.read_text()
        for attempt in range(12):
            try:
                m.add(text, user_id="bench", metadata={"note": f.stem})
                break
            except Exception as e:
                print(f"add {f.stem} failed ({str(e)[:120]}), retry {attempt+1}", flush=True)
                time.sleep(min(45 * (attempt + 1), 150))
        else:
            print(f"giving up on {f.stem}")
        added.add(f.stem)
        state["added"] = sorted(added)
        save_json(state_file, state)
        print(f"add {i+1}/{len(files)} {f.stem}")
    state.setdefault("add_seconds", time.time() - t_add0)

    # retrieval eval (vector search inside mem0; no LLM calls)
    mem0_ok, per_hops = [], {1: [], 2: []}
    t0 = time.time()
    for q in questions:
        res = m.search(q["q"], user_id="bench", limit=8)
        memories = [r["memory"] for r in (res["results"] if isinstance(res, dict) else res)]
        ok = answer_in_texts(memories, q["answers"])
        mem0_ok.append(ok)
        per_hops[q["hops"]].append(ok)
    mem0_ms = 1000 * (time.time() - t0) / len(questions)

    state["answer_in_context@8"] = {"mem0": sum(mem0_ok) / len(mem0_ok)}
    state["mem0_hops"] = {h: (sum(v) / len(v) if v else None) for h, v in per_hops.items()}
    state["mem0_ms_per_query"] = mem0_ms

    lem = eval_lemory_side(questions)
    state["answer_in_context@8"].update(lem)
    save_json(state_file, state)
    print(json.dumps(state["answer_in_context@8"], indent=2))
    print("mem0 by hops:", state["mem0_hops"], f"{mem0_ms:.0f} ms/q")


if __name__ == "__main__":
    main()
