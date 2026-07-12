"""reor-style related notes: the note itself is the query."""

from lemory.retrieval.search import related_notes


def test_related_excludes_self_and_ranks_linked(engine):
    engine.index()
    rel = related_notes(engine, "Mercury Initiative.md", k=5)
    assert rel and all(r["path"] != "Mercury Initiative.md" for r in rel)
    # Dana is wikilinked from Mercury and shares vocabulary — must appear
    assert any(r["title"] == "Dana Petrov" for r in rel)
    scores = [r["score"] for r in rel]
    assert scores == sorted(scores, reverse=True)


def test_related_unknown_note(engine):
    engine.index()
    assert related_notes(engine, "no-such.md") == []


def test_related_http_endpoint(client):
        r = client.get("/api/related", params={"path": "Mercury Initiative.md", "k": 4})
        assert r.status_code == 200
        rows = r.json()
        assert rows and {"path", "title", "score"} <= set(rows[0])
        assert client.get("/api/related", params={"path": "nope.md"}).json() == []


# --- link suggestions (unlinked mentions -> [[link]] proposals) ------------

def test_suggest_links_surfaces_unlinked_mention(engine, vault):
    (vault / "Quarterly Plan.md").write_text(
        "Budget review with Dana Petrov next week. The Mercury Initiative "
        "depends on it.\n")
    engine.index()
    from lemory.retrieval.links import suggest_links

    rows = suggest_links(engine, path="Quarterly Plan.md", k=10)
    targets = {r["to_title"] for r in rows}
    assert "Dana Petrov" in targets or "Mercury Initiative" in targets
    row = rows[0]
    assert row["suggestion"].startswith("[[") and row["snippet"]


def test_suggest_links_skips_already_linked(engine, vault):
    (vault / "Linked Note.md").write_text(
        "Already linked to [[Dana Petrov]] here.\n")
    engine.index()
    from lemory.retrieval.links import suggest_links

    rows = suggest_links(engine, path="Linked Note.md", k=10)
    assert all(r["to_title"] != "Dana Petrov" or r["from_title"] != "Linked Note"
               for r in rows)


def test_suggest_links_unknown_path_raises(engine):
    engine.index()
    from lemory.retrieval.links import suggest_links
    import pytest

    with pytest.raises(ValueError):
        suggest_links(engine, path="no/such/note.md")


# --- drift detection (mex-style, vault edition) ----------------------------

def test_drift_detects_broken_wikilink_and_dup_flag(engine, vault):
    (vault / "Dangling.md").write_text("links to [[No Such Note]] here.")
    (vault / "memories").mkdir(exist_ok=True)
    (vault / "memories" / "dup.md").write_text(
        '---\nlemory_generated: true\npossible_duplicate_of: "[[Dana Petrov]]"\n---\nfact\n')
    (vault / "FileRef.md").write_text("see [old doc](gone/old.md) for details")
    engine.index()
    from lemory.retrieval.drift import detect_drift, render_repair_prompt

    f = detect_drift(engine)
    assert any(x["target"] == "No Such Note" for x in f["broken_wikilinks"])
    assert any(x["duplicate_of"] == "Dana Petrov" for x in f["unresolved_duplicates"])
    assert any(x["target"] == "gone/old.md" for x in f["missing_file_links"])
    prompt = render_repair_prompt(f, str(vault))
    assert "No Such Note" in prompt and "Repair ONLY" in prompt


def test_drift_clean_vault_is_clean(engine, vault):
    engine.index()
    from lemory.retrieval.drift import detect_drift, render_repair_prompt

    f = detect_drift(engine)
    # the conftest vault wikilinks all resolve
    assert f["unresolved_duplicates"] == []
    assert "No drift detected" in render_repair_prompt(
        {"broken_wikilinks": [], "missing_file_links": [],
         "unresolved_duplicates": [], "notes_scanned": 3}, str(vault))
