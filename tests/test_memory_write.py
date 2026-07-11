"""Write path (save_memory / append_to_note) and the context block."""

import pytest

from lemory.ingestion.memory import append_to_note, context_block, save_memory


def test_save_memory_creates_indexed_note(engine, vault):
    engine.index()
    rel = save_memory(engine, "사용자는 매주 목요일에 팀 회고를 진행한다.",
                      title="회고 요일", tags=["habit", "#team"])
    assert rel == "memories/회고 요일.md"
    text = (vault / rel).read_text(encoding="utf-8")
    assert "source: assistant" in text and "tags: [habit, team]" in text
    # searchable immediately, without a manual index call
    hits = engine.search("팀 회고 무슨 요일", k=3)
    assert any(h.path == rel for h in hits)


def test_save_memory_never_overwrites(engine, vault):
    engine.index()
    a = save_memory(engine, "first fact", title="Fact")
    b = save_memory(engine, "second fact", title="Fact")
    assert a == "memories/Fact.md" and b == "memories/Fact 2.md"
    assert "first fact" in (vault / a).read_text(encoding="utf-8")
    assert "second fact" in (vault / b).read_text(encoding="utf-8")


def test_save_memory_rejects_escape_and_empty(engine):
    engine.index()
    with pytest.raises(ValueError):
        save_memory(engine, "x", folder="../outside")
    with pytest.raises(ValueError):
        save_memory(engine, "   ")


def test_append_creates_and_appends(engine, vault):
    engine.index()
    rel = append_to_note(engine, "logs/decisions", "Picked SQLite over Postgres.")
    assert rel == "logs/decisions.md"
    first = (vault / rel).read_text(encoding="utf-8")
    assert "lemory_generated: true" in first and "# decisions" in first and "Picked SQLite" in first

    append_to_note(engine, "logs/decisions.md", "Second entry.")
    text = (vault / rel).read_text(encoding="utf-8")
    assert "Picked SQLite" in text and "Second entry." in text
    assert text.index("Picked SQLite") < text.index("Second entry.")

    with pytest.raises(ValueError):
        append_to_note(engine, "../etc/passwd", "nope")


def test_context_block_sections(engine):
    engine.index()
    engine.store.record_hits([1, 1, 2])  # simulate real usage
    ctx = context_block(engine)
    assert ctx.startswith("# Vault context")
    assert "notes" in ctx and "Recent notes" in ctx
    assert "Frequently referenced" in ctx
    assert "Hub notes" in ctx        # Mercury ↔ Dana wikilink exists
    assert "#project" in ctx         # top tags
    assert len(context_block(engine, max_chars=200)) <= 200


def test_server_memory_endpoints(client):
        r = client.get("/context")
        assert r.status_code == 200 and r.json()["context"].startswith("# Vault context")

        r = client.post("/memory", json={"content": "deploy freeze on Fridays",
                                         "title": "Deploy freeze", "tags": ["ops"]})
        assert r.status_code == 200
        assert r.json()["saved"] == "memories/Deploy freeze.md"
        hits = client.get("/search", params={"q": "deploy freeze", "k": 3}).json()
        assert any(h["path"] == "memories/Deploy freeze.md" for h in hits)

        r = client.post("/append", json={"path": "logs/oncall", "content": "paged at 3am"})
        assert r.status_code == 200 and r.json()["appended"] == "logs/oncall.md"

        assert client.post("/memory", json={"content": "x", "folder": "../up"}).status_code == 400
        assert client.post("/append", json={"path": "../up.md", "content": "x"}).status_code == 400


def test_save_memory_links_related_and_flags_duplicate(engine, vault):
    # unit test exercises the mechanism, not the default thresholds (those
    # are tuned for real embedders; the fake embedder's cosine scale differs)
    engine.cfg.memory_dedup_sim = engine.cfg.memory_related_sim
    engine.index()
    a = save_memory(engine, "결제 서비스 장애 시 우선 연락처는 김지수 (010-1234)", title="장애 연락처")
    # near-identical fact saved again -> related + duplicate flag
    b = save_memory(engine, "결제 서비스 장애가 나면 우선 연락처는 김지수 (010-1234)이다", title="장애 연락처 v2")
    assert getattr(b, "related", None), "second save must see the first memory"
    top = b.related[0]
    assert top["title"] == "장애 연락처"
    assert top["near_duplicate"] is True
    # the new note's frontmatter carries the links
    text = (vault / b).read_text()
    assert "related:" in text and "[[장애 연락처]]" in text
    assert "possible_duplicate_of:" in text


def test_save_memory_unrelated_content_gets_no_duplicate_flag(engine, vault):
    engine.index()
    save_memory(engine, "결제 서비스 장애 시 우선 연락처는 김지수", title="장애 연락처")
    c = save_memory(engine, "완전히 무관한 주제: 화분에 물은 화요일마다 준다", title="화분 물주기")
    assert all(not r["near_duplicate"] for r in getattr(c, "related", []))
    text = (vault / c).read_text()
    assert "possible_duplicate_of:" not in text


def test_save_memory_relate_disabled(engine, vault):
    engine.cfg.memory_relate = False
    engine.index()
    save_memory(engine, "fact one about deploys", title="Fact1")
    d = save_memory(engine, "fact one about deploys again", title="Fact2")
    assert getattr(d, "related", []) == []
    assert "related:" not in (vault / d).read_text()
