"""FULL LongMemEval_S (cleaned, all 500 questions) — retrieval Recall@k,
zero API calls.

Why this exists: the field's headline currency is "R@5 on LongMemEval"
measured with a local embedder and no API (MemPalace: "96.6% R@5, zero API
calls"). This runs the identical protocol on the ENTIRE cleaned S set — no
stratified sampling, no LLM generator/judge — so the number is directly
comparable and reproducible on a laptop:

  * per-question vault: one dated Markdown note per haystack session
    (~50 sessions / ~115k tokens each), built by the same adapter as the
    judged benchmark (run_longmemeval.py)
  * embedder: fastembed multilingual MiniLM (Lemory's `local` provider) —
    fully offline, CPU
  * metric: session-level Recall@k — the note(s) of ALL evidence sessions
    appear among the top-k retrieved notes (strict; `any` also reported).
    Abstention questions (question_id ending '_abs') have no evidence by
    construction and are excluded, as in the LongMemEval paper's retrieval
    protocol.

Arms: lemory (hybrid+graph) and vector-only, sharing each question's index.
Checkpointed per question; safe to interrupt and re-run.

    python benchmarks/run_longmemeval_full.py [limit]
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from common import WORK, save_json  # noqa: E402

from lemory.config import LemoryConfig  # noqa: E402
from lemory.engine import Engine  # noqa: E402
from run_longmemeval import DATA_FILE, build_vault  # noqa: E402

OUT = WORK / "longmemeval-full"
KS = (5, 10)
ARMS = {"lemory": dict(mode="hybrid", graph=True),
        "vector": dict(mode="vector", graph=False)}


def note_for_session(q: dict, sid: str) -> str | None:
    try:
        i = q["haystack_session_ids"].index(sid)
    except ValueError:
        return None
    return f"Session {i+1:03d}.md"


def main(limit: int | None = None) -> None:
    questions = json.loads(DATA_FILE.read_text())
    questions = [q for q in questions if not str(q["question_id"]).endswith("_abs")]
    if limit:
        questions = questions[:limit]
    OUT.mkdir(parents=True, exist_ok=True)
    ckpt_file = OUT / "rows.jsonl"
    done = set()
    if ckpt_file.exists():
        for line in ckpt_file.read_text().splitlines():
            if line.strip():
                done.add(json.loads(line)["qid"])

    t_start = time.time()
    for qi, q in enumerate(questions):
        qid = str(q["question_id"])
        if qid in done:
            continue
        vault = build_vault(q)
        data_dir = OUT / "idx" / qid
        cfg = LemoryConfig(vault=vault, data_dir=data_dir, provider="local")
        eng = Engine(cfg)
        try:
            eng.index()
            gold = {note_for_session(q, s) for s in q["answer_session_ids"]}
            gold.discard(None)
            row = {"qid": qid, "type": q["question_type"], "n_gold": len(gold)}
            for arm, kw in ARMS.items():
                hits = eng.search(q["question"], k=max(KS), **kw)
                # collapse chunk hits to ranked unique notes
                seen: list[str] = []
                for h in hits:
                    if h.path not in seen:
                        seen.append(h.path)
                for k in KS:
                    top = set(seen[:k])
                    row[f"{arm}_all@{k}"] = bool(gold) and gold <= top
                    row[f"{arm}_any@{k}"] = bool(gold & top)
        finally:
            eng.close()
            shutil.rmtree(data_dir, ignore_errors=True)  # 500 DBs would eat disk
        with open(ckpt_file, "a") as fh:
            fh.write(json.dumps(row) + "\n")
        if (qi + 1) % 20 == 0:
            el = time.time() - t_start
            print(f"{qi+1}/{len(questions)}  ({el/60:.0f} min elapsed)")

    rows = [json.loads(x) for x in ckpt_file.read_text().splitlines() if x.strip()]
    rows = [r for r in rows if r["n_gold"] > 0]
    summary: dict = {"questions": len(rows)}
    for arm in ARMS:
        for k in KS:
            summary[f"{arm}_recall@{k}"] = sum(r[f"{arm}_all@{k}"] for r in rows) / len(rows)
            summary[f"{arm}_any@{k}"] = sum(r[f"{arm}_any@{k}"] for r in rows) / len(rows)
    by_type: dict = {}
    for r in rows:
        by_type.setdefault(r["type"], []).append(r["lemory_all@5"])
    summary["lemory_recall@5_by_type"] = {t: sum(v) / len(v) for t, v in by_type.items()}
    print(json.dumps(summary, indent=2))
    save_json(OUT / "summary.json", summary)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else None)
