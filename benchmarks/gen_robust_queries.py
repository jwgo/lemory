"""Generate committed query variants for the robustness benchmark.

Real users don't phrase questions like a benchmark: they paraphrase, they type
Korean queries against English notes, they fire two-word keyword lookups, and
they typo. For each multihop question we generate:

  paraphrase — same meaning, different vocabulary (English)
  korean     — natural Korean phrasing of the same question
  keyword    — terse keyword-style lookup (what people actually type)
  typo       — original with 1-2 realistic keyboard typos (code-generated)

Honesty invariants enforced in code: a variant must keep the anchor entity
(the gold bridge/single note title) and must NOT contain the answer or, for
2-hop questions, the answer note's title.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import DATA, load_env, normalize_answer, save_json

from lemory.providers.gemini import GeminiClient

OUT = DATA / "multihop" / "robust_queries.json"
SEED = 5


def typo(q: str, rng: random.Random) -> str:
    """1-2 realistic typos: swap adjacent letters / drop a letter in long words."""
    words = q.split()
    idxs = [i for i, w in enumerate(words) if len(w) >= 5 and w[0].isalpha()]
    rng.shuffle(idxs)
    for i in idxs[:2]:
        w = words[i]
        j = rng.randint(1, len(w) - 3)
        if rng.random() < 0.5:
            w = w[:j] + w[j + 1] + w[j] + w[j + 2:]  # swap
        else:
            w = w[:j] + w[j + 1:]  # drop
        words[i] = w
    return " ".join(words)


def leaks(variant: str, q: dict) -> bool:
    v = normalize_answer(variant)
    for a in q["answers"]:
        na = normalize_answer(a)
        if na and na in v:
            return True
    if q["hops"] == 2:
        answer_note = normalize_answer(q["gold_notes"][-1])
        if answer_note and answer_note in v:
            return True
    return False


def keeps_anchor(variant: str, q: dict) -> bool:
    anchor = q["gold_notes"][0]
    # anchor must survive in some recognizable form (>=60% of its tokens)
    at = [t for t in normalize_answer(anchor).split() if len(t) > 2]
    if not at:
        return True
    vt = normalize_answer(variant)
    hits = sum(1 for t in at if t in vt)
    return hits >= max(1, int(0.6 * len(at)))


def main() -> None:
    load_env()
    import os

    questions = json.loads((DATA / "multihop" / "questions.json").read_text())
    existing = json.loads(OUT.read_text()) if OUT.exists() else {}
    rng = random.Random(SEED)
    client = GeminiClient(api_key=os.environ["GEMINI_API_KEY"], llm_rpm=8)

    out = dict(existing)
    todo = [q for q in questions if q["q"] not in out]
    for i in range(0, len(todo), 8):
        batch = todo[i : i + 8]
        spec = "\n".join(
            f"{j+1}. {q['q']}  (anchor entity that MUST stay: \"{q['gold_notes'][0]}\")"
            for j, q in enumerate(batch)
        )
        data = client.generate_json(
            "For EACH numbered question produce 3 variants:\n"
            '  "paraphrase": same meaning, different English vocabulary\n'
            '  "korean": natural Korean phrasing (질문형)\n'
            '  "keyword": terse 2-5 word keyword lookup (no question words)\n'
            "Rules: keep the anchor entity name EXACTLY as given in every variant; "
            "do not answer the question; do not add information.\n"
            'Return JSON: {"1": {"paraphrase": "...", "korean": "...", "keyword": "..."}, ...}\n\n'
            + spec,
            temperature=0.4, max_output_tokens=4096,
        )
        for j, q in enumerate(batch):
            v = data.get(str(j + 1)) or {}
            entry = {}
            for kind in ("paraphrase", "korean", "keyword"):
                cand = v.get(kind, "")
                if isinstance(cand, str) and cand.strip() and not leaks(cand, q) and keeps_anchor(cand, q):
                    entry[kind] = cand.strip()
            entry["typo"] = typo(q["q"], rng)
            out[q["q"]] = entry
        save_json(OUT, out)
        print(f"{min(i+8, len(todo))}/{len(todo)}")

    counts = {}
    for e in out.values():
        for kind in e:
            counts[kind] = counts.get(kind, 0) + 1
    print("variant coverage:", counts)


if __name__ == "__main__":
    main()
