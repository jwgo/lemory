"""실제 나무위키 메이플스토리 볼트에서 검증-가능한 QA 벤치마크 생성.

실데이터는 관계를 코드로 배선할 수 없으므로, LLM이 초안을 만들고 코드가
정직성 불변식을 검증한다 (불합격 문항은 폐기):

  2-hop (A→B 링크 쌍에서 생성):
    * 질문은 A(브리지)의 주제를 언급하되 B의 제목을 포함하면 안 됨
    * 정답 문자열은 B의 본문에 존재해야 하고 A의 본문에는 없어야 함
  1-hop:
    * 정답 문자열이 해당 노트 본문에 존재해야 함
    * 질문에 정답 문자열이 그대로 들어가면 안 됨

usage: python gen_maple_real_qa.py [n_2hop] [n_1hop]
출력: benchmarks/data/maple_real/questions.json
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import DATA, WORK, load_env, make_engine, normalize_answer, save_json

OUT = DATA / "maple_real"
SEED = 11


def note_text(store, doc_id: int, limit: int = 4000) -> str:
    rows = store.conn().execute(
        "SELECT text FROM chunks WHERE doc_id=? ORDER BY ord", (doc_id,)).fetchall()
    return "\n".join(r["text"] for r in rows)[:limit]


def valid_2hop(q: dict, a_title, a_text, b_title, b_text) -> bool:
    ans = normalize_answer(q.get("answer", ""))
    if not ans or len(ans) < 2:
        return False
    if ans not in normalize_answer(b_text):
        return False                      # answer must live in B
    if ans in normalize_answer(a_text):
        return False                      # ...and only in B (true 2-hop)
    ql = normalize_answer(q.get("q", ""))
    if not ql or normalize_answer(b_title) in ql:
        return False                      # no leakage of the answer note
    if ans in ql:
        return False
    return True


def valid_1hop(q: dict, title, text) -> bool:
    ans = normalize_answer(q.get("answer", ""))
    ql = normalize_answer(q.get("q", ""))
    return bool(ans) and ans in normalize_answer(text) and ans not in ql and bool(ql)


def main() -> None:
    load_env()
    n_2hop = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    n_1hop = int(sys.argv[2]) if len(sys.argv) > 2 else 20

    eng = make_engine(OUT / "vault", tag="maple_real")
    eng.index()
    store = eng.store
    rng = random.Random(SEED)

    # candidate A->B wiki link pairs, both reasonably substantial
    pairs = store.conn().execute(
        """SELECT l.src_doc, l.dst_doc FROM links l
           JOIN documents a ON a.id=l.src_doc JOIN documents b ON b.id=l.dst_doc
           WHERE l.kind='wiki'"""
    ).fetchall()
    rng.shuffle(pairs)
    docs = {d.id: d for d in store.all_docs()}

    questions: list[dict] = []
    tried = 0
    for row in pairs:
        if len([q for q in questions if q["hops"] == 2]) >= n_2hop or tried > n_2hop * 6:
            break
        a, b = docs.get(row["src_doc"]), docs.get(row["dst_doc"])
        if not a or not b or a.id == b.id:
            continue
        a_text, b_text = note_text(store, a.id), note_text(store, b.id)
        if len(a_text) < 300 or len(b_text) < 300:
            continue
        tried += 1
        try:
            draft = eng.llm.generate_json(
                "두 개의 나무위키 문서가 주어진다. 문서 A는 문서 B로 링크한다.\n"
                "다음 조건의 한국어 2-hop 질문 1개를 만들어라:\n"
                f"- 질문은 문서 A의 주제('{a.title}')를 언급하지만, 문서 B의 제목('{b.title}')은 절대 포함하지 않는다\n"
                "- 답은 문서 B의 본문에 나오는 짧은 구체적 사실(이름/숫자/지명 등)이며, 문서 A에는 등장하지 않는 것이어야 한다\n"
                "- 답 문자열은 문서 B 본문의 표현 그대로 써라\n"
                'JSON: {"q": "...", "answer": "..."}\n\n'
                f"### 문서 A: {a.title}\n{a_text[:2500]}\n\n### 문서 B: {b.title}\n{b_text[:2500]}",
                temperature=0.4,
            )
        except Exception as e:
            print(f"gen failed: {e}")
            continue
        if isinstance(draft, dict) and valid_2hop(draft, a.title, a_text, b.title, b_text):
            questions.append({
                "q": draft["q"], "answers": [draft["answer"]],
                "gold_notes": [a.title, b.title], "hops": 2, "type": f"{a.title}→{b.title}",
            })
            print(f"2hop ok ({len([q for q in questions if q['hops']==2])}/{n_2hop}): {draft['q'][:60]}")

    # 1-hop over random substantial notes
    all_ids = [d.id for d in docs.values()]
    rng.shuffle(all_ids)
    for doc_id in all_ids:
        if len([q for q in questions if q["hops"] == 1]) >= n_1hop:
            break
        d = docs[doc_id]
        text = note_text(store, doc_id)
        if len(text) < 500:
            continue
        try:
            draft = eng.llm.generate_json(
                "나무위키 문서에서 짧고 구체적인 사실(이름/숫자/지명/직업명 등)을 하나 골라 "
                "그것을 답으로 하는 한국어 질문 1개를 만들어라. 답 문자열은 본문 표현 그대로. "
                f"질문에는 답이 들어가면 안 된다. 질문은 '{d.title}'에 대한 것임이 드러나야 한다.\n"
                'JSON: {"q": "...", "answer": "..."}\n\n'
                f"### 문서: {d.title}\n{text[:3000]}",
                temperature=0.4,
            )
        except Exception as e:
            print(f"gen failed: {e}")
            continue
        if isinstance(draft, dict) and valid_1hop(draft, d.title, text):
            questions.append({
                "q": draft["q"], "answers": [draft["answer"]],
                "gold_notes": [d.title], "hops": 1, "type": "single",
            })
            print(f"1hop ok ({len([q for q in questions if q['hops']==1])}/{n_1hop}): {draft['q'][:60]}")

    rng.shuffle(questions)
    save_json(OUT / "questions.json", questions)
    print(f"saved {len(questions)} questions "
          f"({len([q for q in questions if q['hops']==2])} 2-hop) -> {OUT}/questions.json")


if __name__ == "__main__":
    main()
