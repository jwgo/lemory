"""AgentMemQA — 일반 에이전트 메모리 벤치마크 (업무/코딩 비서, 결정적·키리스).

RoleMemQA가 롤플레잉 축이라면 이쪽은 claude-mem류 카테고리의 실제 워크로드:
코딩/업무 비서가 몇 주에 걸쳐 쌓는 세션 기억이다. 세션 노트는 Lemory의
어시스턴트 로거(`log_assistant_session`)가 쓰는 포맷 그대로(**나**/**AI** +
date frontmatter) — 벤치가 제품의 실경로를 잰다.

현실성 장치:
  - 영한 혼용 기술 대화 ("커넥션 풀 max_size는 25로"), 코드블록, 에러
    트레이스, 배포/빌드 잡담 — 한국 개발자 세션의 실제 모양.
  - 결정 번복: "Redis로 간다" → 몇 세션 뒤 "Memcached로 변경" (골드=변경
    세션, 옛 결정 세션은 채점되는 함정 — 에이전트 기억의 1등 실패 모드).
  - 값 변경: 포트/버전이 중간에 바뀜 (같은 구조).

질문 8종 · 프로젝트당 골드는 코드로 검증(정답 문자열은 골드 세션에만):
  value      설정값 회상 ("스테이징 DB 포트 뭐였지?")
  decision   결정 회상 — 번복 함정 포함 ("캐시 뭐 쓰기로 했더라?")
  person     담당자 ("결제 모듈 담당 누구지?")
  bugfix     에러→해결책 ("그 CORS 에러 어떻게 고쳤었지?")
  temporal   일정 ("베타 출시 언제라고 했지?")
  convention 팀 규칙 ("커밋 컨벤션 뭐였지?")
  twohop     담당자(세션 i) → 그 사람이 정한 규칙(세션 j)
  abstention 언급된 적 없는 사실

    python benchmarks/data/agentmemqa/generate.py   # vault/ + questions.jsonl
"""
from __future__ import annotations

import json
import random
import unicodedata
from datetime import date, timedelta
from pathlib import Path

SEED = 101
HERE = Path(__file__).parent
VAULT = HERE / "vault"
N_SESSIONS = 18  # per project

_n = lambda s: unicodedata.normalize("NFC", s)


# ------------------------------------------------------------------ pools
# 프로젝트별 유니크 값 (골드-유일성은 검증기가 보장)
PROJECTS = [
    # (name, folder)
    ("페이북 결제연동", "paybook"), ("사내 위키 개편", "wiki"),
    ("로그 파이프라인", "logpipe"), ("모바일 푸시 서버", "push"),
    ("리포트 대시보드", "dash"),
]
DB_PORT = ["5433", "5439", "6543", "5544", "7654"]
CACHE_OLD = ["Redis", "Hazelcast", "Ehcache", "Ignite", "Aerospike"]
CACHE_NEW = ["Memcached", "DragonflyDB", "KeyDB", "Garnet", "Valkey"]
OWNER = ["박선우", "이도현", "김유진", "정하람", "최서준"]
OWNER_MODULE = ["결제 모듈", "검색 모듈", "수집기", "토큰 발급기", "차트 렌더러"]
BRANCH_RULE = ["feature/티켓번호-요약", "fix/날짜-이슈명", "release/버전-rc",
               "hotfix/모듈명-증상", "chore/영역-작업명"]
COMMIT_CONV = ["conventional commits", "gitmoji", "타입: 요약 (지라키)",
               "모듈명 접두사", "50자 제한 명령형"]
ERROR_SIG = ["CORS preflight 302", "JWT aud mismatch", "OOMKilled 137",
             "deadlock detected 40P01", "ECONNRESET keep-alive"]
FIX = ["프록시에서 OPTIONS를 바로 200으로 반환", "aud 클레임을 배열로 발급",
       "힙을 512m로 내리고 스트리밍 파싱으로 전환", "락 순서를 계좌ID 오름차순으로 고정",
       "keep-alive 타임아웃을 55초로 LB보다 짧게"]
BETA_WEEK = [7, 8, 9, 10, 11]  # 베타 출시 주차 (세션 날짜에서 계산)
BUCKET = ["acme-pay-assets", "acme-wiki-media", "acme-log-cold",
          "acme-push-cred", "acme-dash-export"]
VERSION_OLD = ["1.4.2", "2.0.1", "0.9.7", "3.1.0", "1.1.9"]
VERSION_NEW = ["1.6.0", "2.2.0", "1.0.3", "3.3.1", "1.3.0"]

FILLER = [
    "오늘 배포 무사히 끝났어.", "CI가 또 느리네, 캐시 좀 봐야겠다.",
    "스탠드업에서 별 얘기 없었어.", "리뷰 두 개 남았는데 내일 볼게.",
    "테스트 커버리지 살짝 올랐더라.", "빌드 로그 너무 길어서 접었어.",
    "회의가 30분 늘어졌다...", "린터 규칙 하나 껐어, 너무 시끄러워서.",
    "지라 티켓 정리 좀 했어.", "온콜인데 조용해서 다행이야.",
]
AI_ACK = ["기록해 둘게요.", "네, 반영했습니다.", "확인했어요. 관련 메모 연결해 둘게요.",
          "좋은 결정 같네요.", "다음 세션에서 상기시켜 드릴게요.", "정리해 두었습니다."]


def _tail(name: str) -> bool:
    code = ord(name[-1])
    return 0xAC00 <= code <= 0xD7A3 and (code - 0xAC00) % 28 != 0


def _turn(who: str, text: str) -> str:
    return f"**{who}**: {text}"


def _dates(rng: random.Random) -> list[str]:
    d = date(2026, 4, rng.randint(6, 10))
    out = []
    for _ in range(N_SESSIONS):
        out.append(d.isoformat())
        d += timedelta(days=rng.randint(3, 7))
    return out


def build_project(pi: int, rng: random.Random):
    proj, _folder = PROJECTS[pi]
    dates = _dates(rng)
    plant: dict[int, list[str]] = {i: [] for i in range(N_SESSIONS)}
    F = {}

    # value: DB 포트 (코드블록 안 — 실제 세션 모양)
    F["port"] = (1, DB_PORT[pi])
    plant[1].append(_turn("나", f"스테이징 DB 접속 정보 정리했어.\n"
                                f"```\nhost: stage-db.internal\nport: {DB_PORT[pi]}\n```\n"
                                f"포트가 표준이 아니라서 자주 까먹더라."))
    # decision + 번복: 캐시 선택 (s2 옛 결정 → s11 변경 = 골드)
    old_i, new_i = 2, 11
    F["cache_old"] = (old_i, CACHE_OLD[pi])
    F["cache_new"] = (new_i, CACHE_NEW[pi])
    plant[old_i].append(_turn("나", f"세션 캐시는 {CACHE_OLD[pi]}로 가기로 했어. "
                                    f"운영 경험자가 많아서."))
    plant[new_i].append(_turn("나", f"캐시 결정 뒤집는다. {CACHE_OLD[pi]} 대신 "
                                    f"{CACHE_NEW[pi]}로 최종 확정. 메모리 단가랑 "
                                    f"운영 부담 때문이야."))
    # person: 담당자
    F["owner"] = (3, OWNER[pi], OWNER_MODULE[pi])
    plant[3].append(_turn("나", f"{OWNER_MODULE[pi]}는 {OWNER[pi]} 님이 맡기로 했어."))
    # twohop: 담당자가 정한 브랜치 규칙 (s3 사람, s8 규칙)
    rule_i = 8
    F["rule"] = (rule_i, BRANCH_RULE[pi])
    plant[rule_i].append(_turn("나", f"{OWNER[pi]} 님이 브랜치 네이밍 규칙 정했어: "
                                     f"`{BRANCH_RULE[pi]}` 형식으로 통일."))
    # bugfix: 에러 시그니처 → 해결책 (같은 세션, 트레이스 포함)
    bug_i = 6
    F["bug"] = (bug_i, ERROR_SIG[pi], FIX[pi])
    plant[bug_i].append(_turn("나", f"드디어 잡았다. 어제 그 에러:\n"
                                    f"```\n{ERROR_SIG[pi]}\n  at gateway.middleware\n```\n"
                                    f"해결은 {FIX[pi]}. 재발 방지로 러너에 회귀 테스트 추가함."))
    # temporal: 베타 출시일 (세션 날짜와 일치하는 달)
    beta_i = 12
    beta_month = int(dates[beta_i][5:7])
    beta_day = int(dates[beta_i][8:10])
    F["beta"] = (beta_i, f"{beta_month}월 {beta_day}일")
    plant[beta_i].append(_turn("나", f"베타 출시일 확정: {beta_month}월 {beta_day}일. "
                                     f"그 전주에 코드 프리즈 들어간다."))
    # convention: 커밋 컨벤션
    conv_i = 4
    F["conv"] = (conv_i, COMMIT_CONV[pi])
    plant[conv_i].append(_turn("나", f"커밋 메시지는 {COMMIT_CONV[pi]} 방식으로 "
                                     f"통일하기로 했어."))
    # value2: S3 버킷 + 버전 업그레이드 (값 변경 함정)
    F["bucket"] = (9, BUCKET[pi])
    plant[9].append(_turn("나", f"산출물은 S3 `{BUCKET[pi]}` 버킷에 올리기로 했어. "
                                f"수명주기 30일 걸어뒀고."))
    vold_i, vnew_i = 5, 14
    F["ver_old"] = (vold_i, VERSION_OLD[pi])
    F["ver_new"] = (vnew_i, VERSION_NEW[pi])
    plant[vold_i].append(_turn("나", f"SDK는 v{VERSION_OLD[pi]} 고정으로 시작한다."))
    plant[vnew_i].append(_turn("나", f"SDK를 v{VERSION_NEW[pi]}로 올렸어. 마이그레이션 "
                                     f"노트는 위키에 정리해 둠. 이제 이게 기준 버전이야."))

    # assemble — 어시스턴트 로거 포맷 그대로
    notes: dict[str, str] = {}
    for i in range(N_SESSIONS):
        turns = [_turn("나", rng.choice(FILLER))]
        turns.append(_turn("AI", rng.choice(AI_ACK)))
        for line in plant[i]:
            turns.append(line)
            turns.append(_turn("AI", rng.choice(AI_ACK)))
        while len(turns) < 12:
            turns.append(_turn("나", rng.choice(FILLER)))
            turns.append(_turn("AI", rng.choice(AI_ACK)))
        title = f"{dates[i]} 어시스턴트 {proj} s{i+1:02d}"
        body = (f"---\ndate: {dates[i]}\nsource: assistant\nlemory_generated: true\n"
                f"tags: [chat-import]\n---\n\n# {title}\n\n" + "\n\n".join(turns) + "\n")
        notes[title] = _n(body)
    return notes, F, dates


def build_questions(pi: int, F: dict, dates: list[str]) -> list[dict]:
    proj, _ = PROJECTS[pi]
    S = lambda i: f"{dates[i]} 어시스턴트 {proj} s{i+1:02d}"
    qs = []

    def q(qtype, text, answers, gold_idx, **kw):
        qs.append({"type": qtype, "q": _n(f"[{proj}] {text}"),
                   "answers": [_n(a) for a in answers],
                   "gold_notes": [S(i) for i in gold_idx], "project": proj,
                   "answerable": True, **kw})

    q("value", "스테이징 DB 포트 뭐였지?", [F["port"][1]], [F["port"][0]])
    q("value", "산출물 올리는 S3 버킷 이름이 뭐지?", [F["bucket"][1]], [F["bucket"][0]])
    # 번복 함정 2종: 캐시 결정, SDK 버전
    q("decision", "세션 캐시는 최종적으로 뭐 쓰기로 했지?", [F["cache_new"][1]],
      [F["cache_new"][0]], trap_note=S(F["cache_old"][0]), old_answer=F["cache_old"][1])
    q("decision", "지금 기준 SDK 버전이 뭐야?", [F["ver_new"][1]],
      [F["ver_new"][0]], trap_note=S(F["ver_old"][0]), old_answer=F["ver_old"][1])
    # 담당자 이름은 지정 세션과 (그가 규칙을 정한) 2홉 브릿지 세션 양쪽에
    # 정당하게 존재한다 — 어느 쪽을 찾아도 정답
    q("person", f"{F['owner'][2]} 담당이 누구지?", [F["owner"][1]],
      [F["owner"][0], F["rule"][0]])
    q("bugfix", f"{F['bug'][1]} 에러 어떻게 고쳤었지?", [F["bug"][2]], [F["bug"][0]])
    q("temporal", "베타 출시가 언제라고 했지?", [F["beta"][1]], [F["beta"][0]])
    q("convention", "커밋 메시지 컨벤션 뭐로 하기로 했지?", [F["conv"][1]], [F["conv"][0]])
    # twohop: 담당자 이름(세션 A)과 그가 정한 규칙(세션 B)
    q("twohop", f"{F['owner'][2]} 담당자가 정한 브랜치 규칙이 뭐지?", [F["rule"][1]],
      [F["rule"][0], F["owner"][0]], bridge=F["owner"][1])
    qs.append({"type": "abstention", "q": _n(f"[{proj}] 프로덕션 DB 비밀번호가 뭐지?"),
               "answers": [], "gold_notes": [], "project": proj, "answerable": False})
    qs.append({"type": "abstention", "q": _n(f"[{proj}] 작년 회고 문서 어디 있지?"),
               "answers": [], "gold_notes": [], "project": proj, "answerable": False})
    return qs


def verify(all_notes: dict[str, str], questions: list[dict]) -> None:
    for q in questions:
        if not q["answerable"]:
            continue
        proj = q["project"]
        for ans in q["answers"]:
            holders = [t for t, b in all_notes.items() if ans in b]
            gold = set(q["gold_notes"])
            assert holders, f"answer {ans!r} not planted ({q['q']})"
            bad = [h for h in holders if h not in gold and proj in h]
            cross = [h for h in holders if proj not in h]
            assert not bad, f"answer {ans!r} leaks into {bad} ({q['q']})"
            assert not cross, f"answer {ans!r} in other project {cross}"


def main() -> None:
    rng = random.Random(SEED)
    VAULT.mkdir(parents=True, exist_ok=True)
    for f in VAULT.rglob("*.md"):
        f.unlink()
    all_notes: dict[str, str] = {}
    questions: list[dict] = []
    for pi in range(len(PROJECTS)):
        notes, F, dates = build_project(pi, rng)
        _, folder = PROJECTS[pi]
        d = VAULT / folder
        d.mkdir(exist_ok=True)
        for title, body in notes.items():
            (d / f"{title}.md").write_text(body, encoding="utf-8")
        all_notes.update(notes)
        questions.extend(build_questions(pi, F, dates))
    verify(all_notes, questions)
    for i, qq in enumerate(questions):
        qq["id"] = f"amq-{i:04d}"
    out = HERE / "questions.jsonl"
    with out.open("w", encoding="utf-8") as fh:
        for qq in questions:
            fh.write(json.dumps(qq, ensure_ascii=False) + "\n")
    from collections import Counter
    print(f"vault: {len(all_notes)} session notes ({len(PROJECTS)} projects x {N_SESSIONS})")
    print(f"questions: {len(questions)} {dict(Counter(q['type'] for q in questions))}")
    print("verify: answers unique to gold sessions ✓")


if __name__ == "__main__":
    main()
