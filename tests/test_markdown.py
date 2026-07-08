from lemory.markdown import chunk_note, embed_text_for_chunk, parse_note, render_plain, split_sections


def test_frontmatter_tags_wikilinks():
    raw = (
        "---\ntags: [a, b]\naliases: [Foo]\n---\n"
        "Text with [[Target Note|an alias]] and [[Other#Section]] plus #inline-tag.\n"
    )
    note = parse_note(raw, "My Note")
    assert note.frontmatter["aliases"] == ["Foo"]
    assert set(note.tags) >= {"a", "b", "inline-tag"}
    assert note.wikilinks == ["Target Note", "Other"]
    assert "---" not in note.body


def test_bad_frontmatter_does_not_crash():
    note = parse_note("---\n: bad: [yaml\n---\nbody", "X")
    assert note.body == "body"
    assert note.frontmatter == {}


def test_render_plain_strips_syntax():
    plain = render_plain("# H\nSome **bold** and [[Link|text]] and [md](http://x)")
    assert "**" not in plain and "[[" not in plain
    assert "text" in plain and "md" in plain


def test_split_sections_breadcrumbs():
    body = "intro\n# A\naaa\n## B\nbbb\n# C\nccc"
    secs = split_sections(body)
    assert [s.heading for s in secs] == ["", "A", "A > B", "C"]


def test_chunk_note_respects_size():
    body = "# S\n" + "\n\n".join(f"Paragraph {i} " + "x" * 120 for i in range(20))
    chunks = chunk_note("T", body, chunk_chars=400, overlap=50)
    assert len(chunks) > 3
    assert all(len(t) <= 700 for _, t in chunks)
    assert all(h == "S" for h, _ in chunks)


def test_chunk_note_terminates_with_pathological_overlap():
    body = "word " * 2000  # one giant paragraph
    chunks = chunk_note("T", body, chunk_chars=200, overlap=500)
    assert len(chunks) > 3
    assert all(t.strip() for _, t in chunks)


def test_embed_text_has_breadcrumb():
    assert embed_text_for_chunk("Note", "A > B", "body").startswith("Note > A > B")
