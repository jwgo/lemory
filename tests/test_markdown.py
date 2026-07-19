from lemory.ingestion.markdown import chunk_note, embed_text_for_chunk, parse_note, render_plain, split_sections


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


def test_bad_frontmatter_does_not_crash_or_drop_content():
    note = parse_note("---\n: bad: [yaml\n---\nbody", "X")
    assert "body" in note.body  # content must never be silently dropped
    assert note.frontmatter == {}


def test_leading_horizontal_rule_is_not_frontmatter():
    raw = "---\nIntro facts worth indexing\n---\nRest of the note"
    note = parse_note(raw, "X")
    assert note.frontmatter == {}
    assert "Intro facts worth indexing" in note.body


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
    chunks = chunk_note(body, chunk_chars=400, overlap=50)
    assert len(chunks) > 3
    assert all(len(t) <= 700 for _, t in chunks)
    assert all(h == "S" for h, _ in chunks)


def test_chunk_note_terminates_with_pathological_overlap():
    body = "word " * 2000  # one giant paragraph
    chunks = chunk_note(body, chunk_chars=200, overlap=500)
    assert len(chunks) > 3
    assert all(t.strip() for _, t in chunks)


def test_embed_text_has_breadcrumb():
    assert embed_text_for_chunk("Note", "A > B", "body").startswith("Note > A > B")


# --------------------------------------------------------------- chat bursts

_CHAT = (
    "# 아리와의 대화\n\n"
    "**아리**: 커피 마시고 싶다.\n\n"
    "**현우**: 헐 대박.\n\n"
    "**현우**: 여동생 진짜 이름은 임가을이야. 예전에 말한 미네르바는 농담이었어.\n\n"
    "**아리**: 고마워!\n\n"
    "**현우**: 비 오는 소리 좋다.\n\n"
    "**아리**: 밥은 챙겨 먹었어?\n\n"
)


def test_chat_note_bursts_isolate_fact_lines():
    chunks = chunk_note(_CHAT, chat_bursts=True)
    fact_chunks = [t for _, t in chunks if "임가을" in t]
    assert fact_chunks, "fact line must be indexed"
    # the fact's PRIMARY chunk is focused — not padded with the session's filler
    assert any("비 오는 소리" not in t for t in fact_chunks)
    # the quality gate packs, never drops: every original line is still indexed
    all_text = "\n".join(t for _, t in chunks)
    for line in ("커피 마시고 싶다", "헐 대박", "비 오는 소리", "밥은 챙겨"):
        assert line in all_text


def test_chat_bursts_keep_question_antecedent():
    body = (
        "# 대화\n\n"
        "**나**: 네 생일이 언제라고 했지?\n\n"
        "**AI**: 3월 14일이라고 말씀하셨어요.\n\n"
        "**나**: 아 맞다.\n\n"
        "**나**: 고마워.\n\n"
    )
    chunks = chunk_note(body, chat_bursts=True)
    # the answer chunk carries the preceding question as overlap
    ans = next(t for _, t in chunks if "3월 14일" in t)
    assert "생일" in ans


def test_chat_bursts_off_and_prose_unaffected():
    prose = (
        "요약입니다.\n\n결론: 매출이 올랐다.\n\n"
        "메모: 회의는 목요일.\n\n계획을 다시 세운다.\n\n다음 주에 검토한다.\n\n"
    )
    assert chunk_note(prose, chat_bursts=True) == chunk_note(prose, chat_bursts=False)
    # flag off → chat notes chunk like prose (single small chunk)
    assert len(chunk_note(_CHAT, chat_bursts=False)) == 1


def test_chat_bursts_respect_size_cap():
    body = "# 대화\n\n" + "\n\n".join(
        f"**나**: 사실 {i}번 " + "내용 " * 80 for i in range(8))
    chunks = chunk_note(body, chunk_chars=400, overlap=50, chat_bursts=True)
    assert all(len(t) <= 700 for _, t in chunks)
