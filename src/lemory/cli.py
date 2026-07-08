"""Lemory CLI: `lemory init | index | watch | search | ask | serve | status`."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .engine import create_engine

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
    cfg_file.write_text(f'[lemory]\nvault = "{vault}"\n')
    console.print(f"[green]wrote[/green] {cfg_file}")
    console.print("Set GEMINI_API_KEY in your environment (free-tier key works), then run: [bold]lemory index[/bold]")


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
):
    """Hybrid search over the indexed vault."""
    eng = _engine(vault)
    hits = eng.search(query, k=k, mode=mode)
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

    from .server import build_app

    eng = _engine(vault)
    uvicorn.run(build_app(eng, watch=watch), host=host, port=port)


if __name__ == "__main__":
    app()
