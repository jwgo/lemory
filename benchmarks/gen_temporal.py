"""Temporal scenario benchmark: 6 months of a life, asked the way people ask.

Generates a realistic 6-month personal vault "as of" a fixed TODAY:
daily notes (일지/YYYY-MM-DD.md), weekly reviews, meetings — with facts that
EVOLVE over time. Every planted storyline has an old value superseded by a
newer one (책, 운동, 도구, 식당, 프로젝트 상태, 담당자...), so the benchmark can
measure the thing people actually want from a second brain:

  "요새 내가 읽던 책 뭐였지?"  → the CURRENT book, not the one from March.

Query classes (all with code-verified gold):
  recent_fact      요새/요즘/최근 X → latest value, gold = newest note
  superseded_trap  same, but the old value is the strong lexical match
  window           어제/지난주/이번 주/N일 전 → note in that window
  old_fact         explicit past reference ("3월에 읽던 책") → old value stays
                   reachable (no over-suppression of history)

Deterministic (seeded), LLM-free, no-API. TODAY is fixed so results reproduce.
"""

from __future__ import annotations

import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import WORK, save_json

SEED = 23
OUT = WORK / "temporal"
TODAY = date(2026, 7, 9)  # fixed "now" for reproducibility

BOOKS = ["스노 크래시", "피라네시", "프로젝트 헤일메리", "듄", "파운데이션", "삼체",
         "어스시의 마법사", "뉴로맨서"]
EXERCISES = ["클라이밍", "수영", "러닝", "테니스", "복싱", "요가"]
TOOLS = ["Obsidian", "Notion", "Logseq", "Bear", "Reflect"]
RESTAURANTS = ["을지로 평양냉면집", "성수 파스타바", "연남동 쌀국수", "판교 김치찜",
               "강남 스시집", "홍대 라멘집"]
LANGS = ["Rust", "Go", "TypeScript", "Kotlin", "Elixir"]
PEOPLE = ["김지수", "박민준", "이서연", "최하준", "정다은", "강시우"]
PROJECTS = ["결제 리뉴얼", "검색 개선", "온보딩 실험", "정산 자동화"]

FILLER = [
    "오늘은 집중이 잘 됐다.", "점심 먹고 산책했다.", "리뷰 코멘트를 반영했다.",
    "테스트가 계속 깨져서 원인을 찾았다.", "배포는 무사히 끝났다.",
    "회의가 길어져서 피곤했다.", "Paired with the platform team.",
    "Refactored the flaky test.", "내일 할 일을 정리해뒀다.",
]


def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def main() -> None:
    rng = random.Random(SEED)
    vault = OUT / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    for f in vault.glob("**/*.md"):
        f.unlink()
    for sub in ("일지", "회의", "프로젝트"):
        (vault / sub).mkdir(exist_ok=True)

    start = TODAY - timedelta(days=180)
    daily: dict[date, list[str]] = {d: [] for d in daterange(start, TODAY)}
    queries: list[dict] = []

    def note_name(d: date) -> str:
        return f"일지/{d.isoformat()}"

    def plant_evolving(kind: str, values: list[str], phrases, question, ask_old=None):
        """Two values: old one mentioned repeatedly long ago, new one recently.
        The old value gets MORE mentions (it's the stronger lexical match) —
        that's the trap a recency-blind retriever falls into."""
        old_v, new_v = rng.sample(values, 2)
        old_days = sorted(rng.sample(range(90, 170), 3))
        new_days = sorted(rng.sample(range(1, 14), 2))
        for nd in old_days:
            daily[TODAY - timedelta(days=nd)].append(phrases(old_v))
        for nd in new_days:
            daily[TODAY - timedelta(days=nd)].append(phrases(new_v))
        newest = TODAY - timedelta(days=new_days[0])
        queries.append({
            "kind": "recent_fact", "topic": kind, "q": question,
            "answer": new_v, "wrong_answer": old_v,
            "gold_note": note_name(newest),
        })
        if ask_old:
            oldest = TODAY - timedelta(days=old_days[-1])
            month = oldest.month
            queries.append({
                "kind": "old_fact", "topic": kind,
                "q": ask_old.format(month=month),
                "answer": old_v, "wrong_answer": new_v,
                "gold_note": note_name(oldest),
            })

    plant_evolving(
        "book", BOOKS,
        lambda v: f"요즘 읽는 책은 {v}. 자기 전에 몇 챕터씩 읽고 있다.",
        "요새 내가 읽던 책 뭐였지?",
        ask_old="{month}월에 읽던 책 제목이 뭐였지?",
    )
    plant_evolving(
        "exercise", EXERCISES,
        lambda v: f"퇴근하고 {v} 하러 갔다. 확실히 체력이 붙는다.",
        "요즘 하는 운동이 뭐더라?",
    )
    plant_evolving(
        "tool", TOOLS,
        lambda v: f"노트 앱을 {v}(으)로 정리 중. 세팅을 좀 다듬었다.",
        "최근에 갈아탄 노트 앱 이름이 뭐지?",
    )
    plant_evolving(
        "restaurant", RESTAURANTS,
        lambda v: f"저녁은 {v}에서. 여기 진짜 맛있다, 또 와야지.",
        "요새 자주 가던 맛집 어디였지?",
    )
    plant_evolving(
        "lang", LANGS,
        lambda v: f"사이드 프로젝트를 {v}로 다시 쓰기 시작했다. 문법이 손에 익는 중.",
        "요즘 사이드 프로젝트 무슨 언어로 하고 있었지?",
    )

    # --- window queries: unique events pinned to specific days
    events = [
        (1, "어제 회의에서 뭐 결정했지?",
         "회의: 정산 배치를 새벽 4시로 옮기기로 결정했다.", "정산 배치를 새벽 4시로"),
        (3, "3일 전에 저장해둔 링크 뭐였지?",
         "나중에 볼 링크 저장: https://example.com/vector-db-comparison (벡터DB 비교글)",
         "vector-db-comparison"),
        (0, "오늘 아침에 적어둔 할 일이 뭐였지?",
         "오늘 할 일: 검색 개선 PR 리뷰, 치과 예약 전화.", "치과 예약"),
    ]
    for days_ago, q, text, ans in events:
        d = TODAY - timedelta(days=days_ago)
        daily[d].append(text)
        queries.append({"kind": "window", "topic": "event", "q": q,
                        "answer": ans, "wrong_answer": None,
                        "gold_note": note_name(d)})
    # last week: put the event mid-last-week
    monday = TODAY - timedelta(days=TODAY.weekday())
    lw = monday - timedelta(days=4)
    daily[lw].append("회고: 지난주 목표였던 온보딩 실험 A/B 결과가 +4.2%로 나왔다.")
    queries.append({"kind": "window", "topic": "event",
                    "q": "지난주에 나온 A/B 테스트 결과 몇 프로였지?",
                    "answer": "+4.2%", "wrong_answer": None,
                    "gold_note": note_name(lw)})

    # --- project status evolution in meeting notes
    proj = rng.choice(PROJECTS)
    owner_old, owner_new = rng.sample(PEOPLE, 2)
    d_old = TODAY - timedelta(days=95)
    d_new = TODAY - timedelta(days=6)
    (OUT / "vault" / "회의" / f"{d_old.isoformat()} {proj} 킥오프.md").write_text(
        f"---\ndate: {d_old.isoformat()}\n---\n# {proj} 킥오프\n"
        f"담당자는 {owner_old}. 목표는 다음 분기 출시.\n" + rng.choice(FILLER),
        encoding="utf-8",
    )
    (OUT / "vault" / "회의" / f"{d_new.isoformat()} {proj} 인수인계.md").write_text(
        f"---\ndate: {d_new.isoformat()}\n---\n# {proj} 인수인계\n"
        f"이번 주부터 담당자가 {owner_new}(으)로 변경. 일정은 유지.\n" + rng.choice(FILLER),
        encoding="utf-8",
    )
    queries.append({"kind": "superseded_trap", "topic": "owner",
                    "q": f"지금 {proj} 담당자가 누구지?",
                    "answer": owner_new, "wrong_answer": owner_old,
                    "gold_note": f"회의/{d_new.isoformat()} {proj} 인수인계"})

    # --- filler: every day gets 1-3 mundane lines; ~70% of days have notes
    n_notes = 0
    for d, lines in daily.items():
        if not lines and rng.random() > 0.7:
            continue
        body = lines + rng.sample(FILLER, k=min(len(FILLER), rng.randint(1, 3)))
        rng.shuffle(body)
        (vault / "일지" / f"{d.isoformat()}.md").write_text(
            "\n\n".join(body), encoding="utf-8")
        n_notes += 1

    save_json(OUT / "queries.json", queries)
    print(f"temporal vault: {n_notes + 2} notes over 180 days -> {OUT}")
    print(f"queries: {len(queries)} "
          f"({sum(1 for q in queries if q['kind']=='recent_fact')} recent, "
          f"{sum(1 for q in queries if q['kind']=='window')} window, "
          f"{sum(1 for q in queries if q['kind']=='old_fact')} old, "
          f"{sum(1 for q in queries if q['kind']=='superseded_trap')} trap)")


if __name__ == "__main__":
    main()
