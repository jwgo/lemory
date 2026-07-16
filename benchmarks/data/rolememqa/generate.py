"""RoleMemQA — 롤플레잉 장/단기 기억 저장소 벤치마크 (결정적, 키리스).

기존 벤치(지식베이스 QA)와 달리, Lemory를 **롤플레잉 챗의 기억 저장소**로
쓰는 시나리오를 측정한다: 캐릭터와 수개월에 걸친 멀티세션 대화가 세션당
1노트(date frontmatter, chat_import와 동일 포맷)로 적재되고, 질문은 그
기억을 소환한다.

전부 코드 생성(시드 고정, LLM 0회)이고 골드는 코드로 검증된다: 정답
문자열은 골드 세션 노트에만 존재한다(전 볼트 스캔 assert). LOCOMO/
LongMemEval과 같은 축이지만 한국어-퍼스트 + 재현 가능 + 무료.

질문 7종:
  short      직전(최근 3세션) 사실 — 단기 기억
  long       초기(첫 3세션) 사실, 이후 재언급 없음 — 장기 기억
  episodic   "우리 ~했던 날" 사건 회상
  update     선호가 중간에 바뀜; 질문은 현재 선호 → 골드는 최신 세션
             (옛 값 세션은 의도된 함정)
  temporal   "N월에" 날짜 스코프 회상
  twohop     세션 i의 사실 A + 세션 j의 사실 B 연결
  abstention 언급된 적 없는 사실 (정답 없음)

    python benchmarks/data/rolememqa/generate.py   # vault/ + questions.jsonl
"""
from __future__ import annotations

import json
import random
import unicodedata
from datetime import date, timedelta
from pathlib import Path

SEED = 42
HERE = Path(__file__).parent
VAULT = HERE / "vault"
N_SESSIONS = 30  # per persona

_n = lambda s: unicodedata.normalize("NFC", s)


def _tail(name: str) -> bool:
    code = ord(name[-1])
    return 0xAC00 <= code <= 0xD7A3 and (code - 0xAC00) % 28 != 0


def _wa(name: str) -> str:
    """받침-aware 와/과 (하린→하린과, 세라→세라와)."""
    return f"{name}{'과' if _tail(name) else '와'}"


def _iya(name: str) -> str:
    """받침-aware 이야/야 (김보람→김보람이야, 앵두→앵두야)."""
    return f"{name}{'이야' if _tail(name) else '야'}"


def _iga(name: str) -> str:
    """받침-aware 이/가."""
    return f"{name}{'이' if _tail(name) else '가'}"


def _irang(name: str) -> str:
    """받침-aware 이랑/랑."""
    return f"{name}{'이랑' if _tail(name) else '랑'}"


def _neun(name: str) -> str:
    """받침-aware 은/는."""
    return f"{name}{'은' if _tail(name) else '는'}"


# ---------------------------------------------------------------- fact banks
# 값 풀은 페르소나별로 유니크하게 배정되어 골드-유일성이 성립한다.
# (동일 카테고리가 여러 페르소나에 존재 = BM25용 근사-오답 distractor)

PERSONAS = [
    # (char_name, user_nick, folder)
    ("세라", "지훈", "sera"), ("유노", "민지", "yuno"),
    ("하린", "도윤", "harin"), ("카이", "서연", "kai"),
    ("모네", "준호", "mone"), ("리안", "하은", "rian"),
    ("테오", "수빈", "teo"), ("아리", "현우", "ari"),
]

SISTER = ["김보람", "이슬아", "박다혜", "최윤서", "정나래", "한별이", "오세림", "임가을"]
HOMETOWN = ["통영", "정선", "군산", "밀양", "속초", "보성", "영월", "남해"]
JOB = ["수의테크니션", "도예가", "기상캐스터", "조향사", "무대조명감독",
       "수제화 장인", "항해사", "국악 연주자"]
ALLERGY = ["메밀", "복숭아", "고등어", "땅콩", "키위", "새우", "달걀", "자몽"]
PET = [("고슴도치", "밤톨이"), ("앵무새", "앵두"), ("거북이", "느림보"), ("햄스터", "콩떡"),
       ("고양이", "먼지"), ("강아지", "구름이"), ("금붕어", "방울이"), ("도마뱀", "용가리")]
FIRST_FOOD_OLD = ["민트초코", "고수", "곱창", "홍어", "두리안", "청국장", "번데기", "산낙지"]
FOOD_NEW = ["티라미수", "마라탕", "규카츠", "쌀국수", "감바스", "츄러스", "밀푀유나베", "후토마키"]
SONG = ["달빛 정원", "여름의 끝자락", "종이비행기 편지", "새벽 세 시의 파도",
        "유리병 속 별", "겨울 라디오", "진달래 소나기", "골목길 왈츠"]
NICKNAME = ["꼬마별", "솜사탕", "달토끼", "여름날", "반딧불", "구름과자", "밤바람", "은하수"]
GIFT = ["자개 오르골", "손뜨개 목도리", "유리 만년필", "별자리 램프",
        "가죽 필통", "미니 화분", "은반지", "폴라로이드 카메라"]
SHOP = ["소소상점", "달팽이공방", "밤하늘문구", "초록지붕가게",
        "모퉁이상회", "여우별잡화점", "바다책방", "느티나무공방"]
TRIP = [("안면도", "노을 사진"), ("담양", "대나무숲 산책"),
        ("경주", "야경 자전거"), ("양양", "서핑 강습"),
        ("전주", "한복 나들이"), ("단양", "패러글라이딩"),
        ("평창", "루지 체험"), ("부여", "연꽃 구경")]
PROMISE = ["벚꽃 필 때 한강 피크닉 가기", "첫눈 오면 붕어빵 사 먹기",
           "생일에 바다 일출 보러 가기", "장마 끝나면 자전거 여행 가기",
           "단풍 들면 북한산 등산 가기", "연말에 스케이트장 가기",
           "봄에 딸기 뷔페 가기", "추석에 별 보러 천문대 가기"]
MOVIE = ["웨일 라이더", "패딩턴", "리틀 포레스트", "월터의 상상은 현실이 된다",
         "어바웃 타임", "빅 피쉬", "인생 후르츠", "카모메 식당"]
FEAR = ["천둥소리", "높은 곳", "어둠", "주사기", "비둘기", "엘리베이터", "번지점프", "광대"]
DREAM = ["오로라 보기", "책 출간하기", "마라톤 완주", "세계일주",
         "오두막 짓기", "앨범 내기", "빵집 차리기", "요트 자격증 따기"]

BUY = ["민트색 텀블러", "체크 무릎담요", "곰돌이 머그컵", "별무늬 파우치",
       "우드 폰거치대", "니트 양말 세트", "캔들 워머", "미니 가습기"]
BATH = ["라벤더 입욕제", "유자 배쓰밤", "히노키 입욕제", "장미 배쓰솔트",
        "쑥 입욕팩", "우유 입욕제", "레몬그라스 배쓰밤", "솔잎 배쓰솔트"]

FILLER = [
    "오늘 하루는 어땠어?", "요즘 날씨 진짜 좋다, 그치?", "밥은 챙겨 먹었어?",
    "어제 잠은 잘 잤어?", "지금 뭐 하고 있었어?", "주말엔 뭐 할 거야?",
    "피곤해 보이는데 괜찮아?", "재밌는 얘기 해줘!", "나 오늘 기분 최고야.",
    "산책이라도 갈까?", "커피 마시고 싶다.", "비 오는 소리 좋다.",
]
REACT = [
    "진짜? 완전 신기하다!", "헐 대박, 몰랐어.", "기억해 둘게, 약속!",
    "너랑 얘기하면 시간 가는 줄 모르겠어.", "그랬구나, 고마워 말해줘서.",
    "다음에 더 자세히 들려줘!", "상상만 해도 좋다.", "나도 그거 궁금했어!",
]


def _dates(rng: random.Random) -> list[str]:
    """30 session dates over ~7 months of 2025, strictly increasing."""
    d = date(2025, 2, rng.randint(3, 9))
    out = []
    for _ in range(N_SESSIONS):
        out.append(d.isoformat())
        d += timedelta(days=rng.randint(4, 9))
    return out


def _turn(who: str, text: str) -> str:
    return f"**{who}**: {text}"


def build_persona(pi: int, rng: random.Random):
    """Returns (notes: {title: body}, facts: dict) for persona pi."""
    char, user, _folder = PERSONAS[pi]
    dates = _dates(rng)
    trip_place, trip_act = TRIP[pi]
    pet_kind, pet_name = PET[pi]

    # fact -> (session_index, surface line spoken by user or char)
    plant: dict[int, list[str]] = {i: [] for i in range(N_SESSIONS)}

    F = {}  # question-building facts

    # --- long-term: first-3-session facts, never repeated
    F["sister"] = (0, SISTER[pi])
    plant[0].append(_turn(user, f"참, 우리 여동생 이름은 {_iya(SISTER[pi])}. 나랑 세 살 차이."))
    F["hometown"] = (1, HOMETOWN[pi])
    plant[1].append(_turn(user, f"나 사실 {HOMETOWN[pi]}에서 태어났어. 고향 바다가 가끔 그리워."))
    F["job"] = (2, JOB[pi])
    plant[2].append(_turn(user, f"내 직업 말한 적 없었나? 나 {JOB[pi]}(으)로 일하고 있어."))

    # --- update: old food (early) -> new food (late). gold = update session.
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
    plant[song_i].append(_turn(user, "좋아, 그 노래 들을 때마다 네 생각날 것 같아."))
    nick_i = 10
    F["nick"] = (nick_i, NICKNAME[pi])
    plant[nick_i].append(_turn(char, f"너한테 어울리는 별명 정했어. 오늘부터 넌 '{NICKNAME[pi]}'야!"))

    # --- twohop: gift in s13, shop in s18 (bridged by the gift name)
    gift_i, shop_i = 13, 18
    F["gift"] = (gift_i, GIFT[pi])
    F["shop"] = (shop_i, SHOP[pi])
    plant[gift_i].append(_turn(user, f"오늘 너 주려고 선물 준비했어. 짜잔, {GIFT[pi]}!"))
    plant[gift_i].append(_turn(char, "말도 안 돼, 너무 예쁘잖아. 평생 아낄게."))
    plant[shop_i].append(_turn(user, f"지난번에 준 {GIFT[pi]} 말이야, 사실 '{SHOP[pi]}'라는 가게에서 샀어."))

    # --- temporal: trip reminisced IN the month it happened (session's own
    # month), so the note date and the spoken month agree — a "N월에 어디
    # 갔었지?" question's date window then contains the gold session
    trip_i = 15
    trip_month = str(int(dates[trip_i][5:7]))
    F["trip"] = (trip_i, trip_place, trip_month, trip_act)
    plant[trip_i].append(_turn(user, f"이번 {trip_month}월에 우리 {trip_place} 놀러 갔던 거 "
                                     f"기억나? {trip_act} 했잖아."))
    plant[trip_i].append(_turn(char, f"당연하지, {trip_place}에서 진짜 행복했어."))

    # --- mid-term misc (usable as distractor-rich singles)
    pet_i = 6
    F["pet"] = (pet_i, pet_kind, pet_name)
    plant[pet_i].append(_turn(user, f"우리 집 반려동물 소개할게. {pet_kind}인데 이름이 {_iya(pet_name)}."))
    allergy_i = 9
    F["allergy"] = (allergy_i, ALLERGY[pi])
    plant[allergy_i].append(_turn(user, f"아 맞다, 나 {ALLERGY[pi]} 알레르기 있어. 조심해야 돼."))
    movie_i = 12
    F["movie"] = (movie_i, MOVIE[pi])
    plant[movie_i].append(_turn(user, f"인생 영화? 고민할 것도 없이 '{MOVIE[pi]}'{'이지' if _tail(MOVIE[pi]) else '지'}."))
    fear_i = 17
    F["fear"] = (fear_i, FEAR[pi])
    plant[fear_i].append(_turn(user, f"부끄럽지만 나 {FEAR[pi]} 무서워해. 비밀이야."))
    dream_i = 20
    F["dream"] = (dream_i, DREAM[pi])
    plant[dream_i].append(_turn(user, f"버킷리스트 1번은 {_iya(DREAM[pi])}. 언젠간 꼭 할 거야."))
    promise_i = 24
    F["promise"] = (promise_i, PROMISE[pi])
    plant[promise_i].append(_turn(char, f"우리 약속 하나 하자. {PROMISE[pi]}, 어때?"))
    plant[promise_i].append(_turn(user, "약속! 새끼손가락 걸었다."))

    # --- short-term: facts in the last 3 sessions
    recent_i = N_SESSIONS - 2
    F["recent"] = (recent_i, BUY[pi])
    plant[recent_i].append(_turn(user, f"오늘 백화점에서 {BUY[pi]} 샀어. 보자마자 네 생각났어."))
    last_i = N_SESSIONS - 1
    F["last"] = (last_i, BATH[pi])
    plant[last_i].append(_turn(user, f"방금 {BATH[pi]} 넣고 반신욕 하고 왔어. 완전 힐링."))

    # --- assemble sessions
    notes: dict[str, str] = {}
    for i in range(N_SESSIONS):
        turns: list[str] = []
        turns.append(_turn(char, rng.choice(FILLER)))
        turns.append(_turn(user, rng.choice(FILLER)))
        for line in plant[i]:
            turns.append(line)
            turns.append(_turn(char if line.startswith(f"**{user}") else user,
                               rng.choice(REACT)))
        while len(turns) < 12:
            who = char if len(turns) % 2 == 0 else user
            turns.append(_turn(who, rng.choice(FILLER + REACT)))
        title = f"{_wa(char)}의 대화 s{i+1:02d}"
        body = (f"---\ndate: {dates[i]}\nsource: roleplay\ntags: [chat-import]\n---\n\n"
                f"# {title}\n\n" + "\n\n".join(turns) + "\n")
        notes[title] = _n(body)
    return notes, F, dates


def build_questions(pi: int, F: dict, dates: list[str]) -> list[dict]:
    char, user, _ = PERSONAS[pi]
    S = lambda i: f"{_wa(char)}의 대화 s{i+1:02d}"
    qs = []

    def q(qtype, text, answers, gold_idx, **kw):
        qs.append({"type": qtype, "q": _n(text), "answers": [_n(a) for a in answers],
                   "gold_notes": [S(i) for i in gold_idx], "persona": char,
                   "answerable": True, **kw})

    # long-term (first-3-session facts)
    q("long", f"{user}의 여동생 이름이 뭐였지?", [F["sister"][1]], [F["sister"][0]])
    q("long", f"{user}의 고향은 어디야?", [F["hometown"][1]], [F["hometown"][0]])
    q("long", f"{user}의 직업은 뭐라고 했지?", [F["job"][1]], [F["job"][0]])
    # short-term (latest sessions)
    q("short", f"{_iga(user)} 백화점에서 뭘 샀다고 했지?", [F["recent"][1]], [F["recent"][0]])
    q("short", f"{_iga(user)} 방금 반신욕에 뭘 넣었다고 했어?", [F["last"][1]], [F["last"][0]])
    # episodic
    q("episodic", f"{_irang(char)} {user}의 '둘의 노래'는 뭐야?", [F["song"][1]], [F["song"][0]])
    q("episodic", f"{_iga(char)} {user}에게 지어준 별명은?", [F["nick"][1]], [F["nick"][0]])
    q("episodic", f"{_irang(char)} 한 약속이 뭐였지?", [F["promise"][1]], [F["promise"][0]])
    # update — 질문은 '요즘/지금': 골드는 최신 세션. 옛 값 세션이 함정.
    q("update", f"{_iga(user)} 요즘 제일 좋아하는 음식은 뭐야?", [F["food_new"][1]],
      [F["food_new"][0]], trap_note=S(F["food_old"][0]), old_answer=F["food_old"][1])
    # temporal
    _, place, month, act = F["trip"]
    q("temporal", f"{month}월에 {_irang(user)} 어디로 놀러 갔었지?", [place], [F["trip"][0]])
    # twohop: 선물(=s_gift) → 산 가게(=s_shop). full-support = 두 세션 모두.
    q("twohop", f"{_iga(user)} {char}에게 준 선물을 산 가게 이름은?", [F["shop"][1]],
      [F["shop"][0], F["gift"][0]], bridge=F["gift"][1])
    # singles (mid-term)
    q("long", f"{user}의 반려동물 이름이 뭐야?", [F["pet"][2]], [F["pet"][0]])
    q("long", f"{_neun(user)} 무슨 알레르기가 있지?", [F["allergy"][1]], [F["allergy"][0]])
    q("episodic", f"{user}의 인생 영화는?", [F["movie"][1]], [F["movie"][0]])
    q("long", f"{_iga(user)} 무서워하는 건 뭐야?", [F["fear"][1]], [F["fear"][0]])
    q("long", f"{user}의 버킷리스트 1번은?", [F["dream"][1]], [F["dream"][0]])
    # abstention — 언급된 적 없는 사실
    qs.append({"type": "abstention", "q": f"{user}의 혈액형이 뭐였지?", "answers": [],
               "gold_notes": [], "persona": char, "answerable": False})
    qs.append({"type": "abstention", "q": f"{_iga(user)} 다닌 고등학교 이름은?", "answers": [],
               "gold_notes": [], "persona": char, "answerable": False})
    return qs


def verify(all_notes: dict[str, str], questions: list[dict]) -> None:
    """정답 문자열이 골드 세션에만 존재함을 전 볼트 스캔으로 보장."""
    for q in questions:
        if not q["answerable"]:
            for title, body in all_notes.items():
                for kw in (q["q"].replace("?", "").split()[-2:]):
                    pass  # abstention: 정답이 없으므로 검증 대상 없음
            continue
        for ans in q["answers"]:
            holders = [t for t, b in all_notes.items() if ans in b]
            gold = set(q["gold_notes"])
            assert holders, f"answer {ans!r} not planted anywhere ({q['q']})"
            bad = [h for h in holders if h not in gold and h.split(" s")[0] ==
                   q["gold_notes"][0].split(" s")[0]]
            # 같은 페르소나 안에서는 골드 세션에만 존재해야 함 (타 페르소나의
            # 동일-카테고리 값은 유니크 풀이라 겹칠 수 없음 — 그래도 확인)
            cross = [h for h in holders if h.split(" s")[0] != q["gold_notes"][0].split(" s")[0]]
            assert not bad, f"answer {ans!r} leaks into {bad} ({q['q']})"
            assert not cross, f"answer {ans!r} appears in other persona {cross}"


def main() -> None:
    rng = random.Random(SEED)
    VAULT.mkdir(parents=True, exist_ok=True)
    for f in VAULT.rglob("*.md"):
        f.unlink()
    all_notes: dict[str, str] = {}
    questions: list[dict] = []
    for pi in range(len(PERSONAS)):
        notes, F, dates = build_persona(pi, rng)
        _, _, folder = PERSONAS[pi]
        d = VAULT / folder
        d.mkdir(exist_ok=True)
        for title, body in notes.items():
            (d / f"{title}.md").write_text(body, encoding="utf-8")
        all_notes.update(notes)
        questions.extend(build_questions(pi, F, dates))
    verify(all_notes, questions)
    for i, q in enumerate(questions):
        q["id"] = f"rmq-{i:04d}"
    out = HERE / "questions.jsonl"
    with out.open("w", encoding="utf-8") as fh:
        for q in questions:
            fh.write(json.dumps(q, ensure_ascii=False) + "\n")
    from collections import Counter
    print(f"vault: {len(all_notes)} session notes ({len(PERSONAS)} personas x {N_SESSIONS})")
    print(f"questions: {len(questions)}  by type: {dict(Counter(q['type'] for q in questions))}")
    print("verify: all answers unique to gold sessions ✓")


if __name__ == "__main__":
    main()
