"""Lemory CLI: `lemory init | index | watch | search | ask | serve | status`."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from ..engine import create_engine

app = typer.Typer(help="Lemory — personal knowledge base backend for Obsidian.", no_args_is_help=True)
console = Console()

logging.basicConfig(level=logging.INFO, format="%(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)


def _engine(vault: Optional[Path]):
    return create_engine(vault=vault)


@app.command()
def init(vault: Path = typer.Argument(..., help="Path to your Obsidian vault")):
    """Write a lemory.toml pointing at your vault (one-time setup)."""
    vault = vault.expanduser().resolve()
    if not vault.is_dir():
        console.print(f"[red]not a directory:[/red] {vault}")
        raise typer.Exit(1)
    cfg_file = Path.cwd() / "lemory.toml"
    # json.dumps produces a valid TOML basic string (escapes backslashes and
    # quotes) — bare f-string interpolation breaks on Windows paths
    cfg_file.write_text(f"[lemory]\nvault = {json.dumps(str(vault))}\n")
    console.print(f"[green]wrote[/green] {cfg_file}")
    console.print("Set GEMINI_API_KEY in your environment (free-tier key works), then run: [bold]lemory index[/bold]")


@app.command()
def setup(
    vault: Optional[Path] = typer.Option(None, help="Vault path (prompted if omitted)"),
    key: Optional[str] = typer.Option(None, help="Gemini API key (prompted if omitted)"),
    index_now: bool = typer.Option(True, help="Run the first index at the end"),
):
    """One-shot setup: vault + API key + health check + first index.

    The key is stored in ~/.lemory/env (owner-only), so Obsidian/Claude/VS Code
    integrations work without shell environment tricks.
    """
    from ..config import load_config, save_global_env

    console.print("[bold]Lemory setup[/bold] — 세 가지만 하면 끝납니다.\n")

    # 1. vault
    while True:
        v = vault or Path(typer.prompt("1) Obsidian 볼트 경로 (예: ~/Obsidian/MyVault)"))
        v = v.expanduser().resolve()
        if v.is_dir():
            break
        console.print(f"[red]폴더가 없습니다:[/red] {v}")
        vault = None
    n_md = sum(1 for _ in v.rglob("*.md"))
    console.print(f"   [green]✔[/green] {v} ({n_md}개 노트)")

    # 2. key
    existing = load_config().resolved_gemini_key()
    if key is None and existing:
        console.print("   [green]✔[/green] Gemini 키가 이미 설정되어 있습니다")
        k = existing
    else:
        k = key or typer.prompt("2) Gemini API 키 (무료: https://aistudio.google.com)", hide_input=True)
        env_file = save_global_env({"GEMINI_API_KEY": k.strip()})
        console.print(f"   [green]✔[/green] 키 저장: {env_file} (권한 600)")

    # 3. config file
    cfg_file = Path.cwd() / "lemory.toml"
    cfg_file.write_text(f"[lemory]\nvault = {json.dumps(str(v))}\n")
    console.print(f"   [green]✔[/green] 설정 저장: {cfg_file}")

    # health check + first index
    eng = _engine(v)
    try:
        vec = eng.llm.embed(["setup ping"])
        console.print(f"   [green]✔[/green] API 연결 확인 ({vec.shape[-1]}d embeddings)")
    except Exception as e:
        console.print(f"   [red]✘ API 확인 실패:[/red] {str(e)[:120]}")
        raise typer.Exit(1)
    if index_now:
        with console.status("첫 인덱싱 중... (이후에는 변경분만 처리됩니다)"):
            rep = eng.index()
        console.print(f"   [green]✔[/green] 인덱싱 완료: 노트 {rep.added + rep.updated}개, "
                      f"청크 {rep.chunks}개 ({rep.seconds:.0f}s)")
    console.print(
        "\n[bold]다 됐습니다![/bold] 이렇게 써보세요:\n"
        "  lemory ask \"요새 내가 뭐 했지?\"\n"
        "  lemory serve            # http://127.0.0.1:8377 웹 UI + Obsidian 플러그인 백엔드\n"
        "  claude mcp add lemory -- lemory mcp   # Claude Code에서 바로 사용"
    )


@app.command()
def doctor(vault: Optional[Path] = typer.Option(None, help="Vault path to check")):
    """Diagnose your setup in one command: key, vault, database, search."""
    from ..config import load_config

    ok = True

    def check(label: str, passed: bool, detail: str = "") -> bool:
        mark = "[green]✔[/green]" if passed else "[red]✘[/red]"
        console.print(f" {mark} {label}" + (f" — {detail}" if detail else ""))
        return passed

    cfg = load_config(vault=vault)

    # 1. vault
    try:
        v = cfg.resolved_vault()
        n_md = sum(1 for _ in v.rglob("*.md"))
        ok &= check("vault", v.is_dir(), f"{v} ({n_md} .md files)")
    except Exception as e:
        ok = check("vault", False, str(e))
        v = None

    # 2. API key + live round-trip
    try:
        provider = cfg.resolved_provider()
        check("api key", True, f"provider={provider}")
        try:
            eng = _engine(vault)
            vec = eng.llm.embed(["lemory doctor ping"])
            ok &= check("embedding API", vec.shape[-1] == cfg.active_embed_dim(),
                        f"{cfg.active_embed_model()} @{vec.shape[-1]}d")
        except Exception as e:
            ok = check("embedding API", False, str(e)[:120])
    except Exception as e:
        ok = check("api key", False, str(e)[:120])

    # 3. sqlite features
    import sqlite3
    try:
        c = sqlite3.connect(":memory:")
        c.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        ok &= check("sqlite FTS5", True, sqlite3.sqlite_version)
    except Exception as e:
        ok = check("sqlite FTS5", False, str(e))

    # 4. index state (empty is a to-do, not a failure)
    if v is not None:
        try:
            eng = _engine(vault)
            st = eng.status()
            if st["documents"] > 0:
                check("index", True,
                      f"{st['documents']} docs / {st['chunks']} chunks / {st['links']} links")
                hits = eng.search("test", k=1)
                ok &= check("search", True, f"returned {len(hits)} hit(s)")
            else:
                console.print(" [yellow]⚠[/yellow] index — empty, run [bold]lemory index[/bold] to build it")
        except Exception as e:
            ok = check("index", False, str(e)[:120])

    console.print()
    if ok:
        console.print("[green]all good[/green] — try: [bold]lemory ask \"요새 내가 뭐 했지?\"[/bold]")
    else:
        console.print("[yellow]fix the ✘ items above and re-run[/yellow] [bold]lemory doctor[/bold]")
        raise typer.Exit(1)


@app.command()
def recent(
    vault: Optional[Path] = typer.Option(None),
    days: int = typer.Option(7, help="Look-back window in days"),
    limit: int = typer.Option(20, help="Max notes to list"),
):
    """What did I touch lately? Notes from the last N days, newest first."""
    import time as _time
    from datetime import datetime

    eng = _engine(vault)
    dates = eng.store.doc_dates()
    docs = {d.id: d for d in eng.store.all_docs()}
    cutoff = _time.time() - days * 86400
    rows = sorted(
        ((ts, docs[did]) for did, ts in dates.items() if ts >= cutoff and did in docs),
        key=lambda x: -x[0],
    )[:limit]
    if not rows:
        console.print(f"no notes in the last {days} days")
        return
    table = Table(show_header=True)
    table.add_column("date", width=12)
    table.add_column("note")
    for ts, doc in rows:
        table.add_row(datetime.fromtimestamp(ts).date().isoformat(), doc.path)
    console.print(table)


@app.command()
def index(
    vault: Optional[Path] = typer.Option(None, help="Vault path (else lemory.toml / LEMORY_VAULT)"),
    full: bool = typer.Option(False, help="Re-chunk everything (embeddings still cached)"),
):
    """Index the vault incrementally."""
    eng = _engine(vault)
    with console.status("indexing..."):
        rep = eng.index(full=full, progress=lambda m: console.log(m))
    console.print(
        f"[green]done[/green] +{rep.added} added, ~{rep.updated} updated, -{rep.removed} removed, "
        f"{rep.unchanged} unchanged · {rep.chunks} chunks ({rep.embedded} embedded) · {rep.seconds:.1f}s"
    )
    for e in rep.errors:
        console.print(f"[yellow]warn[/yellow] {e}")


@app.command()
def watch(vault: Optional[Path] = typer.Option(None)):
    """Index, then keep syncing as the vault changes (Ctrl-C to stop)."""
    eng = _engine(vault)
    console.print("[green]watching[/green] — edit your vault, Lemory keeps up. Ctrl-C to stop.")
    eng.watch()


@app.command()
def search(
    query: str,
    k: int = typer.Option(8, help="Number of results"),
    vault: Optional[Path] = typer.Option(None),
    mode: str = typer.Option("hybrid", help="hybrid | vector | bm25 (ablation)"),
    expand: bool = typer.Option(False, help="LLM query expansion (qmd-style, 1 extra call)"),
    rerank: bool = typer.Option(False, help="LLM rerank of top candidates (1 extra call)"),
):
    """Hybrid search over the indexed vault."""
    eng = _engine(vault)
    hits = eng.search(query, k=k, mode=mode, expand=expand or None, rerank=rerank or None)
    table = Table(show_lines=True)
    table.add_column("#", width=3)
    table.add_column("note")
    table.add_column("score", width=8)
    table.add_column("excerpt")
    for i, h in enumerate(hits, 1):
        loc = h.title + (f" › {h.heading}" if h.heading else "")
        table.add_row(str(i), loc, f"{h.score:.4f}", h.text[:180].replace("\n", " "))
    console.print(table)


@app.command()
def ask(
    question: str,
    k: int = typer.Option(8),
    vault: Optional[Path] = typer.Option(None),
):
    """Ask a question; the answer is grounded in your notes with citations."""
    eng = _engine(vault)
    ans = eng.ask(question, k=k)
    console.print(ans.text)
    console.print("\n[dim]" + ans.render_sources() + "[/dim]")


@app.command()
def status(vault: Optional[Path] = typer.Option(None)):
    """Show index statistics."""
    eng = _engine(vault)
    console.print_json(json.dumps(eng.status()))


@app.command()
def serve(
    vault: Optional[Path] = typer.Option(None),
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8377),
    watch: bool = typer.Option(True, help="Keep the index live while serving"),
):
    """Run the HTTP API (and vault watcher) — the 'backend that just runs'."""
    import uvicorn

    from .http import build_app

    eng = _engine(vault)
    uvicorn.run(build_app(eng, watch=watch), host=host, port=port)


@app.command()
def mcp(vault: Optional[Path] = typer.Option(None)):
    """Run as an MCP server (stdio) for Claude Desktop / Claude Code."""
    from .mcp import run_mcp

    run_mcp(_engine(vault))


@app.command()
def enrich(
    vault: Optional[Path] = typer.Option(None),
    max_docs: int = typer.Option(50, help="Notes to enrich in this pass"),
):
    """Optional: LLM entity extraction to densify the graph (uses quota)."""
    from ..ingestion import Indexer

    eng = _engine(vault)
    eng.index()
    n = Indexer(eng).enrich_entities(max_docs=max_docs)
    console.print(f"[green]enriched[/green] {n} notes, links now: {eng.store.link_count()}")


if __name__ == "__main__":
    app()
