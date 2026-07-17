"""Trending 2026 memory challengers on the Korean harness (recon batch).

Each is a runnable-offline adapter over the shared KorQuAD harness. Everything
labeled with the EXACT mode run — where a tool needs a model we don't have
locally (Ollama), we run its documented offline fallback and say so.

Reproduce (both competitors are optional; a missing one is recorded as an error
row, the run still completes):
    # EchoVault (Python) — offline FTS5 fallback (its vector path needs Ollama)
    uv pip install "git+https://github.com/mraza007/echovault@v0.5.0"
    # Vestige (Rust MCP binary) — its default nomic embedder is downloaded once
    npm install -g vestige-mcp-server     # or drop the binary under /tmp/vestige-pkg
    python benchmarks/run_challengers_korean.py [n]

Honesty notes are in each adapter's docstring and docs/COMPETITIVE.md.

Run:  python benchmarks/run_challengers_korean.py [n]
"""
from __future__ import annotations

import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent))
from harness_korean import bench, load_korquad, run_lemory  # noqa: E402


def run_echovault_fts(corpus, questions, gold):
    """EchoVault v0.5 (github mraza007/echovault, ~146★). OFFLINE mode: no
    Ollama → its documented FTS-only fallback (use_vectors=False). Its
    Ollama-semantic path uses nomic-embed (English-centric), not run here."""
    import tempfile
    from memory.core import MemoryService
    from memory.models import RawMemoryInput

    home = tempfile.mkdtemp()
    svc = MemoryService(memory_home=home)
    # title carries the paragraph index so we can map a hit back to gold
    for i, ctx in enumerate(corpus):
        svc.save(RawMemoryInput(title=f"P{i:04d}", what=ctx), project="bench")
    hit, lat = 0, []
    for q, g in zip(questions, gold):
        t = time.perf_counter()
        res = svc.search(q, limit=1, use_vectors=False, record_feedback=False)
        lat.append(time.perf_counter() - t)
        if res:
            title = (res[0].get("title") or res[0].get("name") or "")
            body = str(res[0])
            if f"P{g:04d}" in title or f"P{g:04d}" in body:
                hit += 1
    return hit / len(questions), sorted(lat)[len(lat) // 2] * 1000


def _find_vestige():
    for c in (
        Path("/tmp/vestige-pkg/package/bin/vestige-mcp"),
        Path.home() / ".npm-global/lib/node_modules/vestige-mcp-server/bin/vestige-mcp",
    ):
        if c.exists():
            return str(c)
    return None


def run_vestige(corpus, questions, gold):
    """Vestige v2.2.1 (github samvallad33/vestige, npm vestige-mcp-server, FSRS
    cognitive memory). Driven over its own MCP stdio transport — the exact
    interface a Claude/Codex user gets. Ingests one node per paragraph
    (forceCreate, tag=p####), recalls mode='lookup' (its "hybrid: keyword +
    semantic + convex fusion"). Its embedder is ACTIVATED: Vestige generates
    embeddings lazily inside its consolidate cycle, so we run maintain/
    consolidate after ingest — this is the fully-embedded best case, not a
    keyword-only degrade. Default embedder is nomic-embed-text-v1.5 (English-
    first, same class as memvid's default), downloaded once to
    ~/.cache/vestige/fastembed. So this measures Vestige's real Korean gap with
    semantics on, not a missing model. min_similarity=0 gives it every hit."""
    import json as _json
    import subprocess
    import tempfile

    binp = _find_vestige()
    if not binp:
        raise RuntimeError("vestige-mcp binary not present (npm i -g vestige-mcp-server)")
    env = dict(**__import__("os").environ, VESTIGE_DATA_DIR=tempfile.mkdtemp(),
               VESTIGE_EMBEDDING_MODEL="nomic")
    p = subprocess.Popen([binp], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, text=True, bufsize=1, env=env)
    _id = [0]

    def call(method, params=None, notify=False):
        if notify:
            p.stdin.write(_json.dumps({"jsonrpc": "2.0", "method": method, "params": params or {}}) + "\n")
            p.stdin.flush(); return None
        _id[0] += 1; i = _id[0]
        p.stdin.write(_json.dumps({"jsonrpc": "2.0", "id": i, "method": method, "params": params or {}}) + "\n")
        p.stdin.flush()
        while True:
            line = p.stdout.readline()
            if not line:
                return None
            o = _json.loads(line)
            if o.get("id") == i:
                return o

    def tool(name, args):
        return call("tools/call", {"name": name, "arguments": args})

    try:
        call("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                            "clientInfo": {"name": "bench", "version": "1"}})
        call("notifications/initialized", notify=True)
        for i, ctx in enumerate(corpus):
            tool("smart_ingest", {"content": ctx, "forceCreate": True,
                                  "tags": [f"p{i:04d}"], "node_type": "note"})
        # generate embeddings (lazy — happens in the consolidate cycle)
        tool("maintain", {"action": "consolidate"})
        hit, lat = 0, []
        for q, g in zip(questions, gold):
            t = time.perf_counter()
            r = tool("recall", {"query": q, "mode": "lookup", "limit": 1,
                                "detail_level": "brief", "min_similarity": 0.0})
            lat.append(time.perf_counter() - t)
            res = (r or {}).get("result", {}).get("structuredContent", {}).get("results", [])
            if res and f"p{g:04d}" in (res[0].get("tags") or []):
                hit += 1
        return hit / len(questions), sorted(lat)[len(lat) // 2] * 1000
    finally:
        p.terminate()


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 120
    corpus, questions, gold = load_korquad(n, cap=None)
    print(f"corpus={len(corpus)} paragraphs · {len(questions)} Korean questions "
          f"· recall@1, both fully local\n")
    rows = []
    rows.append(bench("Lemory keyless (e5-ko, hybrid)", run_lemory, corpus, questions, gold))
    rows.append(bench("EchoVault v0.5 (offline FTS5)", run_echovault_fts, corpus, questions, gold))
    rows.append(bench("Vestige v2.2.1 (MCP, offline)", run_vestige, corpus, questions, gold))
    import json
    (Path(__file__).parent / "work" / "results_challengers_korean.json").write_text(
        json.dumps({"n": n, "corpus": len(corpus), "rows": rows}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
