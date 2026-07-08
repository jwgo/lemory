"""Generate the two Korean real-domain benchmark corpora.

    python gen_korean.py maple   # 메이플스토리 나무위키-style vault + QA
    python gen_korean.py law     # 전세사기 관계법령 vault + QA

Network policy blocks namu.wiki / law.go.kr in this environment, so the
content is written by Gemini from its domain knowledge of the real subject
matter (real job/boss/region names; real statutes and article numbers).
Both corpora follow the same honesty scheme as gen_multihop.py:

  * maple: Gemini supplies structured facts; CODE wires which note states
    which relation and renders wikilinked notes; QA comes from templates over
    the structured facts, so gold labels are correct by construction.
  * law: Gemini writes statute notes and QA; code verifies every QA answer
    string literally appears in its gold note (drops QA that fail), so gold
    labels are checked, not trusted.

Everything is resumable: state lives in benchmarks/data/<corpus>/ and calls
are skipped once their output exists (free-tier daily quota is tiny).
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import DATA, load_env, save_json

from lemory.providers.gemini import GeminiClient

SEED = 7


def client() -> GeminiClient:
    import os

    return GeminiClient(api_key=os.environ["GEMINI_API_KEY"], llm_rpm=4)


# =============================================================== MapleStory
MAPLE_FACTS_PROMPT = """메이플스토리(한국 서버 기준)의 실제 게임 지식으로 아래 JSON을 채우세요.
반드시 실존하는 게임 내 명칭(직업, 보스, 지역, 스킬)을 사용하세요. STRICT JSON만 출력:
{
  "jobs": 10 items: {"name": "직업명(예: 아크메이지(썬,콜))", "group": "직업군(예: 마법사)", "main_stat": "주스탯", "signature_skill": "대표 스킬명"},
  "bosses": 8 items: {"name": "보스명(예: 루시드)", "region": "출현 지역명(예: 레헬른)", "level_req": 입장 레벨(int), "reward": "대표 보상 아이템명"},
  "regions": 8 items: {"name": "지역명(예: 아케인 리버)", "continent": "소속 대륙/세계", "level_range": "적정 레벨대(예: 200~210)"},
  "items": 6 items: {"name": "아이템명(예: 앱솔랩스 무기)", "source": "획득처(보스/지역명 - 위 목록의 명칭과 일치해야 함)", "type": "장비 부위/종류"}
}
bosses의 region은 regions 목록에 있는 명칭과, items의 source는 bosses 또는 regions의 명칭과 일치해야 합니다."""


def gen_maple() -> None:
    out = DATA / "maple"
    out.mkdir(parents=True, exist_ok=True)
    facts_f = out / "facts.json"
    if facts_f.exists():
        facts = json.loads(facts_f.read_text())
        print("facts.json exists, reusing")
    else:
        facts = client().generate_json(MAPLE_FACTS_PROMPT, temperature=0.3, max_output_tokens=4096)
        save_json(facts_f, facts)

    prose_f = out / "prose.json"
    prose: dict[str, str] = json.loads(prose_f.read_text()) if prose_f.exists() else {}
    items = []
    for kind in ("jobs", "bosses", "regions", "items"):
        for it in facts.get(kind, []):
            items.append((kind, it["name"], it))
    todo = [x for x in items if x[1] not in prose]
    if todo:
        c = client()
        for i in range(0, len(todo), 6):
            batch = todo[i : i + 6]
            spec = "\n".join(
                f'- "{name}" ({kind}): {json.dumps(it, ensure_ascii=False)}'
                for kind, name, it in batch
            )
            data = c.generate_json(
                "각 항목에 대해 나무위키 문체(개조식+설명형 혼합, 존댓말 금지)의 위키 문단을 "
                "80~120단어로 작성하세요. 주어진 속성 외 다른 항목의 이름은 언급 금지. "
                'JSON만 출력: {"<이름>": "<본문>", ...}\n\n' + spec,
                temperature=0.6, max_output_tokens=4096,
            )
            for kind, name, it in batch:
                body = data.get(name, "")
                prose[name] = body if isinstance(body, str) else ""
            save_json(prose_f, prose)
            print(f"prose {min(i+6, len(todo))}/{len(todo)}")

    # scrub cross-mentions so relations only live where code puts them
    all_names = [name for _, name, _ in items]
    for name in prose:
        for other in all_names:
            if other != name and other in prose[name]:
                prose[name] = prose[name].replace(other, "해당 대상")

    notes: dict[str, str] = {}

    def note(name, tags, body, facts_lines):
        fm = "\n".join(f"- {line}" for line in facts_lines)
        notes[f"{name}.md"] = f"{tags}\n\n{body.strip()}\n\n## 주요 정보\n{fm}\n"

    for j in facts["jobs"]:
        note(j["name"], "#직업", prose.get(j["name"], ""), [
            f"직업군: {j['group']}", f"주스탯: {j['main_stat']}",
            f"대표 스킬: {j['signature_skill']}",
        ])
    for b in facts["bosses"]:
        note(b["name"], "#보스", prose.get(b["name"], ""), [
            f"출현 지역: [[{b['region']}]]", f"입장 레벨: {b['level_req']}",
            f"대표 보상: {b['reward']}",
        ])
    for r in facts["regions"]:
        note(r["name"], "#지역", prose.get(r["name"], ""), [
            f"소속: {r['continent']}", f"적정 레벨: {r['level_range']}",
        ])
    for it in facts["items"]:
        note(it["name"], "#아이템", prose.get(it["name"], ""), [
            f"획득처: [[{it['source']}]]", f"종류: {it['type']}",
        ])

    # QA from structured facts (Korean templates -> gold guaranteed by code)
    rng = random.Random(SEED)
    qs = []

    def add(q, answer, gold, hops):
        qs.append({"q": q, "answers": [str(answer)], "gold_notes": gold, "hops": hops})

    region_by_name = {r["name"]: r for r in facts["regions"]}
    boss_by_name = {b["name"]: b for b in facts["bosses"]}
    for b in facts["bosses"]:
        add(f"{b['name']}의 입장 레벨은 몇이야?", b["level_req"], [b["name"]], 1)
        r = region_by_name.get(b["region"])
        if r:
            # 2-hop: boss note names the region; continent lives in region note
            add(f"{b['name']}가 출현하는 지역은 어느 대륙(세계) 소속이야?",
                r["continent"], [b["name"], r["name"]], 2)
    for it in facts["items"]:
        src_boss = boss_by_name.get(it["source"])
        if src_boss:
            add(f"{it['name']}을 주는 보스의 입장 레벨은?",
                src_boss["level_req"], [it["name"], src_boss["name"]], 2)
        add(f"{it['name']}은 어디서 얻어?", it["source"], [it["name"]], 1)
    for j in rng.sample(facts["jobs"], 6):
        add(f"{j['name']}의 대표 스킬이 뭐야?", j["signature_skill"], [j["name"]], 1)

    # honesty check: 2-hop answer note must not contain the anchor name
    ok_qs = []
    for q in qs:
        if q["hops"] == 2:
            anchor, ans_note = q["gold_notes"]
            if anchor in notes.get(f"{ans_note}.md", ""):
                continue  # leaked; drop
        if all(f"{g}.md" in notes for g in q["gold_notes"]):
            ok_qs.append(q)
    rng.shuffle(ok_qs)

    vault = out / "vault"
    vault.mkdir(exist_ok=True)
    for f in vault.glob("*.md"):
        f.unlink()
    for fname, content in notes.items():
        (vault / fname.replace("/", "-")).write_text(content, encoding="utf-8")
    save_json(out / "questions.json", ok_qs)
    print(f"maple: {len(notes)} notes, {len(ok_qs)} questions "
          f"({sum(1 for q in ok_qs if q['hops'] == 2)} multi-hop)")


# ==================================================================== 법령
LAW_NOTES_PROMPT = """전세사기 피해와 관련된 실제 대한민국 법령·제도에 대한 개인 지식베이스 노트를 작성합니다.
각 주제에 대해 옵시디언 노트 본문(한국어, 150~250단어)을 작성하세요. 실제 법령명과 조문 번호,
실제 요건·기간·금액을 정확히 포함하세요. 관련된 다른 주제는 [[위키링크]]로 표기하세요.
JSON만 출력: {"<주제>": "<본문>", ...}

주제 목록:
"""

LAW_TOPICS = [
    "주택임대차보호법 대항력", "주택임대차보호법 우선변제권", "소액임차인 최우선변제",
    "임차권등기명령", "확정일자", "전세사기피해자 특별법", "전세보증금 반환보증(HUG)",
    "깡통전세 판별법", "민법 전세권", "공인중개사법 손해배상책임",
    "형법 사기죄와 전세사기", "채권자취소권(사해행위취소)", "부동산등기부등본 확인사항",
    "국세 당해세와 임차인 배당순위", "전세사기 피해 신고 절차",
]

LAW_QA_PROMPT = """위에서 작성된 노트들을 근거로 전세사기 관련 질문 20개를 만드세요.
규칙:
- answer는 반드시 해당 gold 노트 본문에 '그대로 포함된' 짧은 구절(숫자, 기간, 요건, 법령명 등)이어야 함
- 12개는 단일 노트로 답할 수 있는 질문(hops=1), 8개는 두 노트를 봐야 하는 질문(hops=2)
- JSON만 출력: {"questions": [{"q": "...", "answers": ["..."], "gold_notes": ["주제명"...], "hops": 1}]}

노트:
"""


def gen_law() -> None:
    out = DATA / "law"
    out.mkdir(parents=True, exist_ok=True)
    notes_f = out / "notes.json"
    notes: dict[str, str] = json.loads(notes_f.read_text()) if notes_f.exists() else {}
    todo = [t for t in LAW_TOPICS if t not in notes]
    if todo:
        c = client()
        for i in range(0, len(todo), 5):
            batch = todo[i : i + 5]
            data = c.generate_json(
                LAW_NOTES_PROMPT + "\n".join(f"- {t}" for t in batch),
                temperature=0.3, max_output_tokens=8192,
            )
            for t in batch:
                body = data.get(t, "")
                if isinstance(body, str) and len(body) > 100:
                    notes[t] = body
            save_json(notes_f, notes)
            print(f"notes {len(notes)}/{len(LAW_TOPICS)}")

    qa_f = out / "qa_raw.json"
    if qa_f.exists():
        qa_raw = json.loads(qa_f.read_text())
    else:
        joined = "\n\n".join(f"### {t}\n{b}" for t, b in notes.items())
        qa_raw = client().generate_json(
            LAW_QA_PROMPT + joined[:24000], temperature=0.3, max_output_tokens=8192)
        save_json(qa_f, qa_raw)

    # verify: every answer must literally appear in a gold note (code-checked)
    qs = []
    for q in qa_raw.get("questions", []):
        golds = [g for g in q.get("gold_notes", []) if g in notes]
        answers = [a for a in q.get("answers", []) if isinstance(a, str) and a.strip()]
        if not golds or not answers:
            continue
        if any(a in notes[g] for a in answers for g in golds):
            qs.append({"q": q["q"], "answers": answers, "gold_notes": golds,
                       "hops": int(q.get("hops", 1))})
    print(f"law QA verified: {len(qs)}/{len(qa_raw.get('questions', []))}")

    vault = out / "vault"
    vault.mkdir(exist_ok=True)
    for f in vault.glob("*.md"):
        f.unlink()
    for topic, body in notes.items():
        (vault / f"{topic}.md").write_text(f"#법령 #전세사기\n\n{body}\n", encoding="utf-8")
    save_json(out / "questions.json", qs)
    print(f"law: {len(notes)} notes, {len(qs)} questions")


if __name__ == "__main__":
    load_env()
    which = sys.argv[1] if len(sys.argv) > 1 else "maple"
    if which == "maple":
        gen_maple()
    elif which == "law":
        gen_law()
    else:
        raise SystemExit("usage: gen_korean.py maple|law")
