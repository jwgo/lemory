from fastapi.testclient import TestClient

from lemory.server import build_app


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
