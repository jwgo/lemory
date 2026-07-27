"""MCP surface: tool registration and the write tools, via the real SDK."""

import asyncio
import json
from unittest.mock import patch

import pytest

mcp_sdk = pytest.importorskip("mcp", reason="pip install 'lemory[mcp]'")


@pytest.fixture
def mcp_app(engine):
    from mcp.server.fastmcp import FastMCP

    captured = {}
    with patch.object(FastMCP, "run", lambda self: captured.setdefault("app", self)):
        from lemory.interfaces.mcp import run_mcp

        run_mcp(engine)
    return captured["app"]


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_all_tools_registered(mcp_app):
    names = {t.name for t in _run(mcp_app.list_tools())}
    assert names == {
        "search_notes", "ask_notes", "recent_notes", "read_note", "list_notes",
        "related_notes", "vault_status", "vault_context", "suggest_links",
        "save_memory", "append_note",
        # agent working memory
        "remember", "recall", "reflect", "resume_case", "list_cases",
        "anchor_note",
    }


def test_agent_memory_loop_over_mcp(mcp_app, vault):
    """The whole point of the layer: what one session remembers, the next one
    resumes — through the tools an agent actually calls."""
    _c, meta = _run(mcp_app.call_tool(
        "remember",
        {"content": "포트 8080이 점유되어 서버가 안 뜬다", "type": "error",
         "case": "배포", "phase": "setup"}))
    assert json.loads(meta["result"])["type"] == "error"

    _c, meta = _run(mcp_app.call_tool(
        "remember",
        {"content": "포트를 15000으로 옮기기로 결정", "type": "decision",
         "case": "배포"}))
    assert "saved" in json.loads(meta["result"])

    # scoped recall sees only the errors
    _c, meta = _run(mcp_app.call_tool("recall", {"query": "포트", "type": "error"}))
    rows = json.loads(meta["result"])
    assert rows and all(r["type"] == "error" for r in rows)
    assert rows[0]["status"] == "open"

    _c, meta = _run(mcp_app.call_tool(
        "reflect",
        {"summary": "포트 정리", "next_steps": "헬스체크 추가\n문서 갱신",
         "case": "배포"}))
    assert "saved" in json.loads(meta["result"])

    _c, meta = _run(mcp_app.call_tool("resume_case", {"case": "배포"}))
    out = json.loads(meta["result"])
    assert out["next_steps"] == ["헬스체크 추가", "문서 갱신"]
    assert [o["type"] for o in out["open"]] == ["error"]

    _c, meta = _run(mcp_app.call_tool("list_cases", {}))
    assert any(c["case"] == "배포" and c["open"] == 1
               for c in json.loads(meta["result"]))


def test_anchor_tool_pins_into_session_context(mcp_app, vault):
    _c, meta = _run(mcp_app.call_tool(
        "remember", {"content": "항상 한국어로 답한다", "type": "preference",
                     "title": "언어 선호"}))
    rel = json.loads(meta["result"])["saved"]

    _c, meta = _run(mcp_app.call_tool("anchor_note", {"path": rel}))
    assert json.loads(meta["result"])["anchor"] is True

    _c, meta = _run(mcp_app.call_tool("vault_context", {"max_chars": 4000}))
    assert "언어 선호" in meta["result"]

    _c, meta = _run(mcp_app.call_tool("anchor_note", {"path": rel, "pinned": False}))
    assert json.loads(meta["result"])["anchor"] is False


def test_anchor_tool_reports_missing_note(mcp_app):
    _c, meta = _run(mcp_app.call_tool("anchor_note", {"path": "없는노트.md"}))
    assert "error" in json.loads(meta["result"])


def test_save_memory_tool_roundtrip(mcp_app, vault):
    _content, meta = _run(mcp_app.call_tool(
        "save_memory",
        {"content": "user prefers usage-based pricing", "title": "Pricing pref",
         "tags": "product, decision"}))
    assert json.loads(meta["result"])["saved"] == "memories/Pricing pref.md"
    text = (vault / "memories/Pricing pref.md").read_text(encoding="utf-8")
    assert "tags: [product, decision]" in text
    # immediately searchable through the search tool
    _c, meta = _run(mcp_app.call_tool("search_notes",
                                      {"query": "usage-based pricing preference", "k": 3}))
    assert any(h["path"] == "memories/Pricing pref.md" for h in json.loads(meta["result"]))


def test_write_tools_report_errors_as_json(mcp_app):
    _c, meta = _run(mcp_app.call_tool("save_memory", {"content": "x", "folder": "../up"}))
    assert "error" in json.loads(meta["result"])
    _c, meta = _run(mcp_app.call_tool("append_note", {"path": "../up.md", "content": "x"}))
    assert "error" in json.loads(meta["result"])


def test_vault_context_tool(mcp_app):
    _c, meta = _run(mcp_app.call_tool("vault_context", {}))
    assert meta["result"].startswith("# Vault context")
