"""Agent working memory: typed fragments, anchors, scoped recall, work threads."""

import pytest

from lemory.ingestion.fragments import (
    FRAGMENT_TYPES,
    anchored,
    normalize_case,
    reflect,
    remember,
    set_anchor,
)
from lemory.retrieval.recall import open_cases, recall, resume_case


def _fm(engine, rel):
    """Frontmatter the indexer parsed back out of a written fragment."""
    doc = next(d for d in engine.store.all_docs() if d.path == rel)
    return engine.store.docs_meta([doc.id])[doc.id]


def test_remember_writes_typed_frontmatter(engine):
    engine.index()
    rel = remember(
        engine, "배포 포트는 15000이다", type="fact", topic="deploy",
        case="mcp 붙이기", phase="setup", title="배포 포트",
    )
    fm = _fm(engine, rel)
    assert fm["type"] == "fact"
    assert fm["topic"] == "deploy"
    assert fm["case"] == "mcp 붙이기"
    assert fm["phase"] == "setup"
    assert fm["lemory_generated"] is True
    # a fact carries no status; only errors get the open default
    assert not fm.get("status")


def test_error_defaults_to_open(engine):
    engine.index()
    rel = remember(engine, "포트 8080 충돌로 서버가 죽는다", type="error", case="배포")
    assert _fm(engine, rel)["status"] == "open"
    rel2 = remember(engine, "포트 바꿔서 해결", type="error", case="배포",
                    status="resolved")
    assert _fm(engine, rel2)["status"] == "resolved"


def test_meta_cannot_forge_reserved_keys(engine):
    """A spoofed marker would subvert the trash guard and the approval gate."""
    from lemory.ingestion.memory import save_memory

    rel = save_memory(engine, "내용", title="스푸핑",
                      meta={"lemory_generated": False, "lemory_pending": True,
                            "type": "fact"})
    fm = _fm(engine, rel)
    assert fm["lemory_generated"] is True   # writer's value, not the caller's
    assert "lemory_pending" not in fm
    assert fm["type"] == "fact"             # non-reserved key still lands


def test_recall_scoped_by_type_and_case(engine):
    engine.index()
    remember(engine, "가격은 컴퓨트분당 0.04달러로 결정", type="decision", case="가격")
    remember(engine, "가격 계산 스크립트가 0으로 나눠서 터진다", type="error", case="가격")
    remember(engine, "가격 관련 사용자 선호는 연간 결제", type="preference", case="가격")

    errs = recall(engine, "가격", type="error")
    assert errs and all(r["type"] == "error" for r in errs)
    assert all(r["case"] == "가격" for r in errs)

    # the same query unscoped is free to return the other types
    everything = recall(engine, "가격", case="가격", k=10)
    assert {r["type"] for r in everything} >= {"decision", "error", "preference"}


def test_recall_without_query_lists_the_scope(engine):
    engine.index()
    remember(engine, "첫 기록", type="fact", case="빈쿼리")
    remember(engine, "둘째 기록", type="fact", case="빈쿼리")
    rows = recall(engine, case="빈쿼리")
    assert len(rows) == 2


def test_recall_returns_one_row_per_fragment(engine):
    """A fragment is a note. Document search wants several chunks of a long
    note; recall handing the agent the same fragment twice just burns k."""
    engine.index()
    long_body = "배포 절차는 다음과 같다. " + ("포트를 확인하고 헬스체크를 돈다. " * 60)
    remember(engine, long_body, type="procedure", case="긴글", title="배포 절차")
    rows = recall(engine, "배포 포트 헬스체크", case="긴글", k=8)
    paths = [r["path"] for r in rows]
    assert len(paths) == len(set(paths)) == 1


def test_recall_shows_prose_not_flattened_frontmatter(engine):
    """Fragments are short, so the chunk that ranks is often the enrichment
    pseudo-chunk (flattened frontmatter). It earns its keep in ranking, but an
    excerpt reading "date: … source: assistant …" is useless to a human."""
    engine.index()
    remember(engine, "지훈의 여동생 이름은 김보람이다", type="fact", case="가족",
             title="여동생 이름")
    row = recall(engine, case="가족")[0]
    assert "김보람" in row["text"]
    assert "source: assistant" not in row["text"]
    assert "lemory_generated" not in row["text"]


def test_recall_empty_scope_returns_nothing(engine):
    engine.index()
    remember(engine, "무언가", type="fact", case="있음")
    assert recall(engine, "무언가", case="없는케이스") == []


def test_anchor_roundtrip(engine):
    engine.index()
    rel = remember(engine, "사용자는 항상 한국어로 답변받길 원한다", type="preference",
                   title="언어 선호")
    assert anchored(engine) == []

    set_anchor(engine, rel, True)
    pins = anchored(engine)
    assert [p["path"] for p in pins] == [rel]
    assert pins[0]["type"] == "preference"

    set_anchor(engine, rel, False)
    assert anchored(engine) == []


def test_anchor_preserves_body_and_existing_frontmatter(engine):
    engine.index()
    rel = remember(engine, "본문은 그대로 남아야 한다", type="fact", topic="보존")
    path = engine.cfg.resolved_vault() / rel
    before = path.read_text(encoding="utf-8").split("---", 2)[2]

    set_anchor(engine, rel, True)
    after = path.read_text(encoding="utf-8")
    assert after.split("---", 2)[2] == before      # body byte-for-byte
    assert _fm(engine, rel)["topic"] == "보존"      # other keys survive
    assert _fm(engine, rel)["anchor"] is True


def test_anchor_note_without_frontmatter(engine):
    engine.index()
    rel = "Dana Petrov.md"  # a plain human note from the fixture vault
    set_anchor(engine, rel, True)
    assert _fm(engine, rel)["anchor"] is True
    assert "head of platform engineering" in (
        engine.cfg.resolved_vault() / rel).read_text(encoding="utf-8")


def test_anchor_rejects_path_escape(engine):
    engine.index()
    with pytest.raises(ValueError):
        set_anchor(engine, "../outside.md", True)


def test_reflect_writes_an_episode_with_sections(engine):
    engine.index()
    rel = reflect(
        engine,
        summary="MCP 서버를 붙이고 recall 왕복까지 확인했다",
        decisions=["프래그먼트는 볼트 마크다운으로 저장한다"],
        errors_resolved=["포트 충돌"],
        next_steps=["CLI verb 추가", "문서 갱신"],
        case="mcp 붙이기",
        notes_touched=["memories/배포 포트.md"],
    )
    fm = _fm(engine, rel)
    assert fm["type"] == "episode" and fm["case"] == "mcp 붙이기"
    body = (engine.cfg.resolved_vault() / rel).read_text(encoding="utf-8")
    assert "## 다음 단계" in body and "CLI verb 추가" in body
    assert "[[배포 포트]]" in body  # touched notes become graph edges


def test_reflect_rejects_empty_summary(engine):
    engine.index()
    with pytest.raises(ValueError):
        reflect(engine, "   ")


def test_resume_case_reconstructs_the_thread(engine):
    engine.index()
    remember(engine, "포트 8080이 이미 점유되어 있다", type="error", case="배포",
             phase="setup")
    remember(engine, "포트를 15000으로 옮기기로 했다", type="decision", case="배포",
             phase="setup")
    reflect(engine, summary="배포 포트 정리", decisions=["15000 고정"],
            next_steps=["헬스체크 추가"], case="배포", phase="verify")

    out = resume_case(engine, "배포")
    assert out["found"] == 3
    assert out["next_steps"] == ["헬스체크 추가"]
    assert "15000 고정" in out["decisions"]
    assert [o["type"] for o in out["open"]] == ["error"]  # unresolved failure
    assert "setup" in out["phases"] and "verify" in out["phases"]
    assert "## 다음 단계 (직전 세션 기준)" in out["brief"]


def test_resume_case_latest_next_steps_supersede_earlier(engine):
    engine.index()
    reflect(engine, summary="1회차", next_steps=["옛날 계획"], case="순서")
    reflect(engine, summary="2회차", next_steps=["최신 계획"], case="순서")
    assert resume_case(engine, "순서")["next_steps"] == ["최신 계획"]


def test_resume_case_unknown_is_empty_not_an_error(engine):
    engine.index()
    out = resume_case(engine, "존재하지 않는 케이스")
    assert out["found"] == 0 and out["fragments"] == []


def test_resume_case_rejects_empty_id(engine):
    engine.index()
    with pytest.raises(ValueError):
        resume_case(engine, "   ")


def test_open_cases_ranks_unfinished_work(engine):
    engine.index()
    remember(engine, "아직 못 고친 버그", type="error", case="열린건", phase="fix")
    remember(engine, "이미 고침", type="error", case="닫힌건", status="resolved")
    rows = {r["case"]: r for r in open_cases(engine)}
    assert rows["열린건"]["open"] == 1
    assert rows["닫힌건"]["open"] == 0
    assert rows["열린건"]["phase"] == "fix"


def test_open_cases_keeps_the_last_known_phase(engine):
    """Fragments written mid-case routinely omit `phase`; the case's progress
    marker must not be blanked just because the newest write skipped it."""
    engine.index()
    remember(engine, "단계를 적은 기록", type="fact", case="단계", phase="setup")
    remember(engine, "단계를 안 적은 기록", type="fact", case="단계")
    rows = {r["case"]: r for r in open_cases(engine)}
    assert rows["단계"]["phase"] == "setup"
    assert "phase_at" not in rows["단계"]  # internal bookkeeping stays internal


def test_context_block_leads_with_anchors_and_open_cases(engine):
    from lemory.ingestion.memory import context_block

    engine.index()
    rel = remember(engine, "항상 한국어", type="preference", title="언어")
    set_anchor(engine, rel, True)
    remember(engine, "미해결 건", type="error", case="진행중")

    block = context_block(engine, max_chars=4000)
    assert "## Anchors (pinned core memory)" in block
    assert "## Open cases" in block
    assert block.index("## Anchors") < block.index("## Recent notes")
    assert "진행중" in block


def test_server_agent_memory_endpoints(client):
    r = client.post("/memory/fragment",
                    json={"content": "포트 8080 충돌", "type": "error",
                          "case": "배포", "phase": "setup"})
    assert r.status_code == 200 and r.json()["type"] == "error"

    r = client.post("/memory/fragment",
                    json={"content": "15000으로 옮긴다", "type": "decision",
                          "case": "배포"})
    assert r.status_code == 200
    rel = r.json()["saved"]

    rows = client.get("/api/recall", params={"q": "포트", "type": "error"}).json()
    assert rows["results"] and rows["results"][0]["status"] == "open"

    cases = client.get("/api/cases").json()["cases"]
    assert any(c["case"] == "배포" and c["open"] == 1 for c in cases)

    thread = client.get("/api/case", params={"case": "배포"}).json()
    assert thread["found"] == 2 and thread["brief"].startswith("# 케이스 재개")
    assert client.get("/api/case", params={"case": "  "}).status_code == 400

    assert client.post("/memory/anchor", json={"path": rel}).json()["anchor"] is True
    assert [a["path"] for a in client.get("/api/anchors").json()["anchors"]] == [rel]
    assert client.get("/context").json()["context"].count("## Anchors") == 1

    # the vault guard still holds on the new write paths
    assert client.post("/memory/anchor",
                       json={"path": "../up.md"}).status_code == 400
    assert client.post("/memory/fragment",
                       json={"content": "  "}).status_code == 400


def test_normalize_case_is_stable_and_safe():
    assert normalize_case("  mcp   붙이기 ") == "mcp 붙이기"
    assert normalize_case("a/b:c") == "a b c"
    assert normalize_case("") == ""


def test_fragment_taxonomy_matches_the_documented_eight():
    # AnchorMind's seven for interop + belief (Hindsight's opinions network)
    assert set(FRAGMENT_TYPES) == {
        "fact", "decision", "error", "preference", "procedure", "relation",
        "episode", "belief",
    }


# ---------------------------------------------------- belief (Hindsight 흡수)
def test_belief_carries_confidence(engine):
    engine.index()
    rel = engine.remember("SQLite가 이 규모에는 최선이다", type="belief",
                          title="저장소 선택", confidence=0.8)
    text = engine.read_note(str(rel))
    assert 'type: "belief"' in text and "confidence: 0.8" in text


def test_belief_revision_updates_in_place(engine):
    """Same title → the note is REVISED: new statement on top, confidence
    updated, superseded statement preserved in the 변천 trail."""
    engine.index()
    rel = engine.remember("벡터 DB가 필요할 것이다", type="belief",
                          title="벡터DB 필요성", confidence=0.7)
    rel2 = engine.remember("numpy 행렬로 충분하다 · 벡터 DB는 과함",
                           type="belief", title="벡터DB 필요성", confidence=0.9)
    assert str(rel2) == str(rel)                      # one note, not two
    text = engine.read_note(str(rel))
    assert "confidence: 0.90" in text
    assert text.count("## 변천") == 1
    assert "0.70→0.90" in text and "벡터 DB가 필요할 것이다" in text
    assert text.index("numpy 행렬로 충분하다") < text.index("## 변천")
    # a second revision accumulates, never overwrites
    engine.remember("확정: numpy 유지", type="belief",
                    title="벡터DB 필요성", confidence=0.95)
    text = engine.read_note(str(rel))
    assert "0.90→0.95" in text and "0.70→0.90" in text


def test_belief_default_confidence_and_recall_row(engine):
    engine.index()
    engine.remember("담당자는 리뷰를 아침에 본다", type="belief", title="리뷰 습관")
    rows = engine.recall(type="belief")
    assert rows and rows[0]["type"] == "belief"
    assert rows[0]["confidence"] == 0.6               # belief default
    # evidence types carry no confidence — that absence is the separation
    engine.remember("포트는 15000", type="fact")
    fact_rows = engine.recall(type="fact")
    assert fact_rows and fact_rows[0]["confidence"] is None


# ----------------------------------------- after:/before: (시간 범위 연산자)
def test_parse_operators_date_range():
    from lemory.retrieval.search import parse_operators, _pop_date_range
    clean, _, _, fields = parse_operators("after:2026-01 before:2026-03 예산")
    assert clean == "예산"
    rng = _pop_date_range(fields)
    assert rng is not None and fields == {}
    lo, hi = rng
    import datetime as dt
    assert dt.datetime.fromtimestamp(lo).month == 1
    assert dt.datetime.fromtimestamp(hi).month == 4   # period-inclusive end


def test_search_scoped_by_date_range(engine, vault):
    (vault / "d1.md").write_text("---\ndate: 2026-01-10\n---\n# 일월 회의\n예산 확정\n",
                                 encoding="utf-8")
    (vault / "d2.md").write_text("---\ndate: 2026-06-20\n---\n# 유월 회의\n예산 재검토\n",
                                 encoding="utf-8")
    engine.index()
    hits = engine.search("after:2026-05 예산", k=5)
    assert hits and all(h.path != "d1.md" for h in hits)
    assert any(h.path == "d2.md" for h in hits)
    hits = engine.search("before:2026-02 예산", k=5)
    assert any(h.path == "d1.md" for h in hits)
    assert all(h.path != "d2.md" for h in hits)
    # bare range = scoped listing
    assert engine.search("after:2026-06", k=5)


# ------------------------------------ Hindsight 소스 정독 2차 흡수분
def test_temporal_leg_surfaces_window_notes(engine, vault):
    """명시적 시간 창 질의는 어휘·의미가 안 겹치는 창 안 노트도 후보로 낸다
    (recency 부스트만으로는 불가능한 케이스)."""
    import datetime as dt
    now = dt.datetime.now()
    last_week = (now - dt.timedelta(days=4)).strftime("%Y-%m-%d")
    (vault / "창안노트.md").write_text(
        f"---\ndate: {last_week}\n---\n# 창안노트\n김치 냉장고 온도를 손봤다.\n",
        encoding="utf-8")
    engine.index()
    hits = engine.search("지난주에 작업한 내용", k=8)
    assert any(h.path == "창안노트.md" for h in hits)


def test_belief_trail_is_capped(engine):
    engine.index()
    engine.remember("v0", type="belief", title="캡테스트", confidence=0.5)
    for i in range(55):
        engine.remember(f"개정 {i}", type="belief", title="캡테스트")
    text = engine.read_note("memories/캡테스트.md")
    trail_lines = [ln for ln in text.splitlines() if ln.startswith("- ")]
    # 50 entries + one elision marker, never unbounded
    assert len(trail_lines) == 51
    assert any("생략" in ln for ln in trail_lines)


def test_degenerate_fragments_are_rejected(engine):
    engine.index()
    for junk in ("...", "---", "  ", "•", "?!"):
        with pytest.raises(ValueError, match="degenerate"):
            engine.remember(junk, type="fact")
    # real content still lands
    assert engine.remember("포트는 15000", type="fact")
