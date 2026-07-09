"""LongMemEval_S (cleaned) — stratified 100-question judged evaluation.

Each LongMemEval question ships its own ~50-session haystack (~115k tokens)
with per-session dates; abilities: single-session (user/assistant/preference),
multi-session, temporal-reasoning, knowledge-update, plus abstention variants
(question_id ending '_abs', gold = the information is not there).

Adapter: per-question vault of dated session notes; retrieval top-k; the same
generator/judge protocol as LOCOMO/DMR. Abstention is graded in code: correct
iff the model replies unknown. Checkpointed per (system, question).

    python benchmarks/run_longmemeval.py           # lemory + vector
    python benchmarks/run_longmemeval.py 20        # first 20 of the sample
"""

from __future__ import annotations

import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import WORK, load_env, save_json

from lemory.config import LemoryConfig
from lemory.engine import Engine
from lemory.providers.gemini import GeminiClient
from lemory.retrieval.answer import build_context, build_prompt
from run_locomo import JUDGE_PROMPT

DATA_FILE = Path(__file__).parent / "data" / "longmemeval" / "longmemeval_s_cleaned.json"
OUT = WORK / "longmemeval"
K = 10
N_SAMPLE = 100
SEED = 41
GEN_MODEL = "gemini-2.5-flash"

SYSTEMS = {
    "lemory": dict(mode="hybrid", graph=True),
    "vector": dict(mode="vector", graph=False),
}

GEN_SYSTEM = (
    "You answer questions about the user's past chat sessions using ONLY the "
    "provided dated session notes. Use the note dates to resolve relative time "
    "expressions, and when information changed across sessions answer with the "
    "LATEST state. Reply with the shortest exact answer (a few words, or a "
    "date like '7 May 2023', or a comma-separated list if several items are "
    "asked). No explanation. Reply exactly 'unknown' if the sessions do not "
    "contain the answer."
)

PREF_SYSTEM = (
    "You are the user's assistant. Respond helpfully to their request, "
    "personalizing your response using what the provided dated session notes "
    "reveal about the user's situation, plans, and preferences. Keep it to "
    "2-4 sentences."
)

PREF_JUDGE = """You are grading whether an assistant response is personalized correctly.

USER REQUEST: {q}
PERSONALIZATION RUBRIC (what a good response should reflect): {gold}
ASSISTANT RESPONSE: {pred}

Does the response reflect the preference/context described in the rubric?
Reply with exactly one word: yes or no."""

UNKNOWN_MARKERS = ("unknown", "don't know", "not provided", "no information", "cannot")


def sample_questions() -> list[dict]:
    data = json.loads(DATA_FILE.read_text())
    rng = random.Random(SEED)
    by_type: dict[str, list] = {}
    for q in data:
        t = q["question_type"] + ("_abs" if str(q["question_id"]).endswith("_abs") else "")
        by_type.setdefault(t, []).append(q)
    total = sum(len(v) for v in by_type.values())
    sample = []
    for t, pool in sorted(by_type.items()):
        n = max(2, round(N_SAMPLE * len(pool) / total))
        rng.shuffle(pool)
        sample.extend(pool[:n])
    rng.shuffle(sample)
    return sample[:N_SAMPLE]


def build_vault(q: dict) -> Path:
    vault = OUT / "vaults" / str(q["question_id"])
    if vault.exists() and any(vault.glob("*.md")):
        return vault
    vault.mkdir(parents=True, exist_ok=True)
    dates = q.get("haystack_dates") or []
    for i, sess in enumerate(q["haystack_sessions"]):
        date = str(dates[i])[:10].replace("/", "-") if i < len(dates) else ""
        lines = [f"{t.get('role', '?')}: {t.get('content', '')}" for t in sess]
        fm = f"---\ndate: {date}\n---\n" if date else ""
        (vault / f"Session {i+1:03d}.md").write_text(
            fm + f"# Session {i+1} ({date})\n\n" + "\n".join(lines), encoding="utf-8")
    return vault


def load_state() -> dict:
    state = {}
    f = OUT / "preds.jsonl"
    if f.exists():
        for line in f.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                state[(r["system"], r["qid"])] = r
    return state


def append_state(row: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "preds.jsonl", "a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main(limit: int | None = None) -> None:
    load_env()
    sample = sample_questions()
    if limit:
        sample = sample[:limit]
    state = load_state()
    judge = GeminiClient(api_key=os.environ["GEMINI_API_KEY"], llm_model=GEN_MODEL,
                         llm_fallback_model="gemini-2.5-flash", llm_rpm=120)

    for qi, q in enumerate(sample):
        qid = str(q["question_id"])
        todo = [s for s in SYSTEMS if (s, qid) not in state]
        if not todo:
            continue
        vault = build_vault(q)
        cfg = LemoryConfig(vault=vault, data_dir=OUT / "index" / qid,
                           llm_model=GEN_MODEL, llm_rpm=120, embed_rpm=240)
        eng = Engine(cfg)
        rep = eng.index()
        if rep.embedded:
            print(f"  {qid}: {rep.chunks} chunks ({rep.embedded} embedded, {rep.seconds:.0f}s)", flush=True)
        is_abs = qid.endswith("_abs")
        is_pref = q["question_type"] == "single-session-preference"
        q_date = str(q.get("question_date", ""))[:10]
        # the official protocol anchors relative-time questions on question_date
        question = (f"(Today is {q_date}.) " if q_date else "") + q["question"]
        for sys_name in todo:
            hits = eng.search(q["question"], k=K, **SYSTEMS[sys_name])
            ctx = build_context(hits, max_chars=13000)
            pred = eng.llm.generate(
                build_prompt(ctx, question),
                system=PREF_SYSTEM if is_pref else GEN_SYSTEM,
                temperature=0.0, max_output_tokens=200 if is_pref else 64,
            ).strip()
            if is_abs:
                correct = int(any(m in pred.lower() for m in UNKNOWN_MARKERS))
            else:
                jp = PREF_JUDGE if is_pref else JUDGE_PROMPT
                verdict = judge.generate(
                    jp.format(q=q["question"], gold=q["answer"], pred=pred),
                    temperature=0.0, max_output_tokens=8,
                ).strip().lower()
                correct = 1 if verdict.startswith("yes") else 0
            row = {"system": sys_name, "qid": qid, "type": q["question_type"],
                   "abs": is_abs, "q": q["question"], "gold": str(q["answer"]),
                   "pred": pred, "judge": correct}
            append_state(row)
            state[(sys_name, qid)] = row
        eng.close()
        if (qi + 1) % 10 == 0:
            for s in SYSTEMS:
                rs = [state[k] for k in state if k[0] == s]
                if rs:
                    print(f"{s}: {len(rs)} acc {sum(x['judge'] for x in rs)/len(rs):.3f}", flush=True)

    results = {}
    for s in SYSTEMS:
        rs = [state[k] for k in state if k[0] == s]
        if not rs:
            continue
        summary = {"n": len(rs), "judge_acc": sum(x["judge"] for x in rs) / len(rs)}
        for t in sorted({r["type"] for r in rs}):
            sub = [r for r in rs if r["type"] == t]
            summary[f"acc_{t}"] = sum(x["judge"] for x in sub) / len(sub)
        ab = [r for r in rs if r["abs"]]
        if ab:
            summary["acc_abstention"] = sum(x["judge"] for x in ab) / len(ab)
        results[s] = summary
        print(s, json.dumps(summary, indent=1))
    save_json(WORK / "results_longmemeval.json", results)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else None)
