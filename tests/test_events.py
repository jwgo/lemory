"""Middleware timeline: event log, client attribution, AI-note trash."""

import pytest

from lemory.ingestion.memory import save_memory, trash_ai_note


def test_engine_logs_only_when_recording(engine):
    engine.index()
    engine.search("pricing decision", k=3)             # library call: invisible
    assert engine.store.events() == []
    engine.search("pricing decision", k=3, record=True, client="cli")
    engine.ask("what is atlas?", record=True, client="mcp")
    evts = engine.store.events()
    assert [e["kind"] for e in evts] == ["ask", "search"]  # newest first
    assert evts[1]["client"] == "cli" and evts[1]["query"] == "pricing decision"
    assert evts[1]["detail"]["top"]  # top source paths captured


def test_event_log_can_be_disabled(engine):
    engine.index()
    engine.cfg.event_log = False
    engine.search("pricing", k=3, record=True, client="cli")
    assert engine.store.events() == []
    # hit stats still work independently of the timeline
    assert engine.store.hit_stats()
    engine.cfg.event_log = True


def test_memory_writes_logged_and_client_stats(engine):
    engine.index()
    save_memory(engine, "deploy freeze on Fridays", title="Freeze", client="claude-desktop")
    engine.search("freeze", k=2, record=True, client="claude-desktop")
    evts = engine.store.events(kinds=["memory"])
    assert len(evts) == 1 and evts[0]["path"] == "memories/Freeze.md"
    stats = {r["client"]: r for r in engine.store.client_stats()}
    assert stats["claude-desktop"]["writes"] == 1
    assert stats["claude-desktop"]["queries"] == 1


def test_event_log_ring_buffer(engine):
    engine.index()
    engine.store.EVENT_LOG_MAX = 10
    for i in range(25):
        engine.store.log_event("search", client="t", query=f"q{i}")
    evts = engine.store.events(limit=100)
    assert len(evts) == 10 and evts[0]["query"] == "q24"


def test_trash_ai_note_moves_to_obsidian_trash(engine, vault):
    engine.index()
    rel = save_memory(engine, "temp fact", title="Temp", client="mcp")
    assert engine.store.get_doc_by_path(rel) is not None
    moved = trash_ai_note(engine, rel, client="http")
    assert moved.startswith(".trash/") and (vault / moved).exists()
    assert not (vault / rel).exists()
    assert engine.store.get_doc_by_path(rel) is None  # de-indexed
    assert engine.store.events(kinds=["trash"])[0]["path"] == rel


def test_trash_refuses_human_notes(engine, vault):
    engine.index()
    with pytest.raises(ValueError):
        trash_ai_note(engine, "Dana Petrov.md")       # no source: frontmatter
    with pytest.raises(ValueError):
        trash_ai_note(engine, "../outside.md")        # escape attempt
    assert (vault / "Dana Petrov.md").exists()


def test_server_timeline_endpoints(engine):
    from fastapi.testclient import TestClient

    from lemory.interfaces.http import build_app

    app = build_app(engine, watch=False)
    with TestClient(app) as client:
        client.get("/search", params={"q": "pricing"},
                   headers={"X-Lemory-Client": "obsidian-plugin"})
        client.post("/memory", json={"content": "fact", "title": "F"},
                    headers={"X-Lemory-Client": "cursor"})
        evts = client.get("/api/events").json()
        kinds = {e["kind"] for e in evts}
        assert {"search", "memory"} <= kinds
        assert any(e["client"] == "obsidian-plugin" for e in evts)
        rows = client.get("/api/clients").json()
        assert {r["client"] for r in rows} >= {"obsidian-plugin", "cursor"}

        r = client.post("/memory/trash", json={"path": "memories/F.md"})
        assert r.status_code == 200 and r.json()["moved_to"].startswith(".trash/")
        assert client.post("/memory/trash",
                           json={"path": "Dana Petrov.md"}).status_code == 400
        # kind filter works
        only = client.get("/api/events", params={"kinds": "trash"}).json()
        assert [e["kind"] for e in only] == ["trash"]
