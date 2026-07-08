"""Edge cases for the ingest pipeline."""

from lemory.ingestion import iter_vault_files, note_title


def test_exclude_dirs(engine, vault):
    (vault / ".obsidian").mkdir()
    (vault / ".obsidian" / "workspace.md").write_text("should not index")
    (vault / ".trash").mkdir()
    (vault / ".trash" / "old.md").write_text("deleted note")
    rep = engine.index()
    assert rep.added == 4
    paths = {d.path for d in engine.store.all_docs()}
    assert not any(".obsidian" in p or ".trash" in p for p in paths)


def test_empty_and_whitespace_notes(engine, vault):
    (vault / "Empty.md").write_text("")
    (vault / "Blank.md").write_text("   \n\n  ")
    rep = engine.index()
    assert rep.errors == []
    # empty notes still get a doc row (title-only chunk) so wikilinks resolve
    assert engine.store.get_doc_by_path("Empty.md") is not None


def test_unicode_titles_and_content(engine, vault):
    (vault / "김치 프로젝트.md").write_text("발효 온도는 4도씨로 유지한다. [[Dana Petrov]] 참고.")
    rep = engine.index()
    assert rep.errors == []
    doc = engine.store.get_doc_by_path("김치 프로젝트.md")
    assert doc.title == "김치 프로젝트"
    hits = engine.search("발효 온도", k=3, mode="bm25")
    assert any(h.title == "김치 프로젝트" for h in hits)


def test_rename_is_delete_plus_add(engine, vault):
    engine.index()
    (vault / "Weekly Log.md").rename(vault / "Weekly Journal.md")
    rep = engine.index()
    assert rep.added == 1 and rep.removed == 1
    assert engine.store.get_doc_by_path("Weekly Log.md") is None


def test_frontmatter_only_note(engine, vault):
    (vault / "Meta Only.md").write_text("---\ntags: [x]\n---\n")
    rep = engine.index()
    assert rep.errors == []


def test_giant_paragraph_hard_split(engine, vault):
    (vault / "Wall.md").write_text("word " * 3000)  # single 15k-char paragraph
    rep = engine.index()
    assert rep.errors == []
    doc = engine.store.get_doc_by_path("Wall.md")
    ids = engine.store.doc_chunk_ids(doc.id)
    assert len(ids) > 5
    chunks = engine.store.get_chunks(ids)
    assert all(len(c.text) <= engine.cfg.chunk_chars * 1.6 for c in chunks.values())


def test_note_title_and_iter(tmp_path):
    v = tmp_path / "v"
    (v / "sub").mkdir(parents=True)
    (v / "sub" / "Note.md").write_text("x")
    (v / "top.md").write_text("y")
    (v / "skip.txt").write_text("z")
    files = iter_vault_files(v, ["**/*.md"], [])
    assert {f.name for f in files} == {"Note.md", "top.md"}
    assert note_title(v / "sub" / "Note.md") == "Note"


def test_self_mention_not_linked(engine, vault):
    # a note that mentions its own title must not self-link
    engine.index()
    docs = {d.title: d.id for d in engine.store.all_docs()}
    mercury = docs["Mercury Initiative"]
    nbrs = engine.store.neighbors([mercury])[mercury]
    assert all(dst != mercury for dst, _, _ in nbrs)
