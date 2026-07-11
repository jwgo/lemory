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
    }


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
