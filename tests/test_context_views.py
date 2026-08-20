"""Tiered context loading (L0/L1/L2) + context tree · deterministic, LLM-0."""
from __future__ import annotations

import pytest

NOTE = """---
tags: [설계, 검색]
---
하이브리드 검색의 설계 근거를 정리한다. 벡터 단독은 어휘 신호를 버린다.

## 융합
RRF로 다리를 섞는다. 가중치는 실측으로 정했다.

세부 파라미터는 스윕 결과를 따른다.

## 한국어
바이그램 인덱싱이 조사 문제를 푼다.
```
code block is skipped
```
"""


def test_abstract_is_title_plus_lead(engine):
    from lemory.retrieval.context_views import note_abstract
    l0 = note_abstract("검색 설계", NOTE)
    assert l0.startswith("검색 설계 — 하이브리드 검색의 설계 근거")
    assert "\n" not in l0 and len(l0) < 240
    # frontmatter never leaks into L0
    assert "tags" not in l0


def test_overview_keeps_skeleton_and_openings(engine):
    from lemory.retrieval.context_views import note_overview
    l1 = note_overview(NOTE)
    assert "## 융합" in l1 and "## 한국어" in l1
    assert "RRF로 다리를 섞는다" in l1
    assert "code block is skipped" not in l1
    assert "(tags:" in l1


def test_note_view_levels_and_guard(engine):
    engine.index()
    rel = engine.write_note("설계/검색 설계", NOTE, client="test")
    assert engine.note_view(rel, level="full") == NOTE
    assert engine.note_view(rel, level="abstract").startswith("검색 설계 —")
    assert "## 융합" in engine.note_view(rel, level="overview")
    with pytest.raises(ValueError, match="unknown level"):
        engine.note_view(rel, level="xl")


def test_context_tree_shows_folders_counts_and_l0(engine):
    engine.index()
    engine.write_note("설계/검색 설계", NOTE, client="test")
    tree = engine.context_tree()
    assert "노트" in tree.splitlines()[0]
    assert "설계/" in tree
    assert "검색 설계 — 하이브리드 검색의 설계 근거" in tree
    # scoped + per-folder elision
    scoped = engine.context_tree(folder="설계", per=1)
    assert "검색 설계" in scoped and "설계/" not in scoped.splitlines()[0].replace("설계 ·", "")


def test_http_tree_and_tiered_raw(client, engine):
    engine.index()
    client.put("/api/note", json={"path": "설계/티어", "content": NOTE})
    r = client.get("/api/raw", params={"path": "설계/티어.md", "level": "abstract"})
    assert r.status_code == 200 and r.json()["content"].startswith("티어 —")
    assert client.get("/api/raw", params={"path": "설계/티어.md", "level": "bogus"}).status_code == 400
    t = client.get("/api/tree").json()["tree"]
    assert "티어" in t
