import json
import threading
import time

import httpx
import numpy as np
import pytest

from lemory.providers.base import RateLimiter, parse_json_loose
from lemory.providers.gemini import GeminiClient, _retry_delay_from_429


def make_client(handler, **kw) -> GeminiClient:
    c = GeminiClient(api_key="test", llm_rpm=1000, embed_rpm=1000, **kw)
    c._http = httpx.Client(transport=httpx.MockTransport(handler))
    return c


def gemini_text_response(text: str) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def test_rate_limiter_blocks_when_exceeded():
    rl = RateLimiter(rpm=2)
    t0 = time.monotonic()
    rl.acquire(); rl.acquire()
    assert time.monotonic() - t0 < 0.5

    # third acquire must wait; run in thread and confirm it doesn't return instantly
    done = threading.Event()
    threading.Thread(target=lambda: (rl.acquire(), done.set()), daemon=True).start()
    assert not done.wait(0.3)


def test_retry_delay_parsing():
    assert _retry_delay_from_429('{"retryDelay": "43s"}') == 43.0
    assert _retry_delay_from_429('{"retryDelay": "1.5s"}') == 1.5
    assert _retry_delay_from_429("nope") is None


@pytest.mark.parametrize("raw,expected", [
    ('{"a": 1}', {"a": 1}),
    ('```json\n{"a": 1}\n```', {"a": 1}),
    ('```\n[1, 2]\n```', [1, 2]),
    ('Here you go: {"a": {"b": 2}} hope that helps', {"a": {"b": 2}}),
])
def test_parse_json_loose(raw, expected):
    assert parse_json_loose(raw) == expected


def test_generate_returns_text():
    def handler(request):
        return httpx.Response(200, json=gemini_text_response("hello"))
    c = make_client(handler)
    assert c.generate("hi") == "hello"


def test_generate_retries_on_503_then_succeeds():
    calls = {"n": 0}
    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, json={"error": {"message": "busy"}})
        return httpx.Response(200, json=gemini_text_response("ok"))
    c = make_client(handler)
    assert c.generate("hi") == "ok"
    assert calls["n"] == 2


def test_generate_falls_back_to_second_model():
    def handler(request):
        if "flash-lite" in str(request.url):
            return httpx.Response(200, json=gemini_text_response("from-fallback"))
        return httpx.Response(400, json={"error": {"message": "bad"}})
    c = make_client(handler, llm_model="gemini-2.5-flash",
                    llm_fallback_model="gemini-2.5-flash-lite")
    assert c.generate("hi") == "from-fallback"


def test_generate_raises_on_400_single_model():
    def handler(request):
        return httpx.Response(400, json={"error": {"message": "invalid"}})
    c = make_client(handler)
    with pytest.raises(RuntimeError, match="all models failed"):
        c.generate("hi")


def test_embed_batches_and_normalizes():
    seen_batches = []
    def handler(request):
        body = json.loads(request.content)
        n = len(body["requests"])
        seen_batches.append(n)
        return httpx.Response(200, json={"embeddings": [{"values": [3.0] + [0.0] * 767}] * n})
    c = make_client(handler, embed_batch=96)
    out = c.embed(["a"] * 100)  # forces two batches (96 + 4)
    assert out.shape == (100, 768)
    assert seen_batches == [96, 4]
    assert np.allclose(np.linalg.norm(out, axis=1), 1.0)


def test_embed_truncates_long_text():
    def handler(request):
        body = json.loads(request.content)
        assert len(body["requests"][0]["content"]["parts"][0]["text"]) <= 8000
        return httpx.Response(200, json={"embeddings": [{"values": [1.0] * 768}]})
    c = make_client(handler)
    c.embed(["x" * 50000])


def test_json_mode_sets_mime():
    def handler(request):
        body = json.loads(request.content)
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        return httpx.Response(200, json=gemini_text_response('{"ok": true}'))
    c = make_client(handler)
    assert c.generate_json("hi") == {"ok": True}
