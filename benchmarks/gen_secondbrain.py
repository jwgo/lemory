"""Second-brain scale benchmark: a big, messy, realistic personal vault.

Builds ~1,200 mixed Korean/English notes — daily logs, people, projects,
meetings, tastes, clippings — densely wikilinked like a real long-lived
vault, with 60 deterministic "planted facts" (birthdays, decisions,
preferences, who-said-what) whose retrieval can be verified without any
LLM or embedding API:

    python gen_secondbrain.py          # writes benchmarks/work/secondbrain/
    python run_secondbrain.py          # index + verify + latency report

This answers the scale question the small corpora can't: does incremental
sync, the mention graph, and retrieval hold up on a vault the size of a
years-old second brain?
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import WORK, save_json

SEED = 11
OUT = WORK / "secondbrain"

FIRST_KR = ["지수", "민준", "서연", "하준", "다은", "시우", "예린", "준호", "수아", "도윤",
            "은우", "채원", "지호", "유나", "건우", "소율"]
LAST_KR = ["김", "이", "박", "최", "정", "강", "조", "윤", "임", "한"]
FIRST_EN = ["Elena", "Marcus", "Yuki", "Priya", "Tomás", "Ingrid", "Kofi", "Sana"]
LAST_EN = ["Silva", "Novak", "Haddad", "Okafor", "Larsson", "Rossi", "Iyer", "Chen"]
PROJECT_WORDS = ["결제", "온보딩", "검색", "알림", "정산", "리포트", "마이그레이션", "실험",
                 "billing", "search", "onboarding", "analytics", "infra", "ml"]
TOPICS = ["회고", "아이디어", "버그", "장애", "설계", "리뷰", "면담", "스터디"]
FOODS = ["평양냉면", "마르게리타 피자", "간장게장", "쌀국수", "훠궈", "붕어빵", "카레우동",
         "바스크 치즈케이크", "김치찜", "라멘"]
HOBBIES = ["클라이밍", "필름 카메라", "베이킹", "러닝", "보드게임", "수영", "기타", "테니스"]
PLACES = ["성수동", "연남동", "판교", "을지로", "제주", "부산", "강릉", "여의도"]
FILLER_KR = [
    "오늘은 집중이 잘 됐다.", "생각보다 오래 걸렸다.", "다음 주에 다시 보기로 했다.",
    "리뷰 코멘트를 반영했다.", "테스트가 계속 깨져서 원인을 찾았다.",
    "점심 먹고 산책했다.", "회의가 길어져서 피곤했다.", "배포는 무사히 끝났다.",
]
FILLER_EN = [
    "Shipped the fix before standup.", "Need to follow up on the incident review.",
    "Paired with the platform team for an hour.", "Refactored the flaky test.",
]


def main() -> None:
    rng = random.Random(SEED)
    vault = OUT / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    for f in vault.glob("**/*.md"):
        f.unlink()
    for sub in ("사람", "프로젝트", "일지", "회의", "취향", "클리핑"):
        (vault / sub).mkdir(exist_ok=True)

    # unique realistic names: every (last, first) pair used at most once, so
    # confusability comes from shared given names (김지수 vs 이지수) — the
    # realistic case — never from one name containing another
    kr_pairs = [(l, f) for l in LAST_KR for f in FIRST_KR]
    en_pairs = [(f, l) for f in FIRST_EN for l in LAST_EN]
    rng.shuffle(kr_pairs)
    rng.shuffle(en_pairs)
    names = [f"{l}{f}" for l, f in kr_pairs[:90]] + [f"{f} {l}" for f, l in en_pairs[:30]]
    people = []
    for name in names:
        people.append({
            "name": name,
            "role": rng.choice(["동료", "친구", "가족", "전 직장 동료", "스터디원"]),
            "birthday": f"{rng.randint(1,12)}월 {rng.randint(1,28)}일",
            "food": rng.choice(FOODS),
            "hobby": rng.choice(HOBBIES),
        })
    projects = []
    for i in range(80):
        pname = f"{rng.choice(PROJECT_WORDS)}-{rng.choice(PROJECT_WORDS)}-{i}"
        projects.append({
            "name": pname,
            "owner": rng.choice(people)["name"],
            "status": rng.choice(["진행중", "보류", "완료"]),
            "decision": f"{rng.choice(['롤백 기준', '캐시 TTL', '요금 정책', 'SLA 목표'])}를 "
                        f"{rng.randint(2, 99)}{rng.choice(['분', '시간', '%', '건'])}로 정함",
        })

    planted: list[dict] = []

    def plant(q, answer, note):
        planted.append({"q": q, "answer": answer, "gold_note": note})

    def josa(word: str, with_batchim: str, without: str) -> str:
        ch = word[-1]
        if "가" <= ch <= "힣":
            return word + (with_batchim if (ord(ch) - 0xAC00) % 28 else without)
        return word + without

    # people notes
    for p in people:
        body = (
            f"#사람\n\n{p['name']} — {p['role']}.\n\n"
            f"- 생일: {p['birthday']}\n- 최애 음식: {p['food']}\n- 취미: {p['hobby']}\n\n"
            f"{rng.choice(FILLER_KR)}\n"
        )
        (vault / "사람" / f"{p['name']}.md").write_text(body, encoding="utf-8")
    for p in rng.sample(people, 20):
        # particle-attached queries are deliberate: they exercise Korean
        # morphology handling (조사 breaks naive token matching)
        plant(f"{josa(p['name'], '이', '가')} 좋아하는 음식", p["food"], p["name"])
        plant(f"{p['name']} 생일 언제지", p["birthday"], p["name"])

    # project notes
    for pr in projects:
        body = (
            f"#프로젝트 상태:{pr['status']}\n\n"
            f"오너: [[{pr['owner']}]]\n\n## 결정사항\n- {pr['decision']}\n\n"
            f"{rng.choice(FILLER_KR)} {rng.choice(FILLER_EN)}\n"
        )
        (vault / "프로젝트" / f"{pr['name']}.md").write_text(body, encoding="utf-8")
    for pr in rng.sample(projects, 10):
        plant(f"{pr['name']} 프로젝트에서 정한 결정", pr["decision"], pr["name"])

    # daily notes (400 days), meetings (200), tastes (100), clippings (300)
    for d in range(400):
        date = f"2025-{(d % 12) + 1:02d}-{(d % 28) + 1:02d}-{d//336}"
        who = rng.choice(people)["name"]
        proj = rng.choice(projects)["name"]
        lines = [f"# {date} 일지", "", f"[[{who}]]랑 [[{proj}]] 얘기함.",
                 rng.choice(FILLER_KR), rng.choice(FILLER_EN)]
        if d % 40 == 3:
            memory = f"{rng.choice(PLACES)}에서 {rng.choice(FOODS)} 먹었는데 인생 맛집이었다"
            lines.append(memory)
        (vault / "일지" / f"{date}.md").write_text("\n".join(lines), encoding="utf-8")
    for m in range(200):
        proj = rng.choice(projects)
        topic = rng.choice(TOPICS)
        att = ", ".join(f"[[{rng.choice(people)['name']}]]" for _ in range(3))
        body = (f"#회의 [[{proj['name']}]]\n\n주제: {topic}\n참석: {att}\n\n"
                f"## 논의\n{rng.choice(FILLER_KR)}\n## 액션아이템\n- {rng.choice(FILLER_EN)}\n")
        (vault / "회의" / f"회의-{m:03d}-{topic}.md").write_text(body, encoding="utf-8")
    for t in range(100):
        food = rng.choice(FOODS)
        place = rng.choice(PLACES)
        score = rng.randint(2, 5)
        body = f"#취향 #맛집\n\n{place}의 {food} 집. 별점 {score}/5.\n{rng.choice(FILLER_KR)}\n"
        (vault / "취향" / f"맛집-{t:03d}.md").write_text(body, encoding="utf-8")
    for c in range(300):
        topic = rng.choice(PROJECT_WORDS)
        body = (f"#클리핑\n\nSource: https://example.com/{topic}/{c}\n\n"
                f"{topic} 관련 아티클 메모. {rng.choice(FILLER_EN)} {rng.choice(FILLER_KR)}\n")
        (vault / "클리핑" / f"클리핑-{c:03d}.md").write_text(body, encoding="utf-8")

    save_json(OUT / "planted.json", planted)
    n = sum(1 for _ in vault.glob("**/*.md"))
    print(f"secondbrain vault: {n} notes, {len(planted)} planted facts -> {OUT}")


if __name__ == "__main__":
    main()
