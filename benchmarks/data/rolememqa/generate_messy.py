"""RoleMemQA-messy — 지저분한 실채팅 변형 (결정적, 키리스).

클린 벤치(generate.py)는 사실이 또렷하게 한 번 진술된다 — 필요조건 테스트.
실제 채팅은 그렇지 않다: 농담으로 가짜를 말하고, 나중에 번복하고, 잡담이
사실 어휘를 오염시킨다. 이 변형이 그 지저분함을 코드-검증 가능하게 재현한다:

  retraction  세션 i에서 가짜 값 진술 → 세션 j(>i)에서 번복+진짜 값.
              골드 = 번복 세션, 가짜 세션은 함정 (trap_above_gold 측정).
  joke        같은 턴 안에서 "X! ㅋㅋ 농담이고 진짜는 Y" — 골드 세션 하나에
              가짜와 진짜가 공존. 검색은 그 세션을 찾아야 하고, 컨텍스트
              소비자는 노이즈 속 진짜를 읽어야 한다 (ans@k로 측정).
  noise       필러가 사실-카테고리 어휘(약속/영화/음식...)를 흩뿌리고
              세션당 턴 수 12→18 — 보일러플레이트 오염 증폭.

나머지 유형(short/long/episodic/update/temporal/twohop/abstention)은 클린
벤치와 동일 구조를 노이즈 위에서 반복한다. 골드-유일성은 동일하게 전 볼트
스캔으로 assert (가짜 값은 함정 세션+번복 세션에만 존재 가능).

    python benchmarks/data/rolememqa/generate_messy.py  # vault-messy/ + questions_messy.jsonl
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from generate import (ALLERGY, BATH, BUY, DREAM, FEAR, FILLER, FOOD_NEW,
                      FIRST_FOOD_OLD, GIFT, HOMETOWN, JOB, MOVIE, NICKNAME,
                      PERSONAS, PET, PROMISE, REACT, SHOP, SISTER, SONG, TRIP,
                      N_SESSIONS, _dates, _iga, _irang, _iya, _n, _neun,
                      _tail, _turn, _wa)

SEED = 77
HERE = Path(__file__).parent
VAULT = HERE / "vault-messy"

# 번복 유형의 가짜 여동생 이름 (진짜 SISTER 풀과 절대 안 겹치는 유니크 풀)
FAKE_SISTER = ["엘라", "루시퍼", "모모카", "제니퍼", "츠바키", "빅토리아",
               "카산드라", "미네르바"]
# 농담 유형의 가짜 인생영화
FAKE_MOVIE = ["무한도전 극장판", "어벤져스 개봉 축하 영상", "옆집 CCTV 하이라이트",
              "회사 워크숍 브이로그", "군대 훈련소 다큐", "삼촌 결혼식 영상",
              "동네 마트 세일 광고", "졸업식 실황"]

# 사실-카테고리 어휘를 흩뿌리는 오염 필러 (정답 값은 절대 포함하지 않음)
NOISE_FILLER = [
    "오늘 저녁 음식 뭐 먹을까 고민된다.", "주말에 영화나 볼까?",
    "약속 시간 늦지 않게 조심해!", "선물 고르는 건 늘 어렵네.",
    "여행 가고 싶다, 어디든!", "노래 하나 추천해줘!",
    "요즘 알레르기 철이라 힘들다.", "별명 짓는 센스가 필요해.",
    "우리 집 근처에 새 가게 생겼더라.", "버킷리스트 얘기 나중에 또 하자.",
]


def build_persona_messy(pi: int, rng: random.Random):
    char, user, _folder = PERSONAS[pi]
    dates = _dates(rng)
    trip_place, trip_act = TRIP[pi]
    pet_kind, pet_name = PET[pi]
    plant: dict[int, list[str]] = {i: [] for i in range(N_SESSIONS)}
    F = {}

    # --- retraction: 가짜 이름(s0) → 번복+진짜(s3). 골드 = s3, 함정 = s0.
    fake = FAKE_SISTER[pi]
    plant[0].append(_turn(user, f"참, 우리 여동생 이름은 {_iya(fake)}. 좀 특이하지?"))
    retr_i = 3
    F["sister"] = (retr_i, SISTER[pi], 0, fake)
    plant[retr_i].append(_turn(
        user, f"저번에 여동생 이름 {fake}라고 했잖아? 그거 뻥이었어 ㅋㅋ "
              f"진짜 이름은 {_iya(SISTER[pi])}. 미안!"))
    plant[retr_i].append(_turn(char, "뭐야, 속았잖아! 그래도 말해줘서 고마워."))

    # --- long-term (클린과 동일 구조, 노이즈 위)
    F["hometown"] = (1, HOMETOWN[pi])
    plant[1].append(_turn(user, f"나 사실 {HOMETOWN[pi]}에서 태어났어. 고향 바다가 가끔 그리워."))
    F["job"] = (2, JOB[pi])
    plant[2].append(_turn(user, f"내 직업 말한 적 없었나? 나 {JOB[pi]}(으)로 일하고 있어."))

    # --- update (클린과 동일: 옛 선호 → 새 선호)
    old_i, new_i = 4, 22
    F["food_old"] = (old_i, FIRST_FOOD_OLD[pi])
    F["food_new"] = (new_i, FOOD_NEW[pi])
    plant[old_i].append(_turn(user, f"내가 제일 좋아하는 음식은 {_iya(FIRST_FOOD_OLD[pi])}!"))
    plant[new_i].append(_turn(
        user, f"요즘은 입맛이 바뀌어서 제일 좋아하는 음식이 {_iga(FOOD_NEW[pi])} 됐어. "
              f"전에 좋아하던 건 좀 질렸나 봐."))

    # --- episodic
    song_i = 7
    F["song"] = (song_i, SONG[pi])
    plant[song_i].append(_turn(char, f"오늘부터 '{SONG[pi]}'를 우리 둘의 노래로 하자! 어때?"))
    nick_i = 10
    F["nick"] = (nick_i, NICKNAME[pi])
    plant[nick_i].append(_turn(char, f"너한테 어울리는 별명 정했어. 오늘부터 넌 '{NICKNAME[pi]}'야!"))

    # --- joke: 같은 턴에 가짜+진짜 공존. 골드 = 이 세션 (유일).
    movie_i = 12
    fake_m = FAKE_MOVIE[pi]
    F["movie"] = (movie_i, MOVIE[pi], fake_m)
    plant[movie_i].append(_turn(
        user, f"내 인생 영화? 음... '{fake_m}'! ㅋㅋㅋ 농담이고, "
              f"진짜 인생 영화는 '{MOVIE[pi]}'{'이지' if _tail(MOVIE[pi]) else '지'}."))
    plant[movie_i].append(_turn(char, "잠깐 진짜인 줄 알았잖아!"))

    # --- twohop / temporal / misc (클린과 동일 구조)
    gift_i, shop_i = 13, 18
    F["gift"] = (gift_i, GIFT[pi])
    F["shop"] = (shop_i, SHOP[pi])
    plant[gift_i].append(_turn(user, f"오늘 너 주려고 선물 준비했어. 짜잔, {GIFT[pi]}!"))
    plant[shop_i].append(_turn(user, f"지난번에 준 {GIFT[pi]} 말이야, 사실 '{SHOP[pi]}'라는 가게에서 샀어."))
    trip_i = 15
    trip_month = str(int(dates[trip_i][5:7]))
    F["trip"] = (trip_i, trip_place, trip_month, trip_act)
    plant[trip_i].append(_turn(user, f"이번 {trip_month}월에 우리 {trip_place} 놀러 갔던 거 "
                                     f"기억나? {trip_act} 했잖아."))
    pet_i = 6
    F["pet"] = (pet_i, pet_kind, pet_name)
    plant[pet_i].append(_turn(user, f"우리 집 반려동물 소개할게. {pet_kind}인데 이름이 {_iya(pet_name)}."))
    allergy_i = 9
    F["allergy"] = (allergy_i, ALLERGY[pi])
    plant[allergy_i].append(_turn(user, f"아 맞다, 나 {ALLERGY[pi]} 알레르기 있어. 조심해야 돼."))
    fear_i = 17
    F["fear"] = (fear_i, FEAR[pi])
    plant[fear_i].append(_turn(user, f"부끄럽지만 나 {FEAR[pi]} 무서워해. 비밀이야."))
    dream_i = 20
    F["dream"] = (dream_i, DREAM[pi])
    plant[dream_i].append(_turn(user, f"버킷리스트 1번은 {_iya(DREAM[pi])}. 언젠간 꼭 할 거야."))
    promise_i = 24
    F["promise"] = (promise_i, PROMISE[pi])
    plant[promise_i].append(_turn(char, f"우리 약속 하나 하자. {PROMISE[pi]}, 어때?"))
    recent_i = N_SESSIONS - 2
    F["recent"] = (recent_i, BUY[pi])
    plant[recent_i].append(_turn(user, f"오늘 백화점에서 {BUY[pi]} 샀어. 보자마자 네 생각났어."))
    last_i = N_SESSIONS - 1
    F["last"] = (last_i, BATH[pi])
    plant[last_i].append(_turn(user, f"방금 {BATH[pi]} 넣고 반신욕 하고 왔어. 완전 힐링."))

    # --- assemble: 오염 필러 포함, 세션당 18턴 (클린은 12)
    pool = FILLER + NOISE_FILLER
    notes: dict[str, str] = {}
    for i in range(N_SESSIONS):
        turns = [_turn(char, rng.choice(pool)), _turn(user, rng.choice(pool))]
        for line in plant[i]:
            turns.append(line)
            turns.append(_turn(char if line.startswith(f"**{user}") else user,
                               rng.choice(REACT)))
        while len(turns) < 18:
            who = char if len(turns) % 2 == 0 else user
            turns.append(_turn(who, rng.choice(pool + REACT)))
        title = f"{_wa(char)}의 대화 s{i+1:02d}"
        body = (f"---\ndate: {dates[i]}\nsource: roleplay\ntags: [chat-import]\n---\n\n"
                f"# {title}\n\n" + "\n\n".join(turns) + "\n")
        notes[title] = _n(body)
    return notes, F


def build_questions_messy(pi: int, F: dict) -> list[dict]:
    char, user, _ = PERSONAS[pi]
    S = lambda i: f"{_wa(char)}의 대화 s{i+1:02d}"
    qs = []

    def q(qtype, text, answers, gold_idx, **kw):
        qs.append({"type": qtype, "q": _n(text), "answers": [_n(a) for a in answers],
                   "gold_notes": [S(i) for i in gold_idx], "persona": char,
                   "answerable": True, **kw})

    # retraction: 정답은 번복 세션의 진짜 이름. 가짜 세션이 함정.
    ri, real, fi, fake = F["sister"]
    q("retraction", f"{user}의 여동생 진짜 이름이 뭐야?", [real], [ri],
      trap_note=S(fi), fake_answer=fake)
    # joke: 가짜+진짜가 같은 세션 — ans@k가 진짜 문자열 요구
    mi, real_m, fake_m = F["movie"]
    q("joke", f"{user}의 진짜 인생 영화는 뭐야?", [real_m], [mi], fake_answer=fake_m)
    # 클린과 동일 구조 유형들 (노이즈 위 반복)
    q("long", f"{user}의 고향은 어디야?", [F["hometown"][1]], [F["hometown"][0]])
    q("long", f"{user}의 직업은 뭐라고 했지?", [F["job"][1]], [F["job"][0]])
    q("short", f"{_iga(user)} 백화점에서 뭘 샀다고 했지?", [F["recent"][1]], [F["recent"][0]])
    q("short", f"{_iga(user)} 방금 반신욕에 뭘 넣었다고 했어?", [F["last"][1]], [F["last"][0]])
    q("episodic", f"{_irang(char)} {user}의 '둘의 노래'는 뭐야?", [F["song"][1]], [F["song"][0]])
    q("episodic", f"{_iga(char)} {user}에게 지어준 별명은?", [F["nick"][1]], [F["nick"][0]])
    q("episodic", f"{_irang(char)} 한 약속이 뭐였지?", [F["promise"][1]], [F["promise"][0]])
    q("update", f"{_iga(user)} 요즘 제일 좋아하는 음식은 뭐야?", [F["food_new"][1]],
      [F["food_new"][0]], trap_note=S(F["food_old"][0]), old_answer=F["food_old"][1])
    _, place, month, act = F["trip"]
    q("temporal", f"{month}월에 {_irang(user)} 어디로 놀러 갔었지?", [place], [F["trip"][0]])
    q("twohop", f"{_iga(user)} {char}에게 준 선물을 산 가게 이름은?", [F["shop"][1]],
      [F["shop"][0], F["gift"][0]], bridge=F["gift"][1])
    q("long", f"{user}의 반려동물 이름이 뭐야?", [F["pet"][2]], [F["pet"][0]])
    q("long", f"{_neun(user)} 무슨 알레르기가 있지?", [F["allergy"][1]], [F["allergy"][0]])
    q("long", f"{_iga(user)} 무서워하는 건 뭐야?", [F["fear"][1]], [F["fear"][0]])
    q("long", f"{user}의 버킷리스트 1번은?", [F["dream"][1]], [F["dream"][0]])
    qs.append({"type": "abstention", "q": f"{user}의 혈액형이 뭐였지?", "answers": [],
               "gold_notes": [], "persona": char, "answerable": False})
    qs.append({"type": "abstention", "q": f"{_iga(user)} 다닌 고등학교 이름은?", "answers": [],
               "gold_notes": [], "persona": char, "answerable": False})
    return qs


def verify(all_notes: dict[str, str], questions: list[dict]) -> None:
    """정답 문자열이 골드 세션에만 존재. 가짜 값(fake_answer)은 함정/골드
    세션에만 존재할 수 있고, 그 밖으로 새면 안 된다."""
    for q in questions:
        if not q["answerable"]:
            continue
        persona_prefix = q["gold_notes"][0].split(" s")[0]
        for ans in q["answers"]:
            holders = [t for t, b in all_notes.items() if ans in b]
            gold = set(q["gold_notes"])
            assert holders, f"answer {ans!r} not planted ({q['q']})"
            bad = [h for h in holders if h not in gold
                   and h.split(" s")[0] == persona_prefix]
            cross = [h for h in holders if h.split(" s")[0] != persona_prefix]
            assert not bad, f"answer {ans!r} leaks into {bad} ({q['q']})"
            assert not cross, f"answer {ans!r} in other persona {cross}"
        fake = q.get("fake_answer")
        if fake:
            allowed = set(q["gold_notes"]) | {q.get("trap_note")}
            holders = [t for t, b in all_notes.items() if fake in b
                       and t.split(" s")[0] == persona_prefix]
            assert set(holders) <= allowed, \
                f"fake {fake!r} leaks beyond trap/gold: {holders}"


def main() -> None:
    rng = random.Random(SEED)
    VAULT.mkdir(parents=True, exist_ok=True)
    for f in VAULT.rglob("*.md"):
        f.unlink()
    all_notes: dict[str, str] = {}
    questions: list[dict] = []
    for pi in range(len(PERSONAS)):
        notes, F = build_persona_messy(pi, rng)
        _, _, folder = PERSONAS[pi]
        d = VAULT / folder
        d.mkdir(exist_ok=True)
        for title, body in notes.items():
            (d / f"{title}.md").write_text(body, encoding="utf-8")
        all_notes.update(notes)
        questions.extend(build_questions_messy(pi, F))
    verify(all_notes, questions)
    for i, qq in enumerate(questions):
        qq["id"] = f"rmqm-{i:04d}"
    out = HERE / "questions_messy.jsonl"
    with out.open("w", encoding="utf-8") as fh:
        for qq in questions:
            fh.write(json.dumps(qq, ensure_ascii=False) + "\n")
    from collections import Counter
    print(f"vault-messy: {len(all_notes)} notes | questions: {len(questions)} "
          f"{dict(Counter(q['type'] for q in questions))}")
    print("verify: answers unique to gold; fakes confined to trap/gold ✓")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(HERE))
    main()
