from fastapi.testclient import TestClient

from lemory.interfaces.http import build_app


def test_server_endpoints(engine):
    app = build_app(engine, watch=False)
    with TestClient(app) as client:
        st = client.get("/status").json()
        assert st["documents"] == 4  # lifespan indexed the vault

        r = client.get("/search", params={"q": "pricing decision", "k": 3})
        assert r.status_code == 200
        hits = r.json()
        assert hits and {"path", "title", "text", "score"} <= set(hits[0])

        assert client.get("/search", params={"q": "  "}).status_code == 400

        r = client.post("/ask", json={"question": "what is atlas?"})
        assert r.status_code == 200
        body = r.json()
        assert body["answer"] == "fake answer [1]"
        assert body["sources"]

        r = client.post("/index", json={"full": False})
        assert r.status_code == 200
        assert r.json()["unchanged"] == 4


def test_server_search_modes(engine):
    app = build_app(engine, watch=False)
    with TestClient(app) as client:
        for mode in ("hybrid", "vector", "bm25"):
            r = client.get("/search", params={"q": "pricing", "mode": mode})
            assert r.status_code == 200


def test_console_api(engine):
    app = build_app(engine, watch=False)
    with TestClient(app) as client:
        o = client.get("/api/overview").json()
        assert o["documents"] == 4 and "activity" in o and o["activity"]
        assert o["activity"][0]["kind"] == "startup"

        rows = client.get("/api/notes").json()
        assert len(rows) == 4
        assert {"path", "title", "tags", "mtime", "chunks", "links_out", "links_in"} <= set(rows[0])

        merc = next(r for r in rows if r["title"] == "Mercury Initiative")
        assert merc["links_out"] >= 1  # wikilink to Dana Petrov

        d = client.get("/api/note", params={"path": merc["path"]}).json()
        assert d["chunks"] and any(l["title"] == "Dana Petrov" for l in d["links_out"])
        dana = client.get("/api/note", params={"path": "Dana Petrov.md"}).json()
        assert any(l["title"] == "Mercury Initiative" for l in dana["links_in"])

        assert client.get("/api/note", params={"path": "nope.md"}).status_code == 404
        tags = client.get("/api/tags").json()
        assert any(t["tag"] == "project" for t in tags)


def test_console_config_roundtrip(engine):
    app = build_app(engine, watch=False)
    with TestClient(app) as client:
        cfg = client.get("/api/config").json()
        assert cfg["tunable"]["graph_expansion"] is True

        r = client.patch("/api/config", json={"graph_expansion": False, "per_doc_cap": 5})
        assert r.status_code == 200
        assert engine.cfg.graph_expansion is False and engine.cfg.per_doc_cap == 5

        # persisted to the vault's lemory.toml
        toml = (engine.cfg.resolved_vault() / "lemory.toml").read_text()
        assert "graph_expansion = false" in toml and "per_doc_cap = 5" in toml

        assert client.patch("/api/config", json={"vault": "/etc"}).status_code == 400
        assert client.patch("/api/config", json={"per_doc_cap": "abc"}).status_code == 400
        assert client.patch("/api/config", json={"context_style": "weird"}).status_code == 400


def test_console_ui_served(engine):
    app = build_app(engine, watch=False)
    with TestClient(app) as client:
        home = client.get("/")
        assert home.status_code == 200 and "Lemory 콘솔" in home.text
        assert client.get("/assets/app.css").status_code == 200
        assert client.get("/assets/app.js").status_code == 200
        assert client.get("/assets/evil.py").status_code == 404
