"""Tests for the challenger ports: fast lexical mode (EchoVault-class instant
search) and the conflict scan (Vestige's contradiction detection, done local)."""

from __future__ import annotations

from lemory.retrieval.conflicts import _classify, _numbers, find_conflicts


# --------------------------------------------------------------- fast mode
def test_fast_mode_never_embeds(engine):
    engine.index()
    embeds_after_index = engine.llm.calls["embed"]
    hits = engine.search("Dana Petrov FoundationDB", k=4, mode="fast")
    assert hits, "fast mode must find lexical matches"
    assert engine.llm.calls["embed"] == embeds_after_index, "fast mode must not embed"


def test_fast_mode_finds_korean_with_particles(engine):
    (engine.cfg.vault / "회의록.md").write_text(
        "프로젝트 회의는 매주 화요일에 열린다. 발표는 김지수 담당.", encoding="utf-8"
    )
    engine.index()
    before = engine.llm.calls["embed"]
    hits = engine.search("김지수가 담당하는 발표", k=3, mode="fast")
    assert hits and hits[0].path == "회의록.md"
    assert engine.llm.calls["embed"] == before


def test_fast_mode_keeps_title_boost_and_cap(engine):
    engine.index()
    hits = engine.search("Dana Petrov", k=8, mode="fast")
    assert hits and hits[0].title == "Dana Petrov"
    per_doc: dict[int, int] = {}
    for h in hits:
        per_doc[h.doc_id] = per_doc.get(h.doc_id, 0) + 1
    assert max(per_doc.values()) <= engine.cfg.per_doc_cap


def test_fast_mode_usage_prior_breaks_ties(engine):
    v = engine.cfg.vault
    (v / "노트A.md").write_text("파스타 요리법: 면을 삶는다.", encoding="utf-8")
    (v / "노트B.md").write_text("파스타 요리법: 면을 삶는다!", encoding="utf-8")
    engine.index()
    engine.cfg.usage_prior = 0.1
    base = engine.search("파스타 요리법", k=2, mode="fast")
    assert len(base) == 2
    loser = base[1]
    engine.store.record_hits([loser.doc_id])
    engine.store.record_hits([loser.doc_id])
    boosted = engine.search("파스타 요리법", k=2, mode="fast")
    assert boosted[0].doc_id == loser.doc_id, "used note should win the tie"


# ------------------------------------------------------------ conflict scan
def test_numbers_extraction():
    assert _numbers("가격은 $0.04, 수량 1,000개") == {"0.04", "1000"}
    assert _numbers("no digits") == set()


def test_classify_number_conflict():
    kind, detail = _classify("회의는 3시에 시작한다", "회의는 5시에 시작한다")
    assert kind == "number"
    assert "3" in detail and "5" in detail


def test_classify_negation_conflict():
    kind, _ = _classify("이 기능은 지원된다", "이 기능은 지원되지 않는다")
    assert kind == "negation"


def test_classify_duplicate():
    kind, _ = _classify("고양이는 귀엽다", "고양이는 귀엽다 정말")
    assert kind == "duplicate"


def test_find_conflicts_number_disagreement(engine):
    v = engine.cfg.vault
    (v / "요금정책.md").write_text(
        "컴퓨트 요금은 분당 0.04달러로 확정되었다. 파일럿 이후 결정.", encoding="utf-8"
    )
    (v / "요금메모.md").write_text(
        "컴퓨트 요금은 분당 0.05달러로 확정되었다. 파일럿 이후 결정.", encoding="utf-8"
    )
    engine.index()
    found = find_conflicts(engine, threshold=0.7)
    pairs = {(c.a.title, c.b.title, c.kind) for c in found}
    assert any(
        {a, b} == {"요금정책", "요금메모"} and k == "number" for a, b, k in pairs
    ), f"expected the 0.04/0.05 disagreement, got {pairs}"


def test_find_conflicts_ignores_same_doc(engine):
    v = engine.cfg.vault
    (v / "단일노트.md").write_text(
        "가격은 10달러이다.\n\n가격은 20달러이다.", encoding="utf-8"
    )
    engine.index()
    for c in find_conflicts(engine, threshold=0.7):
        assert c.a.doc_id != c.b.doc_id


def test_find_conflicts_clean_vault(engine):
    engine.index()
    # the fixture vault has no near-duplicate cross-note pairs at high cosine
    assert find_conflicts(engine, threshold=0.97) == []
