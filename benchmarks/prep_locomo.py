"""LOCOMO adapter: long multi-session conversations -> dated session notes.

LOCOMO (snap-research/locomo, locomo10.json) is the standard long-term
conversational-memory benchmark used by mem0/zep. Each of the 10 samples is a
months-long two-person chat across ~20-35 dated sessions with ~200 QA pairs
(categories: 1 multi-hop, 2 temporal, 3 open-domain, 4 single-hop,
5 adversarial/unanswerable — excluded here, matching mem0's protocol).

Adapter: one note per session, session timestamp as frontmatter date, turns
as "Speaker: text" lines (+ image captions), one vault per conversation —
exactly how a chat-logging Obsidian plugin would lay it out. Lemory's date
machinery then works untouched.

A stratified question sample (seeded) keeps the eval inside free-tier quota;
pass --all to emit every answerable question.
"""

from __future__ import annotations

import ast
import json
import random
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import DATA, WORK, save_json

SEED = 31
OUT = WORK / "locomo"
# stratified sample per category (1 multi-hop, 2 temporal, 3 open-domain, 4 single-hop)
SAMPLE = {1: 45, 2: 45, 3: 16, 4: 54}

_DATE_RE = re.compile(r"(\d{1,2})\s+(\w+),?\s+(\d{4})")
_MONTHS = {m.lower(): i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"])}


def parse_session_date(raw: str) -> str | None:
    m = _DATE_RE.search(raw or "")
    if not m:
        return None
    day, mon, year = m.groups()
    month = _MONTHS.get(mon.lower()[:20]) or _MONTHS.get(mon.lower()[:3])
    if month is None:
        for name, num in _MONTHS.items():
            if name.startswith(mon.lower()):
                month = num
                break
    if month is None:
        return None
    return f"{int(year):04d}-{month:02d}-{int(day):02d}"


LOCOMO_URL = "https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json"


def main(sample_all: bool = False) -> None:
    src = DATA / "locomo" / "locomo10.json"
    if not src.exists():
        import urllib.request

        src.parent.mkdir(parents=True, exist_ok=True)
        print(f"downloading locomo10.json from {LOCOMO_URL} ...")
        urllib.request.urlretrieve(LOCOMO_URL, src)
    data = json.loads(src.read_text())
    rng = random.Random(SEED)

    all_questions = []
    for ci, conv in enumerate(data):
        vault = OUT / "vaults" / f"conv{ci}"
        vault.mkdir(parents=True, exist_ok=True)
        for f in vault.glob("*.md"):
            f.unlink()

        c = conv["conversation"]
        speaker_a, speaker_b = c.get("speaker_a", "A"), c.get("speaker_b", "B")
        session_keys = sorted(
            (k for k in c if re.fullmatch(r"session_\d+", k)),
            key=lambda s: int(s.split("_")[1]),
        )
        for sk in session_keys:
            n = int(sk.split("_")[1])
            date = parse_session_date(c.get(f"{sk}_date_time", ""))
            lines = []
            for turn in c[sk]:
                text = turn.get("text", "") or ""
                cap = turn.get("blip_caption")
                if cap:
                    text = f"{text} [shared a photo: {cap}]".strip()
                lines.append(f"{turn.get('speaker', '?')}: {text}")
            fm = f"---\ndate: {date}\n---\n" if date else ""
            title = f"Session {n:02d} {speaker_a}-{speaker_b}"
            (vault / f"{title}.md").write_text(
                fm + f"# {title} ({c.get(f'{sk}_date_time', '')})\n\n" + "\n".join(lines),
                encoding="utf-8",
            )

        for q in conv["qa"]:
            cat = int(q.get("category", 0))
            if cat == 5:  # adversarial/unanswerable — excluded, mem0 protocol
                continue
            try:
                evidence = q.get("evidence")
                evidence = ast.literal_eval(evidence) if isinstance(evidence, str) else (evidence or [])
            except (ValueError, SyntaxError):
                evidence = []
            all_questions.append({
                "conv": ci, "q": q["question"], "answer": str(q.get("answer", "")),
                "category": cat, "evidence": evidence,
            })

    if sample_all:
        sampled = all_questions
    else:
        sampled = []
        for cat, n in SAMPLE.items():
            pool = [q for q in all_questions if q["category"] == cat]
            rng.shuffle(pool)
            sampled.extend(pool[:n])
        rng.shuffle(sampled)

    save_json(OUT / "eval_set.json", sampled)
    n_sessions = sum(1 for _ in (OUT / "vaults").glob("conv*/*.md"))
    print(f"vaults: 10 conversations, {n_sessions} session notes -> {OUT/'vaults'}")
    print(f"eval set: {len(sampled)} questions "
          f"(of {len(all_questions)} answerable in locomo10)")


if __name__ == "__main__":
    main(sample_all="--all" in sys.argv)
