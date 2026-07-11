"""Verified QA generation over REAL vaults (English) — same honesty protocol
as gen_maple_real_qa.py: the LLM drafts, code verifies, failures are discarded.

  2-hop (from real A→B wikilink pairs):
    * question mentions A's topic but must NOT contain B's title
    * answer string must appear in B's body and NOT in A's body
    * answer must not appear in the question
  1-hop:
    * answer string must appear in the note body, not in the question

usage:
  python gen_real_qa.py kepano [n_2hop] [n_1hop]
  python gen_real_qa.py help   [n_2hop] [n_1hop]   # run prep_help.py first
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import DATA, WORK, load_env, make_engine, normalize_answer, save_json

SEED = 17

VAULTS = {
    "kepano": DATA / "kepano" / "vault",
    "help": WORK / "help_vault",
}


def note_text(store, doc_id: int, limit: int = 4000) -> str:
    # content chunks only — enrichment pseudo-chunks quote OTHER notes and
    # must never leak into question drafting or answer verification
    rows = store.conn().execute(
        "SELECT text FROM chunks WHERE doc_id=? AND heading != ? ORDER BY ord",
        (doc_id, store.ENRICH_HEADING)).fetchall()
    return "\n".join(r["text"] for r in rows)[:limit]


def valid_2hop(q: dict, a_title, a_text, b_title, b_text) -> bool:
    ans = normalize_answer(q.get("answer", ""))
    if not ans or len(ans) < 2:
        return False
    if ans not in normalize_answer(b_text):
        return False
    if ans in normalize_answer(a_text):
        return False
    ql = normalize_answer(q.get("q", ""))
    if not ql or normalize_answer(b_title) in ql or ans in ql:
        return False
    return True


def valid_1hop(q: dict, title, text) -> bool:
    ans = normalize_answer(q.get("answer", ""))
    ql = normalize_answer(q.get("q", ""))
    return bool(ans) and len(ans) >= 2 and ans in normalize_answer(text) and ans not in ql and bool(ql)


def main() -> None:
    load_env()
    tag = sys.argv[1] if len(sys.argv) > 1 else "kepano"
    n_2hop = int(sys.argv[2]) if len(sys.argv) > 2 else 25
    n_1hop = int(sys.argv[3]) if len(sys.argv) > 3 else 25
    vault = VAULTS[tag]
    out = DATA / tag if tag == "kepano" else DATA / "help"
    out.mkdir(parents=True, exist_ok=True)

    eng = make_engine(vault, tag=f"{tag}")
    eng.index()
    store = eng.store
    rng = random.Random(SEED)

    # resume support: keep already-verified questions
    qfile = out / "questions.json"
    questions: list[dict] = json.loads(qfile.read_text()) if qfile.exists() else []
    seen_types = {q.get("type") for q in questions}

    pairs = store.conn().execute(
        """SELECT l.src_doc, l.dst_doc FROM links l
           JOIN documents a ON a.id=l.src_doc JOIN documents b ON b.id=l.dst_doc
           WHERE l.kind='wiki'"""
    ).fetchall()
    rng.shuffle(pairs)
    docs = {d.id: d for d in store.all_docs()}

    tried = 0
    for row in pairs:
        n_have = len([q for q in questions if q["hops"] == 2])
        if n_have >= n_2hop or tried > n_2hop * 8:
            break
        a, b = docs.get(row["src_doc"]), docs.get(row["dst_doc"])
        if not a or not b or a.id == b.id or f"{a.title}→{b.title}" in seen_types:
            continue
        a_text, b_text = note_text(store, a.id), note_text(store, b.id)
        # real personal notes are short — accept small bodies; a stub target
        # still yields valid QA if its few lines contain a concrete fact
        if len(a_text) < 60 or len(b_text) < 60:
            continue
        tried += 1
        try:
            draft = eng.llm.generate_json(
                "You are given two notes from a real personal knowledge vault. "
                "Note A links to note B.\n"
                "Write ONE natural 2-hop question in English such that:\n"
                f"- the question refers to note A's topic ('{a.title}') but must NOT "
                f"contain note B's title ('{b.title}')\n"
                "- the answer is a short concrete fact (name/number/term) that appears "
                "verbatim in note B's body and does NOT appear in note A\n"
                "- write the answer exactly as it appears in note B\n"
                'Return JSON: {"q": "...", "answer": "..."}\n\n'
                f"### Note A: {a.title}\n{a_text[:2200]}\n\n### Note B: {b.title}\n{b_text[:2200]}",
                temperature=0.4,
            )
        except Exception as e:
            print(f"gen failed: {str(e)[:90]}")
            continue
        if isinstance(draft, dict) and valid_2hop(draft, a.title, a_text, b.title, b_text):
            questions.append({
                "q": draft["q"], "answers": [draft["answer"]],
                "gold_notes": [a.title, b.title], "hops": 2, "type": f"{a.title}→{b.title}",
            })
            save_json(qfile, questions)
            print(f"2hop ok ({len([q for q in questions if q['hops']==2])}/{n_2hop}): {draft['q'][:70]}")

    all_ids = [d.id for d in docs.values()]
    rng.shuffle(all_ids)
    for doc_id in all_ids:
        if len([q for q in questions if q["hops"] == 1]) >= n_1hop:
            break
        d = docs[doc_id]
        if f"single:{d.title}" in seen_types:
            continue
        text = note_text(store, doc_id)
        if len(text) < 200:
            continue
        try:
            draft = eng.llm.generate_json(
                "From this real personal-vault note, pick ONE short concrete fact "
                "(a name, number, term, or phrase) and write ONE natural English "
                "question whose answer is that fact. Write the answer exactly as it "
                f"appears in the note. The question must make clear it is about "
                f"'{d.title}' and must not contain the answer.\n"
                'Return JSON: {"q": "...", "answer": "..."}\n\n'
                f"### Note: {d.title}\n{text[:2800]}",
                temperature=0.4,
            )
        except Exception as e:
            print(f"gen failed: {str(e)[:90]}")
            continue
        if isinstance(draft, dict) and valid_1hop(draft, d.title, text):
            questions.append({
                "q": draft["q"], "answers": [draft["answer"]],
                "gold_notes": [d.title], "hops": 1, "type": f"single:{d.title}",
            })
            save_json(qfile, questions)
            print(f"1hop ok ({len([q for q in questions if q['hops']==1])}/{n_1hop}): {draft['q'][:70]}")

    rng.shuffle(questions)
    save_json(qfile, questions)
    n2 = len([q for q in questions if q["hops"] == 2])
    print(f"saved {len(questions)} questions ({n2} 2-hop) -> {qfile}")


if __name__ == "__main__":
    main()
