import json

import httpx
import numpy as np
import pytest

from lemory.openai_client import OpenAIClient


def make_client(handler, **kw) -> OpenAIClient:
    c = OpenAIClient(api_key="test", llm_rpm=1000, embed_rpm=1000, **kw)
    c._http = httpx.Client(transport=httpx.MockTransport(handler))
    return c


def chat_response(text: str) -> dict:
    return {"choices": [{"message": {"content": text}}]}


def test_generate():
    def handler(request):
        body = json.loads(request.content)
        assert body["model"] == "gpt-4o-mini"
        assert body["messages"][0]["role"] == "system"
        return httpx.Response(200, json=chat_response("hi there"))
    c = make_client(handler)
    assert c.generate("hello", system="be nice") == "hi there"


def test_generate_json_mode():
    def handler(request):
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json=chat_response('{"a": 1}'))
    c = make_client(handler)
    assert c.generate_json("x") == {"a": 1}


def test_retry_on_429_with_retry_after():
    calls = {"n": 0}
    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "0"}, json={"error": "rl"})
        return httpx.Response(200, json=chat_response("ok"))
    c = make_client(handler)
    assert c.generate("x") == "ok"
    assert calls["n"] == 2


def test_raises_on_401():
    def handler(request):
        return httpx.Response(401, json={"error": {"message": "bad key"}})
    c = make_client(handler)
    with pytest.raises(RuntimeError, match="OpenAI error 401"):
        c.generate("x")


def test_embed_normalized_and_dimensioned():
    def handler(request):
        body = json.loads(request.content)
        assert body["dimensions"] == 768
        n = len(body["input"])
        return httpx.Response(200, json={
            "data": [{"embedding": [2.0] + [0.0] * 767, "index": i} for i in range(n)]
        })
    c = make_client(handler)
    out = c.embed(["a", "b", ""])  # empty string must not be sent as-is
    assert out.shape == (3, 768)
    assert np.allclose(np.linalg.norm(out, axis=1), 1.0)


def test_engine_uses_openai_when_only_openai_key(tmp_path, monkeypatch):
    from lemory.config import LemoryConfig
    from lemory.engine import Engine

    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    v = tmp_path / "v"
    v.mkdir()
    eng = Engine(LemoryConfig(vault=v, data_dir=tmp_path / "d"))
    assert type(eng.llm).__name__ == "OpenAIClient"
    eng.close()
