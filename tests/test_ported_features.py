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


# ------------------------------------------------- approval workflow (SwarmVault)
def test_approval_mode_keeps_pending_out_of_index(engine):
    from lemory.ingestion.memory import approve_memory, list_pending, save_memory

    engine.index()
    engine.cfg.memory_approval = True
    path = save_memory(engine, "승인 대기 테스트: 판다는 대나무를 먹는다", title="판다 메모")
    # written as a file, but NOT searchable yet
    assert (engine.cfg.vault / path).exists()
    assert all("판다" not in h.title for h in engine.search("판다 대나무", k=5))
    pend = list_pending(engine)
    assert [p["path"] for p in pend] == [str(path)]
    # approve -> indexed
    approve_memory(engine, str(path))
    assert list_pending(engine) == []
    hits = engine.search("판다 대나무", k=5)
    assert hits and hits[0].path == str(path)


def test_approval_off_is_immediate(engine):
    from lemory.ingestion.memory import list_pending, save_memory

    engine.index()
    path = save_memory(engine, "즉시 인덱스: 코알라는 유칼립투스를 먹는다", title="코알라 메모")
    assert list_pending(engine) == []
    hits = engine.search("코알라 유칼립투스", k=5)
    assert hits and hits[0].path == str(path)


def test_approve_refuses_non_pending(engine):
    import pytest

    from lemory.ingestion.memory import approve_memory

    engine.index()
    with pytest.raises(ValueError):
        approve_memory(engine, "Dana Petrov.md")  # human note, no pending marker


def test_pending_note_can_be_rejected_via_trash(engine):
    from lemory.ingestion.memory import list_pending, save_memory, trash_ai_note

    engine.index()
    engine.cfg.memory_approval = True
    path = save_memory(engine, "거절 테스트 메모", title="거절될 메모")
    trash_ai_note(engine, str(path))
    assert list_pending(engine) == []
    assert not (engine.cfg.vault / path).exists()


def test_numbers_ignore_dates():
    # date stamps must not create fake number conflicts between notes
    assert _numbers("결정 (2026-07-15). 예산 80만원") == {"80"}
    assert _numbers("07/15/2026 미팅, 3명 참석") == {"3"}
    assert _numbers("2026년 계획: 서버 2대") == {"2"}
    kind, _ = _classify("합의했다 (2026-07-15). 예산 80만원",
                        "합의했다 (2026-07-14). 예산 80만원")
    assert kind == "duplicate"  # only the dates differ -> not a conflict


# -------------------------------------------------- remote auth (mobile story)
def test_remote_auth_rules():
    from lemory.interfaces.http import remote_auth_error as rae

    # localhost always exempt
    assert rae("127.0.0.1", "", "") is None
    assert rae("::1", "", "secret") is None
    # remote without configured token -> refused outright
    assert rae("192.168.0.7", "", "")[1] == 403
    # remote with wrong/missing bearer -> 401
    assert rae("192.168.0.7", "", "secret")[1] == 401
    assert rae("192.168.0.7", "Bearer nope", "secret")[1] == 401
    # remote with the right token -> allowed
    assert rae("192.168.0.7", "Bearer secret", "secret") is None


def test_allowed_hosts_config_extends_guard(engine):
    from starlette.testclient import TestClient

    from lemory.interfaces.http import build_app

    engine.cfg.allowed_hosts = ["my-desktop.tail-net.ts.net"]
    app = build_app(engine, watch=False)
    with TestClient(app) as c:
        ok = c.get("/status", headers={"host": "my-desktop.tail-net.ts.net:8377"})
        assert ok.status_code == 200
        bad = c.get("/status", headers={"host": "evil.example.com"})
        assert bad.status_code == 421


# ----------------------------------------------------------- backup / restore
def test_backup_restore_roundtrip(engine, tmp_path, monkeypatch):
    import tarfile

    from typer.testing import CliRunner

    import lemory.interfaces.cli as cli

    engine.index()
    engine.store.record_hits([1])
    monkeypatch.setattr(cli, "create_engine", lambda **kw: engine)
    monkeypatch.setattr("lemory.config.load_config", lambda **kw: engine.cfg)
    runner = CliRunner()
    out = tmp_path / "b.tar.gz"
    r = runner.invoke(app := cli.app, ["backup", str(out), "--vault", str(engine.cfg.vault)])
    assert r.exit_code == 0, r.output
    assert out.exists() and "lemory.db" in tarfile.open(out).getnames()
    # wipe the index, restore, verify usage state survived
    db = engine.store.db_path
    engine.store.close()
    db.unlink()
    r = runner.invoke(app, ["restore", str(out), "--vault", str(engine.cfg.vault)])
    assert r.exit_code == 0, r.output
    from lemory.storage import Store
    st = Store(db)
    assert st.hit_stats().get(1, (0, 0))[0] == 1
    st.close()


# ------------------------------------------- semantic fallback links (linkless)
def test_semantic_links_only_for_linkless_notes(engine):
    v = engine.cfg.vault
    # opt-in (default off after the run_linkless.py ablation refuted it)
    engine.cfg.semantic_links = True
    # the fake bag-of-words embedder yields low cosines; the floor is
    # calibrated for real embedders, so lower it for the mechanism test
    engine.cfg.semantic_links_floor = 0.2
    # two unlinked notes about the same topic, plus the existing linked fixture notes
    (v / "국수 레시피.md").write_text(
        "국수 요리: 면을 삶고 육수를 붓는다. 고명으로 파를 올린다.", encoding="utf-8")
    (v / "라면 끓이기.md").write_text(
        "라면 요리: 면을 삶고 스프를 넣는다. 파를 올리면 좋다.", encoding="utf-8")
    engine.index()
    store = engine.store
    docs = {d.title: d.id for d in store.all_docs()}
    nbrs = store.neighbors([docs["국수 레시피"]])[docs["국수 레시피"]]
    assert any(kind == "sem" for _, kind, _ in nbrs), "linkless note should get sem edges"
    # a note with a real wikilink must have NO sem edges (byte-identical guard)
    mercury = docs["Mercury Initiative"]
    kinds = {k for r in store.conn().execute(
        "SELECT kind AS k FROM links WHERE src_doc=?", (mercury,)) for k in [r["k"]]}
    assert "sem" not in kinds


def test_semantic_links_replaced_when_real_link_appears(engine):
    v = engine.cfg.vault
    engine.cfg.semantic_links = True
    engine.cfg.semantic_links_floor = 0.2
    (v / "혼자노트.md").write_text("고양이 사료 비교: 츄르가 최고다.", encoding="utf-8")
    (v / "고양이.md").write_text("고양이는 츄르와 사료를 먹는다.", encoding="utf-8")
    engine.index()
    store = engine.store
    docs = {d.title: d.id for d in store.all_docs()}
    # add a real wikilink; sem edges for that doc must give way on resync
    (v / "혼자노트.md").write_text(
        "고양이 사료 비교: [[고양이]]가 츄르를 좋아한다.", encoding="utf-8")
    engine.index()
    kinds = [r["kind"] for r in store.conn().execute(
        "SELECT kind FROM links WHERE src_doc=?", (docs["혼자노트"],))]
    assert "wiki" in kinds and "sem" not in kinds


def test_semantic_links_off_config(engine):
    engine.cfg.semantic_links = False
    v = engine.cfg.vault
    (v / "고독한노트.md").write_text("완전히 독립적인 주제의 노트다.", encoding="utf-8")
    engine.index()
    n = engine.store.conn().execute(
        "SELECT COUNT(*) AS n FROM links WHERE kind='sem'").fetchone()["n"]
    assert n == 0


# ----------------------------------------------------------------- docx ingest
def test_docx_ingest_stdlib(engine, tmp_path):
    import zipfile

    engine.cfg.index_docx = True
    doc = engine.cfg.vault / "회의자료.docx"
    xml = ('<?xml version="1.0"?><w:document><w:body>'
           '<w:p><w:r><w:t>3분기 OKR: 검색 품질 개선</w:t></w:r></w:p>'
           '<w:p><w:r><w:t>Owner: Jisoo</w:t></w:r></w:p>'
           '</w:body></w:document>').encode("utf-8")
    with zipfile.ZipFile(doc, "w") as z:
        z.writestr("word/document.xml", xml)
    engine.index()
    hits = engine.search("3분기 OKR 검색 품질", k=3, mode="fast")
    assert hits and hits[0].path.endswith("회의자료.docx")


# ------------------------------------------------------------- deep ask
def test_deep_ask_merges_subquery_evidence(engine):
    engine.index()
    normal = engine.ask("What is the Mercury pricing decision?")
    gen_before = engine.llm.calls["generate"]
    deep = engine.ask("What is the Mercury pricing decision?", deep=True)
    # one decomposition call + one answer call
    assert engine.llm.calls["generate"] - gen_before == 2
    ids_normal = {h.chunk_id for h in normal.sources}
    ids_deep = {h.chunk_id for h in deep.sources}
    assert ids_normal <= ids_deep, "deep mode must only ADD evidence, never drop"


# ------------------------------------------------------ framework integrations
def test_langchain_retriever_adapter(engine):
    pytest = __import__("pytest")
    try:
        from lemory.integrations.langchain import LemoryRetriever
    except ImportError:
        pytest.skip("langchain-core not installed")
    engine.index()
    docs = LemoryRetriever(engine=engine, k=3).invoke("Dana Petrov FoundationDB")
    assert docs and docs[0].metadata["title"] == "Dana Petrov"


def test_llamaindex_retriever_adapter(engine):
    pytest = __import__("pytest")
    try:
        from lemory.integrations.llamaindex import LemoryLlamaRetriever
    except ImportError:
        pytest.skip("llama-index-core not installed")
    engine.index()
    nodes = LemoryLlamaRetriever(engine, k=3).retrieve("Dana Petrov FoundationDB")
    assert nodes and nodes[0].node.metadata["title"] == "Dana Petrov"


def test_integrations_module_importable():
    import lemory.integrations  # the package itself never needs the frameworks
    assert lemory.integrations.__doc__


def test_health_view_apis(engine):
    from starlette.testclient import TestClient

    from lemory.interfaces.http import build_app

    (engine.cfg.vault / "깨진.md").write_text("[[없는노트]] 참고", encoding="utf-8")
    app = build_app(engine, watch=False)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        d = c.get("/api/drift").json()
        assert any(r["target"] == "없는노트" for r in d["broken_wikilinks"])
        assert c.get("/api/suggest_links?k=5").status_code == 200
        assert c.get("/api/conflicts?threshold=0.9").status_code == 200
        assert c.get("/api/pending").json() == []


# ------------------------------------------------------- assistant upgrades
def test_remember_intent_patterns():
    from lemory.interfaces.http import _remember_intent as ri

    assert ri("기억해줘: 환불은 비동기 큐로 처리") == "환불은 비동기 큐로 처리"
    assert ri("기억해 줘 회의는 매주 화요일") == "회의는 매주 화요일"
    assert ri("환불은 비동기 큐로 하기로 했다고 기억해줘") == "환불은 비동기 큐로 하기로 했다"
    assert ri("서버 IP는 10.0.0.5 라고 저장해줘") == "서버 IP는 10.0.0.5"
    assert ri("결제 정책이 뭐였지?") is None
    assert ri("기억해줘") is None  # no content


def test_contextual_query_for_followups():
    from lemory.interfaces.http import _contextual_query as cq

    msgs = [{"role": "user", "content": "결제 모듈 환불 정책이 뭐야?"},
            {"role": "assistant", "content": "비동기 큐로 처리합니다"},
            {"role": "user", "content": "그건 언제 정했어?"}]
    out = cq("그건 언제 정했어?", msgs)
    assert "결제 모듈" in out and "그건 언제 정했어?" in out
    # a full question is left alone
    assert cq("결제 모듈 환불 정책은 무엇인가요?", msgs) == "결제 모듈 환불 정책은 무엇인가요?"


def test_assistant_chat_remember_saves_note(engine):
    from starlette.testclient import TestClient

    from lemory.interfaces.http import build_app

    engine.index()
    app = build_app(engine, watch=False)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        r = c.post("/api/assistant/chat", json={
            "messages": [{"role": "user", "content": "기억해줘: 코끼리 프로젝트 마감은 9월 1일"}],
            "session": "t1"})
        assert r.status_code == 200
        assert "기억했습니다" in r.text
    hits = engine.search("코끼리 프로젝트 마감", k=3)
    assert hits and "코끼리" in hits[0].text


def test_assistant_chat_grounded_stream(engine, monkeypatch):
    from starlette.testclient import TestClient

    from lemory.interfaces.http import build_app
    from lemory.providers import gemma

    engine.index()
    seen_system = {}

    def fake_stream(system, history, question, **kw):
        seen_system["s"] = system
        yield "그라운딩 답변 [1]"

    monkeypatch.setattr(gemma, "chat_stream", fake_stream)
    app = build_app(engine, watch=False)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        r = c.post("/api/assistant/chat", json={
            "messages": [{"role": "user", "content": "Dana Petrov가 좋아하는 DB는?"}],
            "session": "t2"})
        assert r.status_code == 200 and "그라운딩 답변" in r.text
    # first turn folds in the vault context block
    assert "VAULT CONTEXT" in seen_system["s"]
    assert "NOTES" in seen_system["s"]


# ------------------------------------- neighbor context (Cerebras-inspired)
def test_adjacent_chunks_and_context_expansion(engine):
    v = engine.cfg.vault
    (v / "긴노트.md").write_text(
        "## 전제\n" + "이 작업은 반드시 백업 후에 진행해야 한다. " * 12 +
        "\n\n## 절차\n" + "복구 명령은 restore --full 이다. " * 12 +
        "\n\n## 주의\n" + "완료 후 반드시 검증 스크립트를 돌린다. " * 12,
        encoding="utf-8")
    engine.index()
    hits = engine.search("restore 복구 명령", k=1)
    assert hits and "restore" in hits[0].text
    prev_t, next_t = engine.store.adjacent_chunks(hits[0].chunk_id)
    assert prev_t and "백업" in prev_t
    from lemory.retrieval.answer import build_context
    plain = build_context(hits)
    expanded = build_context(hits, store=engine.store, neighbor_chars=240)
    assert "백업" not in plain and "백업" in expanded, \
        "neighbor expansion must restore the precondition the boundary cut away"
    assert len(expanded) > len(plain)


def test_ask_neighbor_expansion_opt_in(engine):
    engine.index()
    # default off: ask context building unchanged (published e2e numbers exact)
    assert engine.cfg.context_neighbors is False
    ans = engine.ask("What is Dana's favorite database?")
    assert ans.sources


# ------------------------------------------------- temporal-preserving rerank
def test_rerank_recency_blend_restores_time_axis(engine, monkeypatch):
    """A cross-encoder favors the MORE VERBATIM old statement; under recency
    intent the blend must put the newer correction back on top, and must not
    touch the reranker's order on timeless queries."""
    v = engine.cfg.resolved_vault()
    (v / "결정 3월.md").write_text(
        "---\ndate: 2026-03-01\n---\n캐시는 Redis로 가기로 결정했다. Redis 확정.\n",
        encoding="utf-8")
    (v / "결정 7월.md").write_text(
        "---\ndate: 2026-07-10\n---\n캐시 결정을 뒤집는다 — Memcached로 최종 변경.\n",
        encoding="utf-8")
    engine.index()

    from lemory.retrieval import search as S

    def fake_scores(eng, query, docs):
        # verbatim old note always "more relevant" to the cross-encoder;
        # off-topic notes score low, like a real cross-encoder would
        def s(d):
            if "Redis 확정" in d:
                return 0.85
            return 0.6 if "캐시" in d else 0.05
        return [s(d) for d in docs]

    monkeypatch.setattr(S, "_reranker_scores", fake_scores)
    engine.cfg.rerank = False  # use the dedicated path explicitly
    engine.cfg.reranker = True

    hits = S.hybrid_search(engine, "요즘 캐시 뭐 쓰기로 했지?", k=4).hits
    assert hits and hits[0].title == "결정 7월"  # recency blend wins

    hits2 = S.hybrid_search(engine, "캐시 Redis 결정 내용", k=4).hits
    assert hits2 and hits2[0].title == "결정 3월"  # timeless query untouched
    # a DECISIVE relevance gap survives even under recency intent — the blend
    # flips near-ties only, mirroring the fusion stage's damped multiplier
    def decisive(eng, query, docs):
        return [0.95 if "Redis 확정" in d else (0.3 if "캐시" in d else 0.05)
                for d in docs]
    monkeypatch.setattr(S, "_reranker_scores", decisive)
    hits3 = S.hybrid_search(engine, "요즘 캐시 뭐 쓰기로 했지?", k=4).hits
    assert hits3 and hits3[0].title == "결정 3월"
