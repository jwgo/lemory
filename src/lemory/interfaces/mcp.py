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
    def recent_notes(days: int = 7, limit: int = 20) -> str:
        """Notes the user touched in the last N days, newest first — for
        '요새 내가 뭐 했지?' style questions about recent activity."""
        import time
        from datetime import datetime

        engine.index()
        dates = engine.store.doc_dates()
        docs = {d.id: d for d in engine.store.all_docs()}
        cutoff = time.time() - days * 86400
        rows = sorted(
            ((ts, docs[did]) for did, ts in dates.items() if ts >= cutoff and did in docs),
            key=lambda x: -x[0],
        )[:limit]
        return json.dumps(
            [{"date": datetime.fromtimestamp(ts).date().isoformat(), "note": d.title,
              "path": d.path} for ts, d in rows],
            ensure_ascii=False,
        )

    @mcp.tool()
    def read_note(path: str, offset: int = 0, limit: int = 200) -> str:
        """Read a note's full markdown by its vault-relative path (as returned
        by search_notes/recent_notes). Filesystem-style memory access: search
        first, then drill into the exact note. offset/limit are line-based."""
        vault = engine.cfg.resolved_vault()
        target = (vault / path).resolve()
        if not str(target).startswith(str(vault)) or not target.is_file():
            return json.dumps({"error": f"no such note: {path}"})
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        body = "\n".join(lines[offset : offset + limit])
        return json.dumps(
            {"path": path, "lines": len(lines), "offset": offset, "content": body},
            ensure_ascii=False,
        )

    @mcp.tool()
    def list_notes(folder: str = "", limit: int = 100) -> str:
        """List note paths (optionally under a folder), newest-modified first —
        browse the vault like a filesystem."""
        vault = engine.cfg.resolved_vault()
        base = (vault / folder).resolve() if folder else vault
        if not str(base).startswith(str(vault)) or not base.is_dir():
            return json.dumps({"error": f"no such folder: {folder}"})
        files = sorted(base.rglob("*.md"), key=lambda p: -p.stat().st_mtime)[:limit]
        return json.dumps(
            [str(p.relative_to(vault)) for p in files], ensure_ascii=False
        )

    @mcp.tool()
    def vault_status() -> str:
        """Index statistics for the connected vault."""
        return json.dumps(engine.status())

    mcp.run()
