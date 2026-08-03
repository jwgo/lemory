"""New usage surfaces: pyramid HTTP endpoints, memory proxy, skill extraction."""
from __future__ import annotations

import json

import pytest

from lemory.ingestion.fragments import reflect, remember
from lemory.ingestion.pyramid import consolidate


# --------------------------------------------------------- pyramid over HTTP

def test_http_pyramid_endpoints(client):
    r = client.post("/memory/fragment",
                    json={"content": "답변은 한국어로", "type": "preference",
                          "case": "스타일"})
    assert r.status_code == 200

    rep = client.post("/memory/consolidate").json()
    assert rep["atoms"] >= 1 and rep["scenes_created"]

    # body content comes from the (fake) LLM here; the contract under test is
    # the surface: persona exists and is served
    p = client.get("/api/persona").json()
    assert p["exists"] and p["body"].strip()
    assert p["path"] == "페르소나.md"

    scenes = client.get("/api/scenes").json()["scenes"]
    assert scenes and scenes[0]["heat"] >= 1

    # idempotent second pass: cursor makes it a no-op
    assert client.post("/memory/consolidate").json()["atoms"] == 0


# ------------------------------------------------------------- memory proxy

class _FakeUpstream:
    """httpx.AsyncClient stand-in: records the outbound body, returns a fixed
    OpenAI-style completion."""

    captured: dict = {}

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        import httpx

        _FakeUpstream.captured = {"url": url, "body": json, "headers": headers}
        return httpx.Response(200, json={
            "id": "cmpl-1", "object": "chat.completion",
            "choices": [{"index": 0, "message":
                        {"role": "assistant", "content": "포트는 15000입니다."}}],
        })


def test_proxy_injects_memory_and_captures(client, engine, monkeypatch):
    import lemory.interfaces.proxy as proxy_mod

    monkeypatch.setattr(proxy_mod.httpx, "AsyncClient", _FakeUpstream)
    engine.cfg.openai_api_key = "sk-test"

    remember(engine, "배포 포트는 15000이다", type="fact", case="배포",
             title="배포 포트")

    r = client.post("/v1/chat/completions", json={
        "model": "gpt-4o-mini",
        "messages": [{"role": "system", "content": "You are helpful."},
                     {"role": "user", "content": "배포 포트 뭐였지?"}],
    })
    assert r.status_code == 200
    assert r.json()["choices"][0]["message"]["content"] == "포트는 15000입니다."

    sent = _FakeUpstream.captured["body"]["messages"]
    # client's own system prompt keeps precedence; memory follows it
    assert sent[0]["content"] == "You are helpful."
    assert "<lemory-memory>" in sent[1]["content"]
    assert "15000" in sent[1]["content"]          # per-turn recall found the fact
    # upstream auth comes from config, never from the client's header
    assert _FakeUpstream.captured["headers"]["Authorization"] == "Bearer sk-test"

    # capture: the exchange became an L0 session note
    import time
    for _ in range(40):                            # capture thread is async
        chats = list((engine.cfg.resolved_vault() / "chats" / "proxy").glob("*.md")) \
            if (engine.cfg.resolved_vault() / "chats" / "proxy").is_dir() else []
        if chats:
            break
        time.sleep(0.05)
    assert chats, "proxy exchange was not captured as a session note"
    body = chats[0].read_text(encoding="utf-8")
    assert "배포 포트 뭐였지?" in body and "포트는 15000입니다." in body
    assert "tags: [chat-import]" in body           # distill/consolidate see it


def test_proxy_without_upstream_key_fails_clearly(client, engine, monkeypatch):
    monkeypatch.setattr(engine.cfg, "openai_api_key", "", raising=False)
    monkeypatch.setattr(engine.cfg, "proxy_upstream_key", "", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "")
    r = client.post("/v1/chat/completions",
                    json={"model": "m", "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 502
    assert "upstream key" in r.json()["detail"]


def test_proxy_capture_can_be_disabled(client, engine, monkeypatch):
    import lemory.interfaces.proxy as proxy_mod

    monkeypatch.setattr(proxy_mod.httpx, "AsyncClient", _FakeUpstream)
    engine.cfg.openai_api_key = "sk-test"
    engine.cfg.proxy_capture = False
    try:
        client.post("/v1/chat/completions", json={
            "model": "m", "messages": [{"role": "user", "content": "캡처 끔"}]})
        proxy_dir = engine.cfg.resolved_vault() / "chats" / "proxy"
        assert not proxy_dir.is_dir() or not any(
            "캡처 끔" in p.read_text(encoding="utf-8")
            for p in proxy_dir.glob("*.md"))
    finally:
        engine.cfg.proxy_capture = True


# ---------------------------------------------------------- skill extraction

def _finish_case(engine):
    remember(engine, "포트 8080 충돌로 서버가 안 뜬다", type="error", case="배포",
             status="resolved")
    remember(engine, "포트를 15000으로 옮기기로 결정", type="decision", case="배포")
    reflect(engine, summary="포트 충돌을 정리했다", decisions=["15000 고정"],
            case="배포")


SKILL_OUT = (
    "name: port-conflict-triage\n"
    "## 언제 쓰나\n서버가 포트 점유로 안 뜰 때.\n"
    "## 언제 쓰지 않나\n네트워크 자체가 죽었을 때.\n"
    "## 절차\n1. lsof -i로 점유 프로세스 확인\n2. 대체 포트 선정\n3. 설정 반영 후 헬스체크\n"
    "## 판단 규칙\n사내 프록시 대역은 피한다.\n"
    "## 함정\n임시 프로세스 kill은 재부팅에서 재발한다.\n"
)


def test_skill_extraction_writes_gated_skill(engine, monkeypatch):
    from lemory.ingestion.skill_extract import extract_skills, list_skills

    engine.index()
    _finish_case(engine)
    monkeypatch.setattr(engine.llm, "generate", lambda *a, **k: SKILL_OUT)

    written = extract_skills(engine)
    assert written == ["스킬/port-conflict-triage.md"]
    body = (engine.cfg.resolved_vault() / written[0]).read_text(encoding="utf-8")
    assert "skill: true" in body and 'skill_case: "배포"' in body
    assert "## 절차" in body and "[[" in body      # provenance wikilinks
    assert list_skills(engine)[0]["name"] == "port-conflict-triage"
    # immediately searchable
    assert any(h.path == written[0]
               for h in engine.search("포트 충돌 절차", k=5))


def test_skill_gate_rejection_writes_nothing(engine, monkeypatch):
    from lemory.ingestion.skill_extract import extract_skills

    engine.index()
    _finish_case(engine)
    monkeypatch.setattr(engine.llm, "generate", lambda *a, **k: "없음")
    assert extract_skills(engine) == []
    assert not (engine.cfg.resolved_vault() / "스킬").exists()


def test_skill_open_case_is_not_extracted(engine, monkeypatch):
    from lemory.ingestion.skill_extract import extract_skills

    engine.index()
    remember(engine, "아직 안 고쳐진 버그", type="error", case="진행중")
    remember(engine, "관련 결정", type="decision", case="진행중")
    monkeypatch.setattr(engine.llm, "generate", lambda *a, **k: SKILL_OUT)
    # default selection only takes cases with zero open errors
    assert extract_skills(engine) == []


def test_skill_incremental_update_respects_nochange(engine, monkeypatch):
    from lemory.ingestion.skill_extract import extract_skills

    engine.index()
    _finish_case(engine)
    monkeypatch.setattr(engine.llm, "generate", lambda *a, **k: SKILL_OUT)
    first = extract_skills(engine)
    assert len(first) == 1
    remember(engine, "추가 사실", type="fact", case="배포")

    monkeypatch.setattr(engine.llm, "generate", lambda *a, **k: "변경 없음")
    assert extract_skills(engine) == []            # no rewrite, no duplicate file
    files = list((engine.cfg.resolved_vault() / "스킬").glob("*.md"))
    assert len(files) == 1


def test_skill_extraction_needs_llm(engine, monkeypatch):
    from lemory.ingestion.skill_extract import extract_skills

    engine.index()
    _finish_case(engine)
    monkeypatch.setattr(type(engine), "keyless", property(lambda self: True))
    assert extract_skills(engine) == []


def test_http_skills_endpoints(client, engine, monkeypatch):
    engine.index()
    _finish_case(engine)
    monkeypatch.setattr(engine.llm, "generate", lambda *a, **k: SKILL_OUT)
    r = client.post("/memory/skills-extract")
    assert r.status_code == 200 and r.json()["skills_written"]
    assert client.get("/api/skills").json()["skills"][0]["name"] == "port-conflict-triage"
