"""Lemory CLI: `lemory init | index | watch | search | ask | serve | status`."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from ..engine import create_engine

app = typer.Typer(help="Lemory — 당신의 마크다운을 위한 로컬 메모리 미들웨어 (local memory middleware for your Markdown).", no_args_is_help=True)
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
def up(
    vault: Path = typer.Argument(..., help="Obsidian vault path"),
    port: int = typer.Option(8377),
    serve_after: bool = typer.Option(True, "--serve/--no-serve",
                                     help="Start the server after indexing"),
):
    """딸깍 — zero questions asked: detect a key (env/.env/~/.lemory/env),
    pick the best available mode, write config, index, and serve.

    * Gemini key found        → full mode (answers + embeddings)
    * no key, fastembed there → local search-only mode
    * neither                 → keyless mode (BM25 + link graph; still useful)
    """
    from ..config import load_config

    v = vault.expanduser().resolve()
    if not v.is_dir():
        console.print(f"[red]폴더가 없습니다:[/red] {v}")
        raise typer.Exit(1)
    n_md = sum(1 for _ in v.rglob("*.md"))

    extra = ""
    if load_config().resolved_gemini_key():
        mode_desc = "Gemini (키 감지됨 — 질문·답변 포함)"
    else:
        try:
            import fastembed  # noqa: F401

            extra = 'provider = "local"\n'
            mode_desc = "로컬 검색 전용 (fastembed — 키 없음)"
        except ImportError:
            mode_desc = "키 없음 — BM25+링크 그래프 검색 (키를 넣으면 자동 업그레이드)"

    cfg_file = v / "lemory.toml"
    if not cfg_file.exists():
        cfg_file.write_text(f"[lemory]\nvault = {json.dumps(str(v))}\n{extra}")
    console.print(f"[green]✔[/green] {v} ({n_md}개 노트) · 모드: {mode_desc}")

    eng = _engine(v)
    plan = eng.index_plan()
    if plan.embeds_needed:
        console.print(f"  첫 색인: 청크 {plan.chunks_total}개 · 예상 {plan.human_eta()}")
    with console.status("색인 중..."):
        rep = eng.index()
    console.print(f"[green]✔[/green] 색인 완료: 노트 {rep.added + rep.updated}개, "
                  f"청크 {rep.chunks}개 ({rep.seconds:.0f}s)")
    console.print(
        f"\n  대시보드  →  http://127.0.0.1:{port}\n"
        f"  Claude 연결  →  claude mcp add lemory -- lemory mcp --vault {v}\n"
        f"  질문  →  lemory ask \"요새 내가 하던 그거 뭐였지?\"\n")
    if serve_after:
        import uvicorn

        from .http import build_app

        uvicorn.run(build_app(eng, watch=True), host="127.0.0.1", port=port)


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

    # 2. execution mode
    extra_toml = ""
    if key is not None:
        mode = "1"  # explicit --key means Gemini mode
    else:
        console.print(
            "\n2) 실행 모드를 고르세요:\n"
            "   [bold]1[/bold]  Gemini 무료 API — 답변 생성 포함, 카드 등록 불필요 [dim](추천)[/dim]\n"
            "   [bold]2[/bold]  완전 로컬 (Ollama) — Gemma 3n E4B 4bit + Qwen3-Embedding-0.6B,\n"
            "      인터넷·키 없이 질문까지 전부 [dim](RAM 8GB+, 다운로드 ~6GB)[/dim]\n"
            "   [bold]3[/bold]  경량 로컬 검색 전용 — MiniLM 220MB, ask 제외 [dim](RAM 4GB면 충분)[/dim]"
        )
        mode = typer.prompt("   선택", default="1").strip()

    if mode == "2":
        extra_toml = _setup_ollama()
    elif mode == "3":
        extra_toml = _setup_fastembed()
    else:
        existing = load_config().resolved_gemini_key()
        if key is None and existing:
            console.print("   [green]✔[/green] Gemini 키가 이미 설정되어 있습니다")
        else:
            k = key or typer.prompt("   Gemini API 키 (무료: https://aistudio.google.com)", hide_input=True)
            env_file = save_global_env({"GEMINI_API_KEY": k.strip()})
            console.print(f"   [green]✔[/green] 키 저장: {env_file} (권한 600)")

    # 3. config file
    cfg_file = Path.cwd() / "lemory.toml"
    cfg_file.write_text(f"[lemory]\nvault = {json.dumps(str(v))}\n{extra_toml}")
    console.print(f"   [green]✔[/green] 설정 저장: {cfg_file}")

    # health check + first index
    eng = _engine(v)
    try:
        vec = eng.llm.embed(["setup ping"])
        console.print(f"   [green]✔[/green] 임베딩 연결 확인 ({vec.shape[-1]}d)")
    except Exception as e:
        console.print(f"   [red]✘ 연결 확인 실패:[/red] {str(e)[:160]}")
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


def _machine_ram_gb() -> float:
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3
    except (ValueError, OSError, AttributeError):
        return 0.0  # unknown (e.g. Windows) — skip the warning


def _setup_ollama() -> str:
    """Interactive Ollama mode setup. Returns extra lemory.toml lines."""
    from ..providers.ollama import DEFAULT_EMBED, DEFAULT_HOST, DEFAULT_LLM, OllamaClient

    ram = _machine_ram_gb()
    if 0 < ram < 8:
        console.print(
            f"   [yellow]⚠ RAM {ram:.0f}GB 감지 — Gemma 3n E4B는 8GB 이상을 권장합니다."
            " 느리거나 스왑이 발생할 수 있어요 (모드 3이 가벼운 대안).[/yellow]"
        )
    client = OllamaClient(host=DEFAULT_HOST)
    if not client.server_alive():
        console.print(
            "   [red]✘ Ollama가 실행 중이 아닙니다.[/red]\n"
            "     설치: [bold]https://ollama.com/download[/bold] (macOS/Windows 앱 또는\n"
            "           `curl -fsSL https://ollama.com/install.sh | sh`)\n"
            "     실행 후 다시 `lemory setup`을 돌려주세요."
        )
        raise typer.Exit(1)
    console.print("   [green]✔[/green] Ollama 서버 연결됨")

    installed = client.installed_models()
    for model, size in ((DEFAULT_LLM, "~5.6GB"), (DEFAULT_EMBED, "~640MB")):
        if any(m.startswith(model) for m in installed):
            console.print(f"   [green]✔[/green] {model} 설치됨")
            continue
        if typer.confirm(f"   {model} 모델이 없습니다. 지금 받을까요? ({size})", default=True):
            import subprocess

            r = subprocess.run(["ollama", "pull", model])
            if r.returncode != 0:
                console.print(f"   [red]✘ pull 실패[/red] — 수동으로: ollama pull {model}")
                raise typer.Exit(1)
        else:
            console.print(f"   나중에 직접 받아주세요: [bold]ollama pull {model}[/bold]")
    client.close()
    console.print("   [green]✔[/green] 완전 로컬 모드 — 볼트 내용이 컴퓨터 밖으로 나가지 않습니다")
    return 'provider = "ollama"\n'


def _setup_fastembed() -> str:
    """Search-only local mode. Returns extra lemory.toml lines."""
    try:
        import fastembed  # noqa: F401

        console.print("   [green]✔[/green] fastembed 준비됨 (첫 색인 때 모델 220MB 자동 다운로드)")
    except ImportError:
        console.print(
            "   [red]✘ fastembed가 없습니다.[/red] 먼저:\n"
            "     pip install \"lemory[local]\"   (또는 pipx inject lemory fastembed)"
        )
        raise typer.Exit(1)
    console.print("   [dim]검색·색인·콘솔은 전부 되고, ask(답변 생성)만 키가 필요합니다.[/dim]")
    return 'provider = "local"\n'


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

    # 2. provider + live round-trip. Keyless is a supported tier, not a
    # failure: lexical search (BM25 + link graph) works without any key.
    try:
        provider = cfg.resolved_provider()
        check("provider", True, f"{provider}")
        try:
            eng = _engine(vault)
            vec = eng.llm.embed(["lemory doctor ping"])
            ok &= check("embedding API", vec.shape[-1] == cfg.active_embed_dim(),
                        f"{cfg.active_embed_model()} @{vec.shape[-1]}d")
        except Exception as e:
            ok = check("embedding API", False, str(e)[:120])
    except RuntimeError:
        console.print(
            " [yellow]⚠[/yellow] provider — 키 없음: 렉시컬 모드로 동작 중 "
            "(BM25+링크 그래프). 시맨틱 검색·ask는 GEMINI_API_KEY를 넣으면 "
            "다음 색인에서 자동 활성화됩니다")

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
                # probe with the vault's own top note title, so a healthy
                # index can't return 0 and pass anyway
                docs = eng.store.all_docs()
                probe = docs[0].title if docs else "test"
                hits = eng.search(probe, k=1)
                ok &= check("search", bool(hits), f"returned {len(hits)} hit(s) for '{probe}'")
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
    from datetime import datetime

    eng = _engine(vault)
    rows = eng.store.recent_docs(days, limit)
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
def context(
    vault: Optional[Path] = typer.Option(None),
    max_chars: int = typer.Option(2400, help="Budget for the context block"),
):
    """Pre-assembled vault context (stats, recent, hot, hubs, tags) — pipe
    this into any agent for instant situational awareness."""
    from ..ingestion.memory import context_block

    eng = _engine(vault)
    eng.index()
    print(context_block(eng, max_chars=max_chars))


@app.command()
def remember(
    content: str = typer.Argument(..., help="What to remember"),
    title: str = typer.Option("", help="Note title (default: first line)"),
    folder: str = typer.Option("memories", help="Vault folder for the note"),
    tags: str = typer.Option("", help="Comma-separated tags"),
    vault: Optional[Path] = typer.Option(None),
):
    """Save a memory as a new Markdown note in the vault (indexed instantly)."""
    from ..ingestion.memory import save_memory

    eng = _engine(vault)
    tag_list = [t for t in (s.strip() for s in tags.split(",")) if t]
    path = save_memory(eng, content, title=title, folder=folder, tags=tag_list, client="cli")
    console.print(f"[green]saved[/green] {path}")
    for r in getattr(path, "related", []):
        flag = " [yellow](중복일 수 있음 · possible duplicate)[/yellow]" if r["near_duplicate"] else ""
        console.print(f"  [dim]관련 기억:[/dim] [[{r['title']}]] sim={r['sim']}{flag}")


@app.command("import-chats")
def import_chats(
    file: Path = typer.Argument(..., help="ChatGPT/Claude export conversations.json"),
    folder: str = typer.Option("chats", help="Vault folder for imported notes"),
    limit: Optional[int] = typer.Option(None, help="Import only the first N conversations"),
    vault: Optional[Path] = typer.Option(None),
):
    """Import a ChatGPT/Claude conversation export as vault notes (searchable,
    dated, idempotent — re-running on a newer export only adds new chats)."""
    from ..ingestion.chat_import import import_conversations

    eng = _engine(vault)
    written = import_conversations(eng, file, folder=folder, limit=limit)
    if written:
        console.print(f"[green]{len(written)}개 대화[/green]를 {folder}/ 에 저장하고 색인했습니다.")
    else:
        console.print("새로 추가된 대화가 없습니다 (이미 가져왔거나 빈 내보내기).")


@app.command()
def hook(
    agent: str = typer.Argument(..., help="Hook source: claude-code"),
    vault: Optional[Path] = typer.Option(None),
):
    """(internal) Lifecycle hook entry — reads the hook event JSON from stdin.
    Registered automatically by `lemory hooks install`."""
    from .hooks import run_hook

    if agent != "claude-code":
        raise typer.Exit(0)  # never break the host session
    raise typer.Exit(run_hook(_engine(vault)))


@app.command()
def hooks(
    action: str = typer.Argument(..., help="install | remove"),
    agent: str = typer.Argument("claude-code"),
    vault: Optional[Path] = typer.Option(None, help="Vault the captured memories go to"),
):
    """Automatic session memory: capture every Claude Code session's
    decisions/facts into the vault on SessionEnd (undo in the dashboard)."""
    from .hooks import install_claude_code, uninstall_claude_code

    if agent != "claude-code":
        console.print(f"[red]지원하지 않는 에이전트:[/red] {agent} (현재: claude-code)")
        raise typer.Exit(1)
    if action == "install":
        eng = _engine(vault)
        v = eng.cfg.resolved_vault()
        path = install_claude_code(v)
        console.print(f"[green]✔[/green] SessionEnd 훅 등록: {path}\n"
                      f"  이제 Claude Code 세션이 끝날 때마다 기억할 것들이 {v}/memories/sessions/ 에 저장됩니다.\n"
                      f"  대시보드 AI 메모리 피드에서 확인·되돌리기 가능합니다.")
    elif action == "remove":
        removed = uninstall_claude_code()
        console.print("[green]✔[/green] 훅 제거됨" if removed else "등록된 훅이 없습니다")
    else:
        console.print("[red]action은 install 또는 remove[/red]")
        raise typer.Exit(1)


@app.command()
def index(
    vault: Optional[Path] = typer.Option(None, help="Vault path (else lemory.toml / LEMORY_VAULT)"),
    full: bool = typer.Option(False, help="Re-chunk everything (embeddings still cached)"),
):
    """Index the vault incrementally."""
    eng = _engine(vault)
    plan = eng.index_plan(full=full)
    if plan.to_process or plan.to_remove:
        src = "실측 속도" if plan.rate_measured else "예상 속도"
        console.print(
            f"노트 {plan.to_process}개 처리 예정"
            + (f", {plan.to_remove}개 삭제" if plan.to_remove else "")
            + f" · 청크 {plan.chunks_total}개 (임베딩 필요 {plan.embeds_needed}개)"
            f" · 예상 시간: [bold]{plan.human_eta()}[/bold] ({src} {plan.rate_chunks_per_s:.0f}청크/s)"
        )
    else:
        console.print("변경 없음 — 색인이 이미 최신입니다.")
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
    hits = eng.search(query, k=k, mode=mode, expand=expand or None, rerank=rerank or None, record=True, client="cli")
    table = Table(show_lines=True)
    table.add_column("#", width=3)
    table.add_column("note")
    table.add_column("score", width=8)
    table.add_column("excerpt")
    for i, h in enumerate(hits, 1):
        sub = h.subheading()
        loc = h.title + (f" › {sub}" if sub else "")
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
    try:
        ans = eng.ask(question, k=k, record=True, client="cli")
    except RuntimeError as e:
        # keyless / local search-only mode: no generator. Degrade to search
        # instead of dumping a traceback — the evidence is still useful.
        console.print(f"[yellow]{e}[/yellow]\n")
        hits = eng.search(question, k=k)
        if hits:
            console.print("[bold]대신 가장 관련있는 노트를 보여드립니다 "
                          "(best-matching notes instead):[/bold]")
            for i, h in enumerate(hits, 1):
                sub = h.subheading()
                loc = h.title + (f" › {sub}" if sub else "")
                console.print(f"  {i}. [cyan]{loc}[/cyan] — "
                              + h.text[:140].replace("\n", " "))
        raise typer.Exit(1)
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
def mcp(vault: Optional[Path] = typer.Option(None),
        client: str = typer.Option("mcp", help="Name shown in the dashboard timeline (set per app: claude-desktop, cursor, ...)")):
    """Run as an MCP server (stdio) for Claude Desktop / Claude Code."""
    from .mcp import run_mcp

    run_mcp(_engine(vault), client=client)


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
