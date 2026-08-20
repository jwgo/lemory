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


def test_console_js_has_no_unclosed_async_fills(client):
    """The dogfood tour crashed on `Cannot set innerHTML of null` when a view
    was left mid-fetch. Guard: async overview fills must go through put(),
    never a bare `$('#x').innerHTML =` that can hit a detached node."""
    import re
    from importlib import resources

    js = resources.files("lemory.interfaces").joinpath("console/app.js").read_text(
        encoding="utf-8")
    # the overview async section is between renderOverview and renderKnowledge
    start = js.index("async function renderOverview")
    end = js.index("async function renderKnowledge")
    section = js[start:end]
    bare = re.findall(r'\$\("#(tiles|acts|memFeed|qlog|clients|hot|recent|sys)"\)\.innerHTML\s*=', section)
    assert not bare, f"overview async fill bypasses put(): {bare}"
    assert "const put = (sel, html)" in js       # the guard helper exists


def test_rename_note_moves_and_reindexes(engine):
    engine.index()
    engine.write_note("옛이름", "# 옛이름\n\n본문 유지.\n", client="console")
    new = engine.rename_note("옛이름.md", "폴더/새이름", client="console")
    assert new == "폴더/새이름.md"
    assert not engine.safe_path("옛이름.md").exists()
    assert "본문 유지" in engine.read_note(new)
    # old path gone from search, new path findable
    paths = {h.path for h in engine.search("본문 유지", k=5)}
    assert new in paths and "옛이름.md" not in paths


def test_rename_refuses_clobber(engine):
    import pytest
    engine.index()
    engine.write_note("a", "x", client="console")
    engine.write_note("b", "y", client="console")
    with pytest.raises(ValueError, match="already exists"):
        engine.rename_note("a.md", "b")


def test_human_delete_allows_any_note(engine):
    # a plain human note has no lemory_generated marker; the AI-undo path
    # refuses it, the human console path trashes it
    import pytest
    engine.index()
    engine.write_note("내 노트", "# 내 노트\n손으로 썼다.\n", client="console")
    with pytest.raises(ValueError, match="refusing"):
        engine.trash_note("내 노트.md")               # AI-undo path: refused
    dest = engine.trash_note("내 노트.md", human=True)  # human path: allowed
    assert dest.startswith(".trash/")
    assert not engine.safe_path("내 노트.md").exists()


def test_http_authoring_endpoints(client, engine):
    # create → rename → titles → delete, all through the console API
    r = client.put("/api/note", json={"path": "초안", "content": "# 초안\n\n[[Dana Petrov]]\n"})
    assert r.status_code == 200

    r = client.post("/api/note/rename", json={"src": "초안.md", "dst": "문서/정식"})
    assert r.status_code == 200 and r.json()["renamed"] == "문서/정식.md"

    titles = client.get("/api/titles").json()["titles"]
    assert any(t["path"] == "문서/정식.md" for t in titles)

    r = client.post("/api/note/delete", json={"path": "문서/정식.md"})
    assert r.status_code == 200 and r.json()["moved_to"].startswith(".trash/")
    assert client.get("/api/raw", params={"path": "문서/정식.md"}).status_code == 404

    # rename onto an existing note → 409
    client.put("/api/note", json={"path": "x", "content": "1"})
    client.put("/api/note", json={"path": "y", "content": "2"})
    assert client.post("/api/note/rename", json={"src": "x.md", "dst": "y"}).status_code == 409


def test_overview_rows_carry_snippet(engine):
    """The note list shows a one-line preview · first real chunk, headings
    and frontmatter markers stripped, whitespace flattened."""
    engine.index()
    engine.write_note("스니펫", "---\ntags: [x]\n---\n# 스니펫\n\n첫 문단이 미리보기가 된다.\n\n다음 문단.\n",
                      client="console")
    rows = {r["path"]: r for r in engine.store.doc_overview_rows()}
    snip = rows["스니펫.md"]["snippet"]
    assert snip.startswith("첫 문단이 미리보기가 된다.")
    assert "#" not in snip and "\n" not in snip
    # every indexed note gets one
    assert all("snippet" in r for r in rows.values())


def test_trash_restore_roundtrip(engine):
    """Delete → bin remembers the home folder → restore puts it back there."""
    engine.index()
    rel = engine.write_note("메모/복구테스트", "# 복구\n\n내용.\n", client="console")
    engine.trash_note(rel, client="console", human=True)
    assert not engine.safe_path(rel).exists()
    bin_ = engine.list_trash()
    entry = next(r for r in bin_ if r["original"] == rel)
    back = engine.restore_note(entry["name"], client="console")
    assert back == rel and engine.safe_path(rel).is_file()
    # restored note is searchable again
    assert any(h.path == rel for h in engine.search("복구 내용", k=5))


def test_restore_never_clobbers(engine):
    engine.index()
    rel = engine.write_note("충돌복구", "v1", client="console")
    engine.trash_note(rel, client="console", human=True)
    engine.write_note("충돌복구", "v2", client="console")   # home is occupied
    entry = engine.list_trash()[0]
    back = engine.restore_note(entry["name"])
    assert back != rel and engine.safe_path(back).read_text(encoding="utf-8") == "v1"
    assert engine.safe_path(rel).read_text(encoding="utf-8") == "v2"


def test_purge_is_guarded_to_trash(engine):
    engine.index()
    rel = engine.write_note("영구삭제", "x", client="console")
    engine.trash_note(rel, client="console", human=True)
    name = engine.list_trash()[0]["name"]
    engine.purge_note(name)
    assert engine.list_trash() == []
    # purge cannot reach outside .trash
    with pytest.raises(ValueError):
        engine.purge_note("../영구삭제.md")
    with pytest.raises(ValueError):
        engine.purge_note("없는파일.md")


def test_http_trash_endpoints(client, engine):
    engine.index()
    client.put("/api/note", json={"path": "일지/휴지통", "content": "# 휴지통\n본문"})
    client.post("/api/note/delete", json={"path": "일지/휴지통.md"})
    rows = client.get("/api/trash").json()
    assert rows and rows[0]["original"] == "일지/휴지통.md"
    r = client.post("/api/trash/restore", json={"name": rows[0]["name"]})
    assert r.json()["restored"] == "일지/휴지통.md"
    client.post("/api/note/delete", json={"path": "일지/휴지통.md"})
    name = client.get("/api/trash").json()[0]["name"]
    assert client.post("/api/trash/purge", json={"name": name}).json()["purged"] == name
    assert client.get("/api/trash").json() == []


def test_korean_filenames_are_born_nfc(engine):
    """macOS composes 한글 filenames as NFD · new writes normalize to NFC so a
    cross-OS vault never grows byte-different twins of the same title."""
    import unicodedata
    engine.index()
    nfd = unicodedata.normalize("NFD", "메모/한글제목")
    rel = engine.write_note(nfd, "# 한글\n본문", client="test")
    assert rel == unicodedata.normalize("NFC", rel)
    # rename destinations too
    nfd2 = unicodedata.normalize("NFD", "메모/바뀐제목")
    moved = engine.rename_note(rel, nfd2, client="test")
    assert moved == unicodedata.normalize("NFC", moved)
    # editing an EXISTING NFD-named file stays reachable (no NFC twin)
    p = engine.cfg.resolved_vault() / unicodedata.normalize("NFD", "메모/엔에프디.md")
    p.parent.mkdir(exist_ok=True)
    p.write_text("v1", encoding="utf-8")
    engine.write_note(unicodedata.normalize("NFD", "메모/엔에프디"), "v2", client="test")
    assert p.read_text(encoding="utf-8") == "v2"
    assert not (engine.cfg.resolved_vault() / "메모" / unicodedata.normalize("NFC", "엔에프디.md")).exists() \
        or unicodedata.normalize("NFC", "엔에프디.md") == unicodedata.normalize("NFD", "엔에프디.md")
