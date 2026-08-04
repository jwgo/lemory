"""Desktop-grade console backend: raw read, editor save, conflict guard."""
from __future__ import annotations

import time

import pytest


def test_read_and_write_note_roundtrip(engine):
    engine.index()
    rel = engine.write_note("메모/새 노트", "# 제목\n\n본문이다. [[Dana Petrov]] 링크.\n",
                            client="console")
    assert rel == "메모/새 노트.md"
    assert "본문이다" in engine.read_note(rel)
    # instantly searchable + wikilink became a graph edge
    assert any(h.path == rel for h in engine.search("새 노트 본문", k=5))


def test_write_note_conflict_guard(engine):
    engine.index()
    rel = engine.write_note("충돌테스트", "v1", client="console")
    mtime = engine.safe_path(rel).stat().st_mtime
    # disk changes under the editor (Obsidian, another tab, a script)
    time.sleep(0.01)
    engine.safe_path(rel).write_text("disk-edit", encoding="utf-8")
    with pytest.raises(ValueError, match="conflict"):
        engine.write_note(rel, "editor-edit", expect_mtime=mtime)
    # fresh token saves fine
    fresh = engine.safe_path(rel).stat().st_mtime
    engine.write_note(rel, "editor-edit", expect_mtime=fresh)
    assert engine.read_note(rel) == "editor-edit"


def test_write_note_rejects_escape(engine):
    engine.index()
    with pytest.raises(ValueError):
        engine.write_note("../밖", "x")


def test_http_editor_endpoints(client, engine):
    r = client.get("/api/raw", params={"path": "Dana Petrov.md"})
    assert r.status_code == 200
    raw = r.json()
    assert "FoundationDB" in raw["content"] and raw["mtime"] > 0

    r = client.put("/api/note", json={"path": "Dana Petrov.md",
                                      "content": raw["content"] + "\n추가 줄.\n",
                                      "expect_mtime": raw["mtime"]})
    assert r.status_code == 200
    # stale token → 409, not a silent overwrite
    r2 = client.put("/api/note", json={"path": "Dana Petrov.md",
                                       "content": "clobber",
                                       "expect_mtime": raw["mtime"]})
    assert r2.status_code == 409
    assert "추가 줄" in engine.read_note("Dana Petrov.md")

    assert client.get("/api/raw", params={"path": "없는노트.md"}).status_code == 404
    assert client.put("/api/note", json={"path": "../탈출", "content": "x"}).status_code == 400


def test_graph_page_serves_html(client):
    r = client.get("/graph")
    assert r.status_code == 200
    assert "<html" in r.text.lower() or "<svg" in r.text.lower() or "<canvas" in r.text.lower()
