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


def test_related_http_endpoint(engine):
    from fastapi.testclient import TestClient

    from lemory.interfaces.http import build_app

    app = build_app(engine, watch=False)
    with TestClient(app) as client:
        r = client.get("/api/related", params={"path": "Mercury Initiative.md", "k": 4})
        assert r.status_code == 200
        rows = r.json()
        assert rows and {"path", "title", "score"} <= set(rows[0])
        assert client.get("/api/related", params={"path": "nope.md"}).json() == []
