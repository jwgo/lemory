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
