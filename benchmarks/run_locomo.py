"""LOCOMO evaluation: Lemory vs naive-RAG baseline, mem0-style protocol.

Per question: retrieve top-k from that conversation's session notes, generate
a short answer (same Gemini generator/prompt for every system), grade with an
LLM judge that sees only (question, gold, prediction). Also reports
evidence-recall@k (gold dialog turns found in retrieved text — no LLM).

Every (question, system) result is checkpointed to preds.jsonl, so quota
interruptions resume instead of restarting.

    python benchmarks/prep_locomo.py
    python benchmarks/run_locomo.py            # both systems
    python benchmarks/run_locomo.py lemory     # one system
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import WORK, load_env, normalize_answer, save_json

from lemory.config import LemoryConfig
from lemory.engine import Engine
from lemory.providers.gemini import GeminiClient
from lemory.retrieval.answer import build_context, build_prompt

OUT = WORK / "locomo"
K = 10
GEN_MODEL = "gemini-2.5-flash-lite"  # free-tier friendly; identical for all systems

SYSTEMS = {
    "lemory": dict(mode="hybrid", graph=True),
    "vector": dict(mode="vector", graph=False),
}

GEN_SYSTEM = (
    "You answer questions about a two-person conversation using ONLY the "
    "provided session notes. Each note is dated — use those dates to resolve "
    "relative time expressions in the dialogue ('last week', 'four years ago', "
    "'next month') into absolute dates or years. Reply with the shortest exact "
    "answer: a few words, a date like '7 May 2023', or a comma-separated list "
    "when the question asks for multiple things — gather ALL matching items "
    "across the notes. No explanation. Reply 'unknown' only when nothing in "
    "the notes answers the question."
)

JUDGE_PROMPT = """You are grading a question-answering system.

QUESTION: {q}
GOLD ANSWER: {gold}
MODEL ANSWER: {pred}

Is the model answer correct? It counts as correct if it conveys the same
information as the gold answer (formatting, phrasing, or extra detail is fine;
for dates, the same day counts even if formatted differently).
Reply with exactly one word: yes or no."""


def load_state() -> dict:
    state = {}
    f = OUT / "preds.jsonl"
    if f.exists():
        for line in f.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                state[(r["system"], r["conv"], r["q"])] = r
    return state


def append_state(row: dict) -> None:
    with open(OUT / "preds.jsonl", "a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


_TURN_IDX: dict[int, dict[str, str]] = {}


def turn_texts(conv_id: int, evidence: list[str]) -> list[str]:
    """Raw texts of gold evidence turns (D{sess}:{turn} ids)."""
    if conv_id not in _TURN_IDX:
        data = json.loads((Path(__file__).parent / "data" / "locomo" / "locomo10.json").read_text())
        c = data[conv_id]["conversation"]
        import re as _re
        idx = {}
        for sk in (k for k in c if _re.fullmatch(r"session_\d+", k)):
            for t in c[sk]:
                idx[t.get("dia_id")] = t.get("text", "") or ""
        _TURN_IDX[conv_id] = idx
    idx = _TURN_IDX[conv_id]
    return [idx[e] for e in evidence if e in idx and idx[e]]


def main(only: str | None = None) -> None:
    load_env()
    eval_set = json.loads((OUT / "eval_set.json").read_text())
    state = load_state()
    judge = GeminiClient(api_key=os.environ["GEMINI_API_KEY"],
                         llm_model=GEN_MODEL, llm_fallback_model="gemini-2.5-flash",
                         llm_rpm=12)

    engines: dict[int, Engine] = {}

    def engine_for(conv: int) -> Engine:
        if conv not in engines:
            cfg = LemoryConfig(
                vault=OUT / "vaults" / f"conv{conv}",
                data_dir=WORK / f"index-locomo-{conv}",
                llm_model=GEN_MODEL, llm_rpm=12,
            )
            engines[conv] = Engine(cfg)
            rep = engines[conv].index()
            if rep.embedded:
                print(f"  conv{conv}: indexed {rep.chunks} chunks ({rep.embedded} embedded)")
        return engines[conv]

    systems = {only: SYSTEMS[only]} if only else SYSTEMS
    for sys_name, opts in systems.items():
        done = 0
        for q in eval_set:
            key = (sys_name, q["conv"], q["q"])
            if key in state:
                continue
            eng = engine_for(q["conv"])
            hits = eng.search(q["q"], k=K, **opts)
            ev_texts = turn_texts(q["conv"], q["evidence"])
            joined = " ".join(h.text for h in hits).lower()
            ev_found = sum(1 for t in ev_texts if t.lower() in joined)
            ctx = build_context(hits, max_chars=12000)
            pred = eng.llm.generate(
                build_prompt(ctx, q["q"]), system=GEN_SYSTEM,
                temperature=0.0, max_output_tokens=64,
            ).strip()
            verdict = judge.generate(
                JUDGE_PROMPT.format(q=q["q"], gold=q["answer"], pred=pred),
                temperature=0.0, max_output_tokens=8,
            ).strip().lower()
            row = {
                "system": sys_name, "conv": q["conv"], "q": q["q"],
                "category": q["category"], "gold": q["answer"], "pred": pred,
                "judge": 1 if verdict.startswith("yes") else 0,
                "ev_found": ev_found, "ev_total": len(ev_texts),
            }
            append_state(row)
            state[key] = row
            done += 1
            if done % 10 == 0:
                so_far = [state[k] for k in state if k[0] == sys_name]
                acc = sum(r["judge"] for r in so_far) / len(so_far)
                print(f"{sys_name}: {len(so_far)}/{len(eval_set)} judge-acc so far {acc:.3f}", flush=True)

    # ---------------- summarize ----------------
    results = {}
    cats = {1: "multi_hop", 2: "temporal", 3: "open_domain", 4: "single_hop"}
    for sys_name in SYSTEMS:
        rows = [r for (s, _, _), r in state.items() if s == sys_name]
        if not rows:
            continue
        summary = {"n": len(rows), "judge_acc": sum(r["judge"] for r in rows) / len(rows)}
        for cat, label in cats.items():
            sub = [r for r in rows if r["category"] == cat]
            if sub:
                summary[f"judge_{label}"] = sum(r["judge"] for r in sub) / len(sub)
        ev_rows = [r for r in rows if r["ev_total"]]
        if ev_rows:
            summary["evidence_recall@10"] = sum(r["ev_found"] / r["ev_total"] for r in ev_rows) / len(ev_rows)
        results[sys_name] = summary
        print(sys_name, json.dumps(summary, indent=1))
    save_json(WORK / "results_locomo.json", results)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else None)
