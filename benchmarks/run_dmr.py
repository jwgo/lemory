"""DMR (Deep Memory Retrieval, MemGPT/Zep) — full 500-question evaluation.

Dataset: MemGPT/MSC-Self-Instruct (500 five-session MSC chats; the
`self_instruct` question asks the agent to recall something from an earlier
session, gold answer included). Protocol mirrors MemGPT/Zep: memory over all
prior sessions, judge-graded answer accuracy.

Adapter: one vault per conversation is wasteful at this scale (500 tiny
vaults) — instead each conversation's sessions become notes in a per-question
namespace within ONE store by prefixing titles, and retrieval is scoped by
running one engine per conversation over an in-memory corpus. Sessions carry
synthetic dates from the dataset's `time_back` gaps so date labels exist.

    python benchmarks/run_dmr.py           # lemory + vector, checkpointed
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import WORK, load_env, save_json

from lemory.config import LemoryConfig
from lemory.engine import Engine
from lemory.providers.gemini import GeminiClient
from lemory.retrieval.answer import build_context, build_prompt
from run_locomo import JUDGE_PROMPT, append_state as _append  # reuse judge wording

DATA_FILE = Path(__file__).parent / "data" / "dmr" / "msc_self_instruct.jsonl"
OUT = WORK / "dmr"
K = 8
GEN_MODEL = "gemini-2.5-flash"
TODAY = datetime(2026, 7, 9, 12)

SYSTEMS = {
    "lemory": dict(mode="hybrid", graph=True),
    "vector": dict(mode="vector", graph=False),
}

GEN_SYSTEM = (
    "You answer a memory question about a long two-person conversation between "
    "Speaker 1 and Speaker 2. The question is asked by Speaker 1: 'I'/'my'/'me' "
    "refer to Speaker 1, and 'you'/'your' refer to Speaker 2 — attribute facts "
    "to the correct speaker. Using ONLY the provided dated conversation notes, "
    "reply with the shortest exact answer (a few words), no explanation. "
    "Reply 'unknown' only if the notes don't contain it."
)


def parse_back(tb: str) -> timedelta:
    days = hours = 0
    m = re.search(r"(\d+)\s*day", tb or "")
    if m:
        days = int(m.group(1))
    m = re.search(r"(\d+)\s*hour", tb or "")
    if m:
        hours = int(m.group(1))
    return timedelta(days=days, hours=hours)


def conv_notes(row: dict) -> list[tuple[str, str]]:
    """[(filename, content)] for one conversation: previous sessions + final."""
    notes = []
    prevs = row.get("previous_dialogs", [])
    for i, pd in enumerate(prevs):
        date = (TODAY - parse_back(pd.get("time_back", ""))).date().isoformat()
        lines = []
        for j, t in enumerate(pd.get("dialog", [])):
            speaker = f"Speaker {1 + j % 2}"
            lines.append(f"{speaker}: {t.get('text', '')}")
        notes.append((
            f"Session {i+1:02d}.md",
            f"---\ndate: {date}\n---\n# Session {i+1} ({date})\n\n" + "\n".join(lines),
        ))
    lines = [f"{t.get('id', f'Speaker {1 + j % 2}')}: {t.get('text', '')}"
             for j, t in enumerate(row.get("dialog", []))]
    date = TODAY.date().isoformat()
    notes.append((
        f"Session {len(prevs)+1:02d}.md",
        f"---\ndate: {date}\n---\n# Session {len(prevs)+1} ({date})\n\n" + "\n".join(lines),
    ))
    return notes


def load_state() -> dict:
    state = {}
    f = OUT / "preds.jsonl"
    if f.exists():
        for line in f.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                state[(r["system"], r["conv"])] = r
    return state


def append_state(row: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "preds.jsonl", "a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main(limit: int | None = None) -> None:
    load_env()
    rows = [json.loads(l) for l in open(DATA_FILE)]
    if limit:
        rows = rows[:limit]
    OUT.mkdir(parents=True, exist_ok=True)
    vaults_root = OUT / "vaults"
    state = load_state()
    judge = GeminiClient(api_key=os.environ["GEMINI_API_KEY"], llm_model=GEN_MODEL,
                         llm_fallback_model="gemini-2.5-flash", llm_rpm=120)

    for ci, row in enumerate(rows):
        todo = [s for s in SYSTEMS if (s, ci) not in state]
        if not todo:
            continue
        q = (row.get("self_instruct") or {}).get("B", "").strip()
        gold = (row.get("self_instruct") or {}).get("A", "").strip()
        if not q or not gold:
            continue
        vault = vaults_root / f"conv{ci}"
        vault.mkdir(parents=True, exist_ok=True)
        for fname, content in conv_notes(row):
            f = vault / fname
            if not f.exists():
                f.write_text(content, encoding="utf-8")
        cfg = LemoryConfig(
            vault=vault, data_dir=OUT / "index" / f"conv{ci}",
            llm_model=GEN_MODEL, llm_rpm=120, embed_rpm=300,
        )
        eng = Engine(cfg)
        eng.now = lambda: TODAY.timestamp()
        eng.index()
        for sys_name in todo:
            hits = eng.search(q, k=K, **SYSTEMS[sys_name])
            ctx = build_context(hits, max_chars=10000)
            pred = eng.llm.generate(
                build_prompt(ctx, q), system=GEN_SYSTEM,
                temperature=0.0, max_output_tokens=48,
            ).strip()
            verdict = judge.generate(
                JUDGE_PROMPT.format(q=q, gold=gold, pred=pred),
                temperature=0.0, max_output_tokens=8,
            ).strip().lower()
            r = {"system": sys_name, "conv": ci, "q": q, "gold": gold, "pred": pred,
                 "judge": 1 if verdict.startswith("yes") else 0}
            append_state(r)
            state[(sys_name, ci)] = r
        eng.close()
        n = sum(1 for k in state if k[0] == "lemory")
        if n % 25 == 0:
            for s in SYSTEMS:
                rs = [state[k] for k in state if k[0] == s]
                if rs:
                    print(f"{s}: {len(rs)} acc {sum(x['judge'] for x in rs)/len(rs):.3f}", flush=True)

    results = {}
    for s in SYSTEMS:
        rs = [state[k] for k in state if k[0] == s]
        if rs:
            results[s] = {"n": len(rs), "judge_acc": sum(x["judge"] for x in rs) / len(rs)}
            print(s, results[s])
    save_json(WORK / "results_dmr.json", results)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else None)
