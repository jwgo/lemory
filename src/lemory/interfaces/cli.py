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

app = typer.Typer(
    help="Lemory — 당신의 마크다운을 위한 로컬 메모리 미들웨어 (local memory middleware for your Markdown).",
    invoke_without_command=True)
console = Console()


@app.callback(invoke_without_command=True)
def _welcome(ctx: typer.Context):
    """Bare `lemory` shows a short 'do this next' quickstart instead of the
    full command dump, so a first run is never a guessing game."""
    if ctx.invoked_subcommand is not None:
        return
    console.print("[bold]🍋 Lemory[/bold] — 로컬 메모리 미들웨어\n")
    if (Path.cwd() / "lemory.toml").exists():
        console.print(
            "설정이 있습니다. 바로 쓰세요:\n"
            "  [bold]lemory serve[/bold]           웹 UI + Obsidian/Claude 백엔드 → http://127.0.0.1:8377\n"
            "  [bold]lemory ask \"질문\"[/bold]        터미널에서 바로 질문\n"
            "  [bold]lemory doctor[/bold]           상태 점검\n")
    else:
        console.print(
            "처음이세요? [bold]이 한 줄이면 설정·색인·서버까지 전부[/bold] 됩니다:\n\n"
            "  [bold cyan]lemory up ~/내볼트경로[/bold cyan]\n\n"
            "  [dim]키 없이 로컬 임베딩으로 바로 검색돼요. 답변(ask)까지 원하면"
            " 대화형 [bold]lemory setup[/bold]에서 최고 로컬(온디바이스 Gemma 4)이나 Gemini 키를 고르세요.[/dim]\n")
    console.print("[dim]전체 명령: [bold]lemory --help[/bold][/dim]")

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
    """🍋 시작은 이것 하나 (config + index + serve 한 번에). 질문 안 물어봄:
    detect a key (env/.env/~/.lemory/env), pick the best available mode, write
    config, index, and serve.

    * Gemini key found        → full mode (answers + embeddings)
    * no key, fastembed there → local search-only mode
    * Gemini key found          → full mode (answers + cloud embeddings)
    * no key, Harrier installed  → local Harrier embeddings (best, keyless)
    * no key, fastembed (base)   → local e5-small-ko-v2 embeddings (keyless)
    * none of the above (rare)   → keyless mode (BM25 + link graph)
    """
    from ..config import _has_module, load_config

    v = vault.expanduser().resolve()
    if not v.is_dir():
        console.print(f"[red]폴더가 없습니다:[/red] {v}")
        raise typer.Exit(1)
    n_md = sum(1 for _ in v.rglob("*.md"))

    extra = ""
    if load_config().resolved_gemini_key():
        mode_desc = "Gemini (키 감지됨 — 질문·답변 포함)"
    elif _has_module("llama_cpp"):
        extra = 'provider = "local"\n'
        mode_desc = "로컬 Harrier 임베딩 (1024d, 키 없음)"
    elif _has_module("fastembed"):
        extra = 'provider = "local"\n'
        mode_desc = "로컬 e5-small-ko-v2 임베딩 (한국어 특화 384d, 키 없음 · Harrier는 pip install \"lemory[llama]\")"
    else:
        mode_desc = "키 없음 — BM25+링크 그래프 (pip install \"lemory[local]\"로 시맨틱 켜짐)"

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
    """One-shot setup: vault + embedding tier (API key optional) + first index.

    Semantic search works with no key at all (local embeddings ship by
    default); a key only adds AI answers (`ask`). Any key you do provide is
    stored in ~/.lemory/env (owner-only), so Obsidian/Claude/VS Code
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

    # 2. execution mode. Semantic embeddings already work out of the box
    # (fastembed ships as a base dependency), so the choice here is about
    # embedding quality + whether you also want AI answers (`ask`).
    extra_toml = ""
    if key is not None:
        mode = "3"  # explicit --key means Gemini mode
    else:
        console.print(
            "\n2) 어떻게 쓸까요?  [dim](검색·시맨틱 임베딩은 이미 로컬에서 기본 동작합니다)[/dim]\n"
            "   [bold]1[/bold]  ⭐ 최고 로컬 (완전 온디바이스, 추천) — Harrier 임베딩 + Qwen3 리랭커\n"
            "      + Gemma 4 로컬 답변, 전부 llama.cpp GPU 한 엔진. 키·데몬 0 [dim](lemory[llama])[/dim]\n"
            "   [bold]2[/bold]  가벼운 로컬 — e5-small-ko-v2(한국어 384d)만, 검색 전용 [dim](설치 최소·제로설정)[/dim]\n"
            "   [bold]3[/bold]  Gemini 무료 API — 임베딩+답변까지 클라우드 [dim](카드 불필요)[/dim]"
        )
        mode = typer.prompt("   선택", default="1").strip()

    if mode == "2":
        extra_toml = _setup_local("auto")
    elif mode == "3":
        existing = load_config().resolved_gemini_key()
        if key is None and existing:
            console.print("   [green]✔[/green] Gemini 키가 이미 설정되어 있습니다")
        else:
            k = key or typer.prompt("   Gemini API 키 (무료: https://aistudio.google.com)", hide_input=True)
            env_file = save_global_env({"GEMINI_API_KEY": k.strip()})
            console.print(f"   [green]✔[/green] 키 저장: {env_file} (권한 600)")
    else:
        extra_toml = _setup_best_local()

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


def _setup_best_local() -> str:
    """The recommended fully-on-device stack, no key and no daemon: Harrier
    all on one llama.cpp engine (Metal / CUDA / CPU offload): Harrier embeddings +
    Qwen3-Reranker + Gemma 4 local answers. Offers to pip-install `lemory[llama]`
    and turns the reranker on. Returns extra lemory.toml lines."""
    import subprocess
    import sys

    from ..config import _has_module

    ram = _machine_ram_gb()
    if not _has_module("llama_cpp"):
        console.print(
            "   최고 로컬 스택엔 [bold]lemory[llama][/bold] 가 필요합니다 "
            "[dim](Harrier ~640MB · Qwen3-Reranker ~600MB · Gemma 4 답변 모델은 첫 사용 때 자동 다운로드)[/dim]")
        if typer.confirm("   지금 설치할까요?", default=True):
            with console.status("설치 중... (llama-cpp-python 빌드에 몇 분 걸릴 수 있어요)"):
                r = subprocess.run([sys.executable, "-m", "pip", "install", "lemory[llama]"])
            if r.returncode != 0:
                console.print('   [yellow]![/yellow] 설치 실패 — 수동으로: pip install "lemory[llama]"')
        else:
            console.print('   나중에: [bold]pip install "lemory[llama]"[/bold]')

    backend = "llamacpp" if _has_module("llama_cpp") else "auto"
    if backend == "llamacpp":
        console.print("   [green]✔[/green] Harrier-0.6B (1024d) 임베딩 — 데몬 없이 프로세스 안 Metal/GPU (doc@8 0.853)")
    else:
        console.print("   [green]✔[/green] e5-small-ko-v2 (한국어 384d) 임베딩 [dim](llama-cpp-python 설치되면 Harrier로 자동 전환)[/dim]")
    console.print("   [green]✔[/green] Qwen3-Reranker-0.6B + Gemma 4 E4B 로컬 답변 — 전부 같은 llama.cpp 엔진(GPU), 키·데몬 0")
    if 0 < ram < 8:
        console.print(f"   [yellow]⚠ RAM {ram:.0f}GB — Gemma 4 E4B 답변은 8GB+ 권장. 웹 콘솔에서 E2B로 낮출 수 있어요.[/yellow]")
    return f'provider = "local"\nlocal_embed_backend = "{backend}"\nreranker = true\n'


def _setup_local(backend: str) -> str:
    """Local-embeddings mode. backend='auto' keeps the default (Harrier if
    lemory[llama] is installed, else e5-small-ko-v2); 'llamacpp' asks for Harrier
    explicitly. Returns extra lemory.toml lines."""
    from ..config import _has_module

    if backend == "llamacpp":
        if not _has_module("llama_cpp"):
            console.print(
                "   [yellow]![/yellow] Harrier는 llama-cpp-python이 필요합니다. 설치 후 다시:\n"
                "     [bold]pip install \"lemory[llama]\"[/bold]  →  [bold]lemory setup[/bold]\n"
                "   [dim](지금은 경량 e5-small-ko-v2로 계속합니다 — 나중에 위 명령이면 자동 전환)[/dim]"
            )
            backend = "auto"
        else:
            console.print("   [green]✔[/green] Harrier-0.6B (1024d) — 첫 색인 때 GGUF ~640MB 자동 다운로드")
            console.print("   [dim]데몬 없이 프로세스 안에서 Metal/GPU로 실행됩니다.[/dim]")
            return 'provider = "local"\nlocal_embed_backend = "llamacpp"\n'

    # auto / default: fastembed is a base dependency, so this always works
    if _has_module("llama_cpp"):
        console.print("   [green]✔[/green] Harrier-0.6B (1024d) 감지 — 로컬 고품질 임베딩 사용")
    elif _has_module("fastembed"):
        console.print("   [green]✔[/green] e5-small-ko-v2 (한국어 특화 384d) — 첫 색인 때 모델 자동 다운로드")
        console.print("   [dim]한국어 검색을 더 올리려면: pip install \"lemory[llama]\" (Harrier 1024d)[/dim]")
    console.print("   [dim]검색·색인·콘솔은 전부 로컬로 됩니다. ask(답변)은 최고 로컬(모드 1·온디바이스 Gemma 4)이나 Gemini 키로.[/dim]")
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
        model = cfg.active_embed_model()
        tier = ("Harrier 1024d · 로컬 고품질" if "harrier" in model.lower()
                else "e5-small-ko 384d · 로컬 경량" if "e5" in model.lower() or "minilm" in model.lower() or "multilingual" in model.lower()
                else f"{model} · 클라우드" if provider in ("gemini", "openai")
                else model)
        check("provider", True, f"{provider}  ({tier})")
        try:
            eng = _engine(vault)
            vec = eng.llm.embed(["lemory doctor ping"])
            ok &= check("시맨틱 임베딩", vec.shape[-1] == cfg.active_embed_dim(),
                        f"@{vec.shape[-1]}d 동작 확인")
        except Exception as e:
            ok = check("시맨틱 임베딩", False, str(e)[:120])
        # answers (ask) need a generator: a cloud key, or on-device Gemma 4
        # (llama.cpp) in the local tier — embeddings alone do not answer
        from ..providers import gemma
        local_brain = provider == "local" and gemma.available()[0]
        ask_ok = provider in ("gemini", "openai") or local_brain or bool(
            cfg.resolved_gemini_key() or cfg.resolved_openai_key())
        if ask_ok:
            detail = "Gemma 4 온디바이스" if local_brain and not (
                cfg.resolved_gemini_key() or cfg.resolved_openai_key()) else "사용 가능"
            check("답변 생성 (ask)", True, detail)
        else:
            console.print(' [yellow]⚠[/yellow] 답변 생성 (ask) — 검색은 되지만 ask는 답변 모델이 필요합니다: '
                          '온디바이스 Gemma 4(pip install "lemory[llama]") 또는 GEMINI_API_KEY(무료)')
        # upgrade hint: on the light local tier, Harrier is a keyless win
        if "e5" in model.lower() or "minilm" in model.lower() or "multilingual" in model.lower():
            console.print(" [dim]↑ 한국어 검색 품질을 더 올리려면: pip install \"lemory[llama]\" "
                          "(Harrier 1024d, 데몬 없음) 후 lemory index[/dim]")
    except RuntimeError:
        console.print(
            " [yellow]⚠[/yellow] provider — 로컬 임베더 없음(희귀): 렉시컬 모드로 동작 중 "
            "(BM25+링크 그래프). 시맨틱 검색을 켜려면 [bold]pip install \"lemory[local]\"[/bold] "
            "(또는 [bold]lemory[llama][/bold]) 후 다음 색인에서 자동 활성화")

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


@app.command("suggest-links")
def suggest_links_cmd(
    note: Optional[str] = typer.Argument(None, help="Vault-relative note path (omit for vault-wide top suggestions)"),
    k: int = typer.Option(12, help="Max suggestions"),
    vault: Optional[Path] = typer.Option(None),
):
    """Unlinked mentions as [[link]] suggestions — notes that reference each
    other in text but were never linked. Zero LLM; reads the existing graph."""
    from ..retrieval.links import suggest_links

    eng = _engine(vault)
    eng.index()
    try:
        rows = suggest_links(eng, path=note, k=k)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    if not rows:
        console.print("[dim]제안할 링크가 없습니다 — 언급되지만 연결 안 된 노트가 없어요.[/dim]")
        return
    table = Table(title=f"link suggestions ({len(rows)})")
    table.add_column("from")
    table.add_column("add link")
    table.add_column("mention context")
    for r in rows:
        table.add_row(r["from_title"], r["suggestion"], r["snippet"][:80])
    console.print(table)


@app.command("graph")
def graph_cmd(
    out: Path = typer.Option(Path("graph.html"), help="Output HTML file"),
    vault: Optional[Path] = typer.Option(None),
    open_after: bool = typer.Option(False, "--open", help="Open in the default browser"),
):
    """볼트 지식그래프를 자체완결 인터랙티브 HTML 한 파일로 내보낸다.

    LLM 0회 — 위키링크·멘션 그래프는 인덱스에 이미 있다. Graphify류가
    LLM 파이프라인으로 몇 분 걸려 만드는 graph.html을 밀리초에 만든다."""
    from .graph_html import render_graph_html

    eng = _engine(vault)
    eng.index()
    html = render_graph_html(eng)
    out = out.expanduser()
    out.write_text(html, encoding="utf-8")
    st = eng.status()
    console.print(f"[green]✔[/green] {out}  ({st['documents']} notes, {st['links']} links)")
    if open_after:
        import webbrowser

        webbrowser.open(out.resolve().as_uri())


@app.command("skill")
def skill_cmd(
    action: str = typer.Argument(..., help="install | show"),
    assistant: str = typer.Argument("claude-code", help="claude-code | codex | cursor"),
    vault: Optional[Path] = typer.Option(None),
    global_install: bool = typer.Option(False, "--global", help="Install to the user-level skills dir"),
):
    """AI 어시스턴트에 Lemory 스킬을 설치한다 (Graphify/qmd 스타일 원커맨드).

    스킬은 어시스턴트에게 lemory CLI/MCP 사용법(검색 연산자, 기억 저장
    에티켓, 링크 제안)을 가르치는 마크다운 — 설치 후 어시스턴트가 볼트를
    기억처럼 다룬다."""
    from .skills import render_skill, skill_target

    if action not in ("install", "show"):
        console.print(f"[red]알 수 없는 동작:[/red] {action} (install | show)")
        raise typer.Exit(2)
    eng = _engine(vault)
    v = str(eng.cfg.resolved_vault())
    content = render_skill(assistant, v)
    if action == "show":
        console.print(content)
        return
    target = skill_target(assistant, Path.cwd(), global_install)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    console.print(f"[green]✔[/green] skill installed: {target}")
    if assistant == "claude-code":
        console.print("  Claude Code가 다음 세션부터 자동으로 로드합니다.")


@app.command("drift")
def drift_cmd(
    vault: Optional[Path] = typer.Option(None),
    as_prompt: bool = typer.Option(False, "--prompt", help="에이전트용 수리 프롬프트로 출력"),
):
    """볼트의 기억이 현실과 어긋난 곳을 찾는다 (드리프트 감지, LLM 0회).

    깨진 [[위키링크]], 존재하지 않는 파일로 가는 링크, 해소되지 않은
    중복 플래그. --prompt는 발견 사항을 그대로 고치라는 에이전트용
    프롬프트로 렌더링한다 (mex 스타일 sync, 볼트 판)."""
    from ..retrieval.drift import detect_drift, render_repair_prompt

    eng = _engine(vault)
    eng.index()
    findings = detect_drift(eng)
    if as_prompt:
        console.print(render_repair_prompt(findings, str(eng.cfg.resolved_vault())))
        return
    total = sum(len(v) for k, v in findings.items() if isinstance(v, list))
    if total == 0:
        console.print(f"[green]✔ 드리프트 없음[/green] — 노트 {findings['notes_scanned']}개 검사")
        return
    for kind, label in (("broken_wikilinks", "깨진 위키링크"),
                        ("missing_file_links", "없는 파일로 가는 링크"),
                        ("unresolved_duplicates", "미해소 중복 플래그")):
        rows = findings[kind]
        if not rows:
            continue
        table = Table(title=f"{label} ({len(rows)})")
        table.add_column("note")
        table.add_column("target")
        for r in rows[:20]:
            table.add_row(r["note"], r.get("target", r.get("duplicate_of", "")))
        console.print(table)
    console.print("[dim]고치려면: lemory drift --prompt | (에이전트에 전달)[/dim]")


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
    """서버만 실행 (웹 UI + Obsidian/Claude 백엔드). 이미 색인돼 있을 때 씀 —
    처음이면 대신 `lemory up`. Run the HTTP API + vault watcher."""
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
