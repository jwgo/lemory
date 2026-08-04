"""MCP server: expose the vault to Claude Desktop / Claude Code / any MCP client.

    lemory mcp --vault ~/Obsidian/MyVault

Claude Desktop config:

    {"mcpServers": {"lemory": {"command": "lemory", "args": ["mcp", "--vault", "~/Obsidian/MyVault"]}}}

Read tools: search_notes, ask_notes, recent_notes, read_note, list_notes,
vault_status, vault_context (pre-assembled session context).
Write tools: save_memory (new Markdown note, never overwrites), append_note
(append-only). Memories live as plain Markdown in the user's vault · visible
in Obsidian, versionable, no lock-in. The index refreshes incrementally
before each call if the vault changed, so results are always live.
"""

from __future__ import annotations

import json

from ..engine import Engine


def run_mcp(engine: Engine, client: str = "mcp") -> None:
    from mcp.server.fastmcp import FastMCP
    from mcp.types import ToolAnnotations

    RO = ToolAnnotations(readOnlyHint=True)
    WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                            idempotentHint=False)

    mcp = FastMCP("lemory")
    engine.index()

    @mcp.tool(annotations=RO)
    def search_notes(query: str, k: int = 8) -> str:
        """Hybrid search (semantic + keyword + link-graph) over the user's
        Obsidian vault. Returns the top matching note excerpts."""
        engine.index()  # incremental: no-op unless files changed
        hits = engine.search(query, k=k, record=True, client=client)
        return json.dumps(
            [
                {"note": h.title, "path": h.path, "heading": h.heading,
                 "text": h.text, "score": round(h.score, 4)}
                for h in hits
            ],
            ensure_ascii=False,
        )

    @mcp.tool(annotations=RO)
    def ask_notes(question: str) -> str:
        """Answer a question grounded ONLY in the user's Obsidian vault,
        with note citations."""
        engine.index()
        ans = engine.ask(question, record=True, client=client)
        return json.dumps(
            {"answer": ans.text,
             "sources": [{"note": h.title, "path": h.path} for h in ans.sources]},
            ensure_ascii=False,
        )

    @mcp.tool(annotations=RO)
    def recent_notes(days: int = 7, limit: int = 20) -> str:
        """Notes the user touched in the last N days, newest first · for
        '요새 내가 뭐 했지?' style questions about recent activity."""
        from datetime import datetime

        engine.index()
        rows = engine.store.recent_docs(days, limit)
        return json.dumps(
            [{"date": datetime.fromtimestamp(ts).date().isoformat(), "note": d.title,
              "path": d.path} for ts, d in rows],
            ensure_ascii=False,
        )

    @mcp.tool(annotations=RO)
    def read_note(path: str, offset: int = 0, limit: int = 200) -> str:
        """Read a note's full markdown by its vault-relative path (as returned
        by search_notes/recent_notes). Filesystem-style memory access: search
        first, then drill into the exact note. offset/limit are line-based."""
        try:
            target = engine.safe_path(path)  # rejects .., abs paths, siblings
        except ValueError:
            return json.dumps({"error": f"no such note: {path}"})
        if not target.is_file():
            return json.dumps({"error": f"no such note: {path}"})
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        body = "\n".join(lines[offset : offset + limit])
        return json.dumps(
            {"path": path, "lines": len(lines), "offset": offset, "content": body},
            ensure_ascii=False,
        )

    @mcp.tool(annotations=RO)
    def list_notes(folder: str = "", limit: int = 100) -> str:
        """List note paths (optionally under a folder), newest-modified first ·
        browse the vault like a filesystem."""
        vault = engine.cfg.resolved_vault()
        try:
            base = engine.safe_path(folder) if folder else vault
        except ValueError:
            return json.dumps({"error": f"no such folder: {folder}"})
        if not base.is_dir():
            return json.dumps({"error": f"no such folder: {folder}"})
        files = sorted(base.rglob("*.md"), key=lambda p: -p.stat().st_mtime)[:limit]
        return json.dumps(
            [str(p.relative_to(vault)) for p in files], ensure_ascii=False
        )

    @mcp.tool(annotations=RO)
    def related_notes(path: str, k: int = 8) -> str:
        """Notes related to a given note by content similarity (the note
        itself is the query). Use after read_note to explore context."""
        engine.index()
        return json.dumps(engine.related(path, k=k), ensure_ascii=False)

    @mcp.tool(annotations=RO)
    def vault_status() -> str:
        """Index statistics for the connected vault."""
        return json.dumps(engine.status())

    @mcp.tool(annotations=RO)
    def vault_context(max_chars: int = 2400) -> str:
        """Pre-assembled situational context in one cheap call: persona (who
        the user is), scene map (which contexts exist, hottest first), pinned
        anchors, open cases, recent activity. Call this at the START of a
        session · it is the top of the memory pyramid, always safe to inject.

        Drill-down budget: when this context is not enough, use read_note on
        a scene path for the full narrative, or recall/search_notes for
        specifics · at most ~3 searches per turn; if 3 searches find nothing,
        the information is not in memory, so answer from what you have."""
        engine.index()
        return engine.context(max_chars=max_chars)

    @mcp.tool(annotations=WRITE)
    def consolidate_memory() -> str:
        """Promote new memories up the pyramid: L1 atoms (fact-sheet bullets +
        typed fragments) fold into L2 scene notes (living narratives, capped
        count) and the L3 persona note. Incremental and idempotent · call at
        session end after reflect. Everything written is a plain vault note."""
        engine.index()
        rep = engine.consolidate()
        return json.dumps({
            "atoms": rep.atoms,
            "scenes_updated": rep.scenes_updated,
            "scenes_created": rep.scenes_created,
            "absorbed_into_existing": rep.scenes_absorbed,
            "persona": rep.persona or None,
            "used_llm": rep.llm,
        }, ensure_ascii=False)

    @mcp.tool(annotations=WRITE)
    def extract_skills(case: str = "") -> str:
        """Extract reusable SKILL documents from finished work threads (cases
        with no unresolved errors). Gated hard: if the thread is not a
        recurring, transferable, executable-by-a-stranger workflow, nothing
        is written · an empty result is the normal outcome. Skills land in
        스킬/*.md and are immediately searchable."""
        engine.index()
        written = engine.extract_skills(cases=[case] if case.strip() else None)
        return json.dumps({"skills_written": written}, ensure_ascii=False)

    @mcp.tool(annotations=WRITE)
    def save_memory(content: str, title: str = "", folder: str = "memories",
                    tags: str = "") -> str:
        """Persist a memory as a NEW Markdown note in the user's vault (facts,
        decisions, preferences worth remembering across sessions). The note is
        immediately indexed and searchable, and visible in Obsidian. Never
        overwrites existing notes. `tags` is comma-separated."""
        tag_list = [t for t in (s.strip() for s in tags.split(",")) if t]
        try:
            path = engine.remember_note(content, title=title, folder=folder, tags=tag_list, client=client)
        except ValueError as e:
            return json.dumps({"error": str(e)})
        out: dict = {"saved": str(path)}
        related = getattr(path, "related", [])
        if related:
            # consolidation surface: the agent learns what the vault already
            # knows the moment it writes — a near-duplicate means "consider
            # citing/updating that note instead of stacking a copy"
            out["related_existing"] = related
            dup = next((r["title"] for r in related if r["near_duplicate"]), None)
            if dup:
                out["note"] = (f"possible duplicate of existing memory '{dup}' · "
                               "both are now linked via frontmatter")
        return json.dumps(out, ensure_ascii=False)

    # ---- agent working memory -------------------------------------------
    # remember → recall → reflect → resume_case: the loop that makes the next
    # session start where this one stopped. Fragments are ordinary vault
    # notes, so everything above (search_notes, read_note, the graph) sees
    # them too — the typed layer narrows, it never forks the store.

    @mcp.tool(annotations=WRITE)
    def remember(content: str, type: str = "fact", topic: str = "",
                 case: str = "", phase: str = "", status: str = "",
                 anchor: bool = False, title: str = "", tags: str = "") -> str:
        """Persist a TYPED memory fragment for future sessions.

        `type` is one of: fact (a stable truth), decision (a choice + reason),
        error (a failure; defaults to status=open until you mark it resolved),
        preference (how the user wants things done), procedure (repeatable
        steps), relation (how two things connect), episode (what happened).

        `case` groups fragments into one work thread — pass the same case id
        all session, then `resume_case` rebuilds it next time. `anchor=true`
        pins the fragment into every future session's opening context; use it
        only for things that are always relevant.
        """
        tag_list = [t for t in (s.strip() for s in tags.split(",")) if t]
        try:
            path = engine.remember(content, type=type, topic=topic, case=case,
                             phase=phase, status=status, anchor=anchor,
                             title=title, tags=tag_list, client=client)
        except ValueError as e:
            return json.dumps({"error": str(e)})
        out: dict = {"saved": str(path), "type": (type or "fact").lower()}
        related = getattr(path, "related", [])
        if related:
            out["related_existing"] = related
            dup = next((r["title"] for r in related if r["near_duplicate"]), None)
            if dup:
                out["note"] = (f"possible duplicate of existing memory '{dup}' — "
                               "both are now linked via frontmatter")
        return json.dumps(out, ensure_ascii=False)

    @mcp.tool(annotations=RO)
    def recall(query: str = "", type: str = "", case: str = "", topic: str = "",
               status: str = "", since_days: int = 0, k: int = 8) -> str:
        """Recall memory fragments, narrowed by type/case/topic/status/recency
        and ranked by the full hybrid retriever (keyword + semantic + link
        graph + recency). Leave `query` empty to list a scope newest-first
        ("what do I know about case X").

        Prefer this over search_notes when you want remembered facts rather
        than the user's own notes."""
        engine.index()
        rows = engine.recall(query=query, type=type, case=case, topic=topic,
                       status=status, since_days=since_days, k=k)
        return json.dumps(rows, ensure_ascii=False)

    @mcp.tool(annotations=WRITE)
    def reflect(summary: str, decisions: str = "", errors_resolved: str = "",
                next_steps: str = "", case: str = "", phase: str = "",
                notes_touched: str = "") -> str:
        """Close out a session: persist what happened as one episode fragment.

        Call this before the conversation ends. `decisions`, `errors_resolved`,
        `next_steps` and `notes_touched` are newline-separated lists. The next
        steps are what `resume_case` hands the next session, so write them as
        instructions to a stranger."""
        def _lines(s: str) -> list[str]:
            return [ln.strip() for ln in s.splitlines() if ln.strip()]

        try:
            path = engine.reflect(summary, decisions=_lines(decisions),
                            errors_resolved=_lines(errors_resolved),
                            next_steps=_lines(next_steps), case=case, phase=phase,
                            notes_touched=_lines(notes_touched), client=client)
        except ValueError as e:
            return json.dumps({"error": str(e)})
        return json.dumps({"saved": str(path)}, ensure_ascii=False)

    @mcp.tool(annotations=RO)
    def resume_case(case: str) -> str:
        """Rebuild a work thread: timeline, decisions so far, still-unresolved
        errors, and the next steps the last session recorded. Call this when
        picking a case back up — it is the cheapest way to stop re-deriving
        what already happened. `brief` is a paste-ready summary."""
        engine.index()
        try:
            return json.dumps(engine.resume_case(case), ensure_ascii=False)
        except ValueError as e:
            return json.dumps({"error": str(e)})

    @mcp.tool(annotations=RO)
    def list_cases(limit: int = 20) -> str:
        """Work threads with fragments, most recently touched first, with a
        count of unresolved errors each — "what was I in the middle of?"."""
        engine.index()
        return json.dumps(engine.open_cases(limit=limit), ensure_ascii=False)

    @mcp.tool(annotations=WRITE)
    def anchor_note(path: str, pinned: bool = True) -> str:
        """Pin (or unpin) a note as core memory — it is injected into every
        future session's opening context via vault_context. Keep the pinned
        set small; it costs tokens on every session."""
        try:
            rel = engine.set_anchor(path, on=pinned, client=client)
        except ValueError as e:
            return json.dumps({"error": str(e)})
        return json.dumps({"path": rel, "anchor": bool(pinned)}, ensure_ascii=False)

    @mcp.tool(annotations=RO)
    def suggest_links(path: str = "", k: int = 12) -> str:
        """Unlinked-mention [[link]] suggestions: notes whose text mentions
        another note's title without linking it. Pass a vault-relative path
        for one note's suggestions (both directions), or leave empty for the
        vault's top suggestions. Each row carries the mention's sentence."""
        engine.index()
        try:
            rows = engine.link_suggestions(path=path or None, k=k)
        except ValueError as e:
            return json.dumps({"error": str(e)})
        return json.dumps({"suggestions": rows}, ensure_ascii=False)

    @mcp.tool(annotations=WRITE)
    def append_note(path: str, content: str) -> str:
        """Append a timestamped section to an existing vault note (running
        logs, decision records). Creates the note if missing. Cannot modify
        existing content · append-only by design."""
        try:
            rel = engine.append_note(path, content, client=client)
        except ValueError as e:
            return json.dumps({"error": str(e)})
        return json.dumps({"appended": rel}, ensure_ascii=False)

    mcp.run()
