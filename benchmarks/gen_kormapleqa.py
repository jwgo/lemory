"""KorMapleQA — 실제 나무위키 메이플스토리 코퍼스(1,469 문서) 위의
결정적·코드검증 한국어 RAG 벤치마크 생성기.

LLM 초안 없이 100% 코드로 생성되므로 (a) API 키 없이 재현 가능하고
(b) 모든 문항이 기계 검증 가능한 불변식을 갖는다:

  S  단일 사실   인포박스 표/불릿의 (키, 값) — 정답이 골드 문서에 존재
  M  마스킹      엔티티를 제목 대신 '코퍼스 전체에서 유일한 속성값'으로
                 지칭 — 제목 부스트가 아니라 내용 검색을 강제
  H  2-hop      A 문서 인포박스의 위키링크 값 → B 문서의 사실.
                 정답은 B에만 있고 A에는 없음을 검증 (지름길 차단)
  T  시간       "YYYY년 M월 D일 ... 등장/출시/추가" 서술
  A  무응답     덤프(2021-03-01) 이후 콘텐츠 — 코퍼스 전체 부재를 검증.
                 e2e 시스템은 '모른다'가 정답, 검색 시스템은 별도 리포트

변형(robustness) 축: 문어체 원문 → 구어체(반말+동의어), 키워드, 오타
(자모 시드 고정) — 같은 골드로 재질의.

사용:
    python benchmarks/gen_kormapleqa.py            # 생성 + 검증 + 통계
    python benchmarks/gen_kormapleqa.py --sample   # 유형별 샘플 출력

출력: benchmarks/data/kormapleqa/questions.jsonl (+ README.md 는 수동 관리)
라이선스: 질문 텍스트는 코드 생성물, 정답/문맥은 나무위키 CC BY-NC-SA 2.0 KR.
"""

from __future__ import annotations

import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

BENCH = Path(__file__).parent
VAULT = BENCH / "data" / "maple_real" / "vault"
OUT_DIR = BENCH / "data" / "kormapleqa"

SEED = 20260711
MAX_S_PER_DOC = 3

# ---------------------------------------------------------------- utilities

_HANGUL = re.compile(r"[가-힣]")


def _jong(ch: str) -> bool:
    """True if the syllable has a final consonant (받침)."""
    code = ord(ch)
    return 0xAC00 <= code <= 0xD7A3 and (code - 0xAC00) % 28 != 0


def _last_hangul(word: str) -> str:
    for ch in reversed(word):
        if 0xAC00 <= ord(ch) <= 0xD7A3:
            return ch
    return ""


def _topic(word: str) -> str:  # 은/는 — 조사는 마지막 한글 음절 기준
    ch = _last_hangul(word)
    return "은" if ch and _jong(ch) else "는"


def _subj(word: str) -> str:  # 이/가
    ch = _last_hangul(word)
    return "이" if ch and _jong(ch) else "가"


def normalize(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^\w가-힣]+", "", s, flags=re.UNICODE)
    return s


# ------------------------------------------------------------- namu parsing

_LINK_RE = re.compile(r"\[\[([^\]\|]+)(?:\|([^\]]*))?\]\]")
_DIRECTIVE_RE = re.compile(r"<[^>]{1,60}>")
_BOLD_RE = re.compile(r"\*\*")
_INCLUDE_RE = re.compile(r"\[include\([^)]*\)\]", re.IGNORECASE)


def clean_cell(cell: str) -> tuple[str, list[str]]:
    """Strip namu formatting from a table cell.

    Returns (display_text, link_targets)."""
    links = []

    def _sub(m: re.Match) -> str:
        target = m.group(1).strip()
        alias = (m.group(2) or "").strip()
        if not target.startswith(("파일:", ":파일:", "틀:", "분류:")):
            links.append(target)
        return alias or target

    s = _LINK_RE.sub(_sub, cell)
    s = _INCLUDE_RE.sub(" ", s)
    s = _DIRECTIVE_RE.sub(" ", s)
    s = _BOLD_RE.sub("", s)
    return re.sub(r"\s+", " ", s).strip(), links


def parse_doc(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8", errors="replace")
    lines = raw.splitlines()
    cats = []
    if lines and lines[0].startswith("#"):
        cats = [t.lstrip("#") for t in lines[0].split() if t.startswith("#")]
    section = "개요"
    kv: list[dict] = []          # {key, value, links, section}
    for line in lines:
        h = re.match(r"^#{2,4}\s+(.+)$", line)
        if h:
            section = h.group(1).strip()
            continue
        if line.startswith("|"):
            cells_raw = [c for c in line.strip().strip("|").split("|")]
            cleaned = [clean_cell(c) for c in cells_raw]
            vis = [(t, ls) for t, ls in cleaned if t]
            if len(vis) == 2:
                k, kl = vis[0]
                v, vl = vis[1]
                if 1 <= len(k) <= 24 and v and not kl:
                    kv.append({"key": k, "value": v, "links": vl, "section": section})
        else:
            b = re.match(r"^\s*-\s*([^:]{1,24}):\s*(.+)$", line)
            if b:
                v, vl = clean_cell(b.group(2))
                if v:
                    kv.append({"key": b.group(1).strip(), "value": v,
                               "links": vl, "section": section})
    text_display, _ = clean_cell(raw)
    return {"title": path.stem, "cats": cats, "kv": kv, "raw": raw,
            "norm": normalize(text_display)}


# ------------------------------------------------------ corpus + title maps

def load_corpus() -> dict[str, dict]:
    docs = {}
    for p in sorted(VAULT.glob("*.md")):
        docs[p.stem] = parse_doc(p)
    return docs


def link_to_title(target: str, docs: dict) -> str | None:
    """Resolve a wikilink target to a vault note title.

    namu_filter writes '문서/하위' as '문서-하위.md', and drops anchors."""
    t = target.split("#")[0].strip()
    for cand in (t, t.replace("/", "-")):
        if cand in docs:
            return cand
    return None


def display_name(title: str) -> str:
    """Natural entity name for question text."""
    name = re.sub(r"\((메이플스토리|메이플스토리2|메이플스토리M)\)", "", title)
    name = name.replace("-보스 몬스터", "").replace("/보스 몬스터", "")
    return name.strip()


def category_noun(cats: list[str]) -> str:
    joined = " ".join(cats)
    for pat, noun in (("보스_몬스터", "보스"), ("일반_몬스터", "몬스터"),
                      ("지역", "지역"), ("아이템", "아이템"), ("장비", "장비"),
                      ("등장인물", "캐릭터"), ("직업", "직업"), ("스킬", "스킬")):
        if pat in joined:
            return noun
    return "문서"


# ------------------------------------------------------- question templates

# curated key phrasing: key -> (질문구, 동의어(구어), 질문형)
KEY_TEMPLATES = {
    "레벨": "레벨",
    "HP": "HP(체력)",
    "MP": "MP",
    "EXP": "경험치(EXP)",
    "테마곡": "테마곡",
    "제한 시간": "제한 시간",
    "물리 공격": "물리 공격력",
    "마법 공격": "마법 공격력",
    "위치": "위치",
    "이명": "이명(별칭)",
    "소속 월드": "소속 월드",
    "소속 대륙": "소속 대륙",
    "적정 레벨": "적정 레벨",
    "GMS": "북미(GMS) 서버 명칭",
    "JMS": "일본(JMS) 서버 명칭",
    "CMS": "중국(CMS) 서버 명칭",
    "TMS": "대만(TMS) 서버 명칭",
    "MSEA": "동남아(MSEA) 서버 명칭",
    "반감": "속성 반감",
    "종족": "종족",
    "성우": "성우",
    "직업": "직업",
    "소속": "소속",
    "무기": "무기",
    "출시일": "출시일",
    "가격": "가격",
}

CASUAL_SYNONYM = {
    "테마곡": "브금", "HP(체력)": "피통", "제한 시간": "타임 리밋",
    "북미(GMS) 서버 명칭": "글섭 이름", "일본(JMS) 서버 명칭": "일섭 이름",
    "레벨": "렙", "적정 레벨": "적정렙", "경험치(EXP)": "경치",
    "물리 공격력": "물공", "마법 공격력": "마공", "이명(별칭)": "별명",
}

_BAD_VALUES = re.compile(
    r"펼치기|접기|^없음$|^-$|^\?+$|파일:|^등장(인물)?$|불명|미상|알 수 없|^상동$")
_GENERIC_KEYS = {"마크", "BGM", "비고", "기타", "이미지", "일러스트"}


def value_ok(v: str) -> bool:
    return (2 <= len(v) <= 60 and not _BAD_VALUES.search(v)
            and normalize(v) != "")


def render_q(entity: str, key_phrase: str) -> str:
    return f"{entity}의 {key_phrase}{_topic(key_phrase)} 무엇인가?"


# --------------------------------------------------------------- generators

def gen_single(docs: dict) -> list[dict]:
    out = []
    for title, d in docs.items():
        if "메이플스토리2" in " ".join(d["cats"]):
            continue  # 본편만: 메이플스토리2/M 문서는 도메인 노이즈
        ent = display_name(title)
        if not ent or len(ent) < 2:
            continue
        picked = 0
        seen_keys = set()
        for f in d["kv"]:
            if picked >= MAX_S_PER_DOC:
                break
            key = f["key"].strip()
            if key in _GENERIC_KEYS or key in seen_keys:
                continue
            kp = KEY_TEMPLATES.get(key)
            if kp is None or not value_ok(f["value"]):
                continue
            ans_norm = normalize(f["value"])
            if not ans_norm or ans_norm not in d["norm"]:
                continue
            # 문서 안에서 같은 키가 여러 값이면 (페이즈별 표 등) 모호 — 스킵
            vals = {normalize(x["value"]) for x in d["kv"] if x["key"].strip() == key}
            if len(vals) > 1:
                continue
            seen_keys.add(key)
            picked += 1
            out.append({
                "type": "single", "q": render_q(ent, kp),
                "answers": [f["value"]], "gold_notes": [title],
                "masked": False, "key": key, "section": f["section"],
            })
    return out


def gen_masked(docs: dict, singles: list[dict]) -> list[dict]:
    """엔티티를 제목 없이 '유일 속성값'으로 지칭. 식별값은 코퍼스 전체에서
    정확히 1개 문서에만 등장해야 한다."""
    # 전체 노트의 normalized text 캐시로 유일성 검증
    out = []
    by_doc: dict[str, list[dict]] = defaultdict(list)
    for s in singles:
        by_doc[s["gold_notes"][0]].append(s)
    for title, facts in by_doc.items():
        if len(facts) < 2:
            continue
        d = docs[title]
        noun = category_noun(d["cats"])
        # 식별자 후보: 값이 충분히 길고 유일한 fact
        for ident in facts:
            iv = normalize(ident["answers"][0])
            if len(iv) < 4:
                continue
            holders = sum(1 for t2, d2 in docs.items() if iv in d2["norm"])
            if holders != 1:
                continue
            for target in facts:
                if target is ident:
                    continue
                ikp = KEY_TEMPLATES[ident["key"]]
                tkp = KEY_TEMPLATES[target["key"]]
                q = (f"{ikp}{_subj(ikp)} '{ident['answers'][0]}'인 {noun}의 "
                     f"{tkp}{_topic(tkp)} 무엇인가?")
                ent_norm = normalize(display_name(title))
                if ent_norm and ent_norm in normalize(q):
                    continue  # 제목 누출
                out.append({
                    "type": "masked", "q": q, "answers": target["answers"],
                    "gold_notes": [title], "masked": True,
                    "ident_key": ident["key"], "key": target["key"],
                })
                break  # 문서당 masked 1개
            break
    return out


def gen_twohop(docs: dict) -> list[dict]:
    """A 인포박스의 위키링크 값 → B 문서의 사실. 정답은 B에만."""
    out = []
    for title, d in docs.items():
        if "메이플스토리2" in " ".join(d["cats"]):
            continue
        ent = display_name(title)
        for f in d["kv"]:
            key = f["key"].strip()
            if key not in KEY_TEMPLATES or len(f["links"]) != 1:
                continue
            b_title = link_to_title(f["links"][0], docs)
            if b_title is None or b_title == title:
                continue
            db = docs[b_title]
            # B의 사실 중 A에 없는 값 선택
            for fb in db["kv"]:
                bkey = fb["key"].strip()
                if bkey not in KEY_TEMPLATES or not value_ok(fb["value"]):
                    continue
                if bkey == key:
                    continue
                ansn = normalize(fb["value"])
                if not ansn or ansn not in db["norm"] or ansn in d["norm"]:
                    continue  # 지름길 차단: 정답이 A에도 있으면 스킵
                vals = {normalize(x["value"]) for x in db["kv"]
                        if x["key"].strip() == bkey}
                if len(vals) > 1:
                    continue
                rel = _REL_PHRASES.get(key)
                if rel is None:
                    continue
                rel = rel.format(s=_subj(ent))
                bkp = KEY_TEMPLATES[bkey]
                bn = display_name(b_title)
                if normalize(bn) and normalize(bn) in normalize(ent):
                    continue
                q = f"{ent}{rel} {bkp}{_topic(bkp)} 무엇인가?"
                out.append({
                    "type": "twohop", "q": q, "answers": [fb["value"]],
                    "gold_notes": [title, b_title], "masked": True,
                    "bridge": title, "key": f"{key}->{bkey}",
                })
                break
            else:
                continue
            break  # 문서당 2-hop 1개
    return out


# 2-hop 질문의 자연스러운 관계 표현: "{s}" 자리에 이/가 조사가 들어간다
_REL_PHRASES = {
    "위치": "{s} 위치한 지역의",
    "소속 월드": "{s} 속한 월드의",
    "소속 대륙": "{s} 속한 대륙의",
    "소속": "{s} 소속된 곳의",
    "보스": "의 보스인 몬스터의",
    "무기": "{s} 쓰는 무기의",
}


_DATE_RE = re.compile(
    r"(\d{4}년 \d{1,2}월 \d{1,2}일)(?:[^.\n]{0,50}?)"
    r"(등장했|출시되|업데이트되|추가되|공개되|시작되|발생했)")

_EVENT_VERB = {"등장했": "등장한", "출시되": "출시된", "업데이트되": "업데이트된",
               "추가되": "추가된", "공개되": "공개된", "시작되": "시작된",
               "발생했": "발생한"}


def gen_temporal(docs: dict) -> list[dict]:
    out = []
    for title, d in docs.items():
        if "메이플스토리2" in " ".join(d["cats"]):
            continue
        m = _DATE_RE.search(d["raw"][:2500])
        if not m:
            continue
        date, verb = m.group(1), m.group(2)
        ent = display_name(title)
        if normalize(date) not in d["norm"]:
            continue
        q = f"{ent}{_subj(ent)} {_EVENT_VERB[verb]} 날짜는 언제인가?"
        out.append({
            "type": "temporal", "q": q, "answers": [date],
            "gold_notes": [title], "masked": False, "key": "date",
        })
    return out


# 덤프(2021-03-01) 이후에 등장한 콘텐츠 — 코퍼스에 답이 없어야 정상
_ABSTENTION_ENTITIES = [
    ("데스티니(업데이트)", "데스티니 업데이트에서 리마스터된 직업군은 무엇인가?"),
    ("이그니션(업데이트)", "이그니션 업데이트의 시작일은 언제인가?"),
    ("최초의 대적자", "최초의 대적자 스킬의 마스터 레벨은 몇인가?"),
    ("림보(메이플스토리)", "보스 림보의 입장 조건은 무엇인가?"),
    ("발드릭스", "보스 발드릭스의 요구 전투력은 얼마인가?"),
    ("솔 에르다", "솔 에르다 조각의 최대 소지 개수는 몇 개인가?"),
    ("챌린저스 서버", "챌린저스 서버의 참여 조건은 무엇인가?"),
    ("하이퍼 버닝 MAX", "하이퍼 버닝 MAX의 레벨 상한은 몇인가?"),
    ("선택받은 세렌", "선택받은 세렌 보스의 클리어 보상은 무엇인가?"),
    ("감시자 칼로스", "감시자 칼로스의 입장 레벨 제한은 몇인가?"),
    ("카링(메이플스토리)", "보스 카링의 요구 아케인 포스는 얼마인가?"),
    ("6차 전직", "6차 전직이 가능한 레벨은 몇인가?"),
    ("헥사 매트릭스", "헥사 매트릭스 강화에 필요한 재화는 무엇인가?"),
    ("어둠의 발현", "어둠의 발현 이벤트 보상은 무엇인가?"),
    ("뉴에이지(업데이트)", "뉴에이지 업데이트의 출시일은 언제인가?"),
    ("에오스탑 리마스터", "에오스탑 리마스터에서 바뀐 몬스터 레벨은 몇인가?"),
]


def gen_abstention(docs: dict) -> list[dict]:
    out = []
    for ident, q in _ABSTENTION_ENTITIES:
        key = normalize(ident.split("(")[0])
        holders = [t for t, d in docs.items() if key in d["norm"]]
        if holders:
            continue  # 코퍼스에 존재 — 무응답 문항으로 부적격
        out.append({
            "type": "abstention", "q": q, "answers": [],
            "gold_notes": [], "masked": True, "key": ident,
            "answerable": False,
        })
    return out


# ------------------------------------------------------------ variants

_TYPO_RNG = random.Random(SEED)


def _typo(word: str) -> str:
    """Deterministic single-syllable typo: swap two adjacent Hangul syllables
    of the longest word (길이 4+), like a fat-finger transposition."""
    runs = sorted(re.findall(r"[가-힣]{4,}", word), key=len, reverse=True)
    if not runs:
        return word
    run = runs[0]
    i = _TYPO_RNG.randrange(len(run) - 1)
    swapped = run[:i] + run[i + 1] + run[i] + run[i + 2:]
    return word.replace(run, swapped, 1)


def gen_variants(questions: list[dict], n: int = 220) -> list[dict]:
    rng = random.Random(SEED)
    singles = [q for q in questions if q["type"] == "single"]
    sample = rng.sample(singles, min(n, len(singles)))
    out = []
    for q in sample:
        ent_key = q["q"].split("의 ", 1)
        if len(ent_key) != 2:
            continue
        ent = ent_key[0]
        plain_key = q["key"]  # 괄호 설명 없는 원 키
        kp = KEY_TEMPLATES.get(q["key"], q["key"])
        out.append({**q, "type": "kw", "q": f"{ent} {plain_key}"})
        syn = CASUAL_SYNONYM.get(kp, plain_key)
        out.append({**q, "type": "casual", "q": f"{ent} {syn} 뭐야?"})
        out.append({**q, "type": "typo", "q": _typo(q["q"])})
    return out


# ------------------------------------------------------------- verification

def verify(questions: list[dict], docs: dict) -> list[dict]:
    ok = []
    for q in questions:
        if not q.get("answerable", True):
            ok.append(q)
            continue
        golds = q["gold_notes"]
        if not golds or any(g not in docs for g in golds):
            continue
        ans = normalize(q["answers"][0])
        if not ans:
            continue
        # 정답은 마지막 골드 문서(답 문서)에 반드시 존재
        if ans not in docs[golds[-1]]["norm"]:
            continue
        # masked 문항은 제목 누출 금지
        if q.get("masked"):
            leak = False
            for g in golds[-1:]:
                gn = normalize(display_name(g))
                if gn and gn in normalize(q["q"]):
                    leak = True
            if leak:
                continue
        ok.append(q)
    return ok


def main() -> None:
    docs = load_corpus()
    print(f"corpus: {len(docs)} docs")

    singles = gen_single(docs)
    masked = gen_masked(docs, singles)
    twohop = gen_twohop(docs)
    temporal = gen_temporal(docs)
    abstention = gen_abstention(docs)
    base = verify(singles + masked + twohop + temporal, docs) + abstention

    # variants AFTER verification (같은 골드/정답, 질의만 변형)
    variants = gen_variants([q for q in base if q["type"] == "single"])
    allq = base + variants

    stats = Counter(q["type"] for q in allq)
    print("verified questions:", dict(stats), "total", len(allq))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_DIR / "questions.jsonl", "w", encoding="utf-8") as fh:
        for i, q in enumerate(allq):
            row = {"id": f"kmq-{i:04d}", **{k: v for k, v in q.items()
                                            if k not in ("section",)}}
            row.setdefault("answerable", True)
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print("saved ->", OUT_DIR / "questions.jsonl")

    if "--sample" in sys.argv:
        by_type = defaultdict(list)
        for q in allq:
            by_type[q["type"]].append(q)
        for t, qs in by_type.items():
            print(f"\n== {t} ({len(qs)}) ==")
            for q in qs[:4]:
                print(" Q:", q["q"])
                print("   A:", q["answers"], "gold:", q["gold_notes"])


if __name__ == "__main__":
    main()
