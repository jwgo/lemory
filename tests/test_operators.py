"""khoj-style scoping operators: tag:/folder:/path: prefilters."""

from lemory.retrieval.search import parse_operators


def test_parse_operators_basic():
    clean, tags, folders = parse_operators("tag:프로젝트 folder:회의록 예산 결정")
    assert clean == "예산 결정"
    assert tags == ["프로젝트"] and folders == ["회의록"]


def test_parse_operators_quoted_and_path_synonym():
    clean, tags, folders = parse_operators('tag:"프로젝트 A" path:daily 뭐했지')
    assert clean == "뭐했지"
    assert tags == ["프로젝트 A"] and folders == ["daily"]


def test_parse_operators_hash_stripped_and_plain_query():
    clean, tags, _ = parse_operators("tag:#log 이번주")
    assert tags == ["log"] and clean == "이번주"
    clean, tags, folders = parse_operators("그냥 일반 질문")
    assert clean == "그냥 일반 질문" and not tags and not folders


def test_docs_matching_tag_and_folder(engine):
    engine.index()
    s = engine.store
    all_ids = {d.id: d for d in s.all_docs()}
    proj = s.docs_matching(tags=["project"])
    assert {all_ids[i].title for i in proj} == {"Mercury Initiative"}
    # AND semantics across tags
    assert s.docs_matching(tags=["project", "priority"]) == proj
    assert s.docs_matching(tags=["project", "nope"]) == set()
    sub = s.docs_matching(folders=["Projects"])
    assert {all_ids[i].title for i in sub} == {"Atlas Notes"}
    assert s.docs_matching(folders=["projects"]) == sub  # case-insensitive


def test_search_scoped_by_tag(engine):
    engine.index()
    hits = engine.search("tag:project pricing", k=5)
    assert hits and all(h.title == "Mercury Initiative" for h in hits)
    # same content, wrong scope → nothing leaks in
    assert engine.search("tag:log pricing FoundationDB dashboards", k=5)
    assert all(h.title == "Weekly Log"
               for h in engine.search("tag:log pricing", k=5))


def test_search_scoped_by_folder(engine):
    engine.index()
    hits = engine.search("folder:Projects dashboard", k=5)
    assert hits and all(h.path.startswith("Projects/") for h in hits)


def test_bare_filter_lists_scope(engine):
    engine.index()
    hits = engine.search("tag:project", k=5)
    assert hits and hits[0].title == "Mercury Initiative"


def test_unmatched_filter_returns_empty(engine):
    engine.index()
    assert engine.search("tag:없는태그 pricing", k=5) == []


def test_default_scope_applies_to_unscoped_queries(engine):
    engine.index()
    engine.cfg.default_scope = "tag:project"
    try:
        hits = engine.search("pricing", k=5)
        assert hits and all(h.title == "Mercury Initiative" for h in hits)
    finally:
        engine.cfg.default_scope = ""


def test_default_scope_query_operators_win(engine):
    engine.index()
    engine.cfg.default_scope = "tag:project"
    try:
        hits = engine.search("tag:log pricing", k=5)
        assert hits and all(h.title == "Weekly Log" for h in hits)
    finally:
        engine.cfg.default_scope = ""


def test_default_scope_scope_all_bypasses_once(engine):
    engine.index()
    engine.cfg.default_scope = "tag:project"
    try:
        titles = {h.title for h in engine.search("scope:all pricing", k=8)}
        assert "Weekly Log" in titles  # outside the default scope
        titles_ko = {h.title for h in engine.search("전체: pricing", k=8)}
        assert "Weekly Log" in titles_ko
    finally:
        engine.cfg.default_scope = ""


def test_empty_default_scope_is_noop(engine):
    engine.index()
    assert engine.cfg.default_scope == ""
    assert {h.title for h in engine.search("pricing", k=8)} >= {"Mercury Initiative", "Weekly Log"}
