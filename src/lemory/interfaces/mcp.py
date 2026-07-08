"""MCP server: expose the vault to Claude Desktop / Claude Code / any MCP client.

    lemory mcp --vault ~/Obsidian/MyVault

Claude Desktop config:

    {"mcpServers": {"lemory": {"command": "lemory", "args": ["mcp", "--vault", "~/Obsidian/MyVault"]}}}

Tools: search_notes (hybrid retrieval), ask_notes (grounded answer with
citations), vault_status. The index refreshes incrementally before each call
if the vault changed, so results are always live.
"""

from __future__ import annotations

import json

from ..engine import Engine


def run_mcp(engine: Engine) -> None:
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("lemory")
    engine.index()

    @mcp.tool()
    def search_notes(query: str, k: int = 8) -> str:
        """Hybrid search (semantic + keyword + link-graph) over the user's
        Obsidian vault. Returns the top matching note excerpts."""
        engine.index()  # incremental: no-op unless files changed
        hits = engine.search(query, k=k)
        return json.dumps(
            [
                {"note": h.title, "path": h.path, "heading": h.heading,
                 "text": h.text, "score": round(h.score, 4)}
                for h in hits
            ],
            ensure_ascii=False,
        )

    @mcp.tool()
    def ask_notes(question: str) -> str:
        """Answer a question grounded ONLY in the user's Obsidian vault,
        with note citations."""
        engine.index()
        ans = engine.ask(question)
        return json.dumps(
            {"answer": ans.text,
             "sources": [{"note": h.title, "path": h.path} for h in ans.sources]},
            ensure_ascii=False,
        )

    @mcp.tool()
    def vault_status() -> str:
        """Index statistics for the connected vault."""
        return json.dumps(engine.status())

    mcp.run()
