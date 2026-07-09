"""qmd (tobi/qmd) head-to-head on the multihop vault.

qmd is the local-model markdown search CLI Lemory gets compared against for
convenience. Same corpus, same questions, same metric (full-support@8 by gold
note). Three qmd modes:

  query    full pipeline (LLM query expansion + rerank) — its headline mode
  vsearch  vector-only (embeddinggemma-300M local)
  search   BM25 only

Latency caveat recorded in results: qmd runs its models on this machine's CPU
(no GPU in the benchmark container); on GPU hardware its latency is lower.
Checkpointed per (mode, question) in preds.jsonl.

    python benchmarks/run_qmd.py search vsearch     # fast modes (+variants)
    python benchmarks/run_qmd.py query              # full pipeline (slow)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import DATA, WORK, save_json

OUT = WORK / "qmd"
K = 8
QMD_ENV = {
    **os.environ,
    # node's fetch must ride the environment proxy for qmd's model checks
    "NODE_OPTIONS": os.environ.get("QMD_NODE_OPTIONS", os.environ.get("NODE_OPTIONS", "")),
}

_JSON_RE = re.compile(r"(\[\s*\{.*\}\s*\]|\[\s*\])", re.S)


def norm_title(s: str) -> str:
    return re.sub(r"[\s\-_]+", " ", s.lower()).strip()


def qmd_query(mode: str, q: str, k: int = K, timeout: int = 600) -> tuple[list[str], float]:
    """Returns (unique note titles in rank order, seconds)."""
    t0 = time.time()
    proc = subprocess.run(
        ["qmd", mode, "--json", q, "-n", str(k * 2)],
        capture_output=True, text=True, timeout=timeout, env=QMD_ENV,
    )
    dt = time.time() - t0
    m = _JSON_RE.search(proc.stdout)
    if not m:
        raise RuntimeError(f"no JSON in qmd output (rc={proc.returncode}): {proc.stdout[-200:]}")
    rows = json.loads(m.group(1))
    titles: list[str] = []
    for r in rows:
        f = str(r.get("file", ""))
        title = norm_title(Path(f.split("://")[-1]).stem)
        if title and title not in titles:
            titles.append(title)
    return titles, dt


def load_state() -> dict:
    state = {}
    f = OUT / "preds.jsonl"
    if f.exists():
        for line in f.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                state[(r["mode"], r["kind"], r["q"])] = r
    return state


def main(modes: list[str]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    questions = json.loads((DATA / "multihop" / "questions.json").read_text())
    variants = json.loads((DATA / "multihop" / "robust_queries.json").read_text())
    state = load_state()

    for mode in modes:
        # full pipeline only on originals (CPU cost); fast modes get variants too
        kinds = ["original"] if mode == "query" else ["original", "paraphrase", "korean", "keyword", "typo"]
        for q in questions:
            qmap = {"original": q["q"], **variants.get(q["q"], {})}
            for kind in kinds:
                text = qmap.get(kind)
                if not text or (mode, kind, q["q"]) in state:
                    continue
                try:
                    titles, dt = qmd_query(mode, text)
                except Exception as e:
                    print(f"  {mode}/{kind} failed: {str(e)[:120]}", flush=True)
                    continue
                gold = {norm_title(g) for g in q["gold_notes"]}
                row = {
                    "mode": mode, "kind": kind, "q": q["q"], "text": text,
                    "full_support": int(gold <= set(titles[:K])), "seconds": dt,
                    "hops": q["hops"],
                }
                with open(OUT / "preds.jsonl", "a") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                state[(mode, kind, q["q"])] = row
            done = [state[k] for k in state if k[0] == mode and k[1] == "original"]
            if done and len(done) % 10 == 0:
                fs = sum(r["full_support"] for r in done) / len(done)
                print(f"{mode}: {len(done)}/57 originals, full_support {fs:.3f}", flush=True)

    results = {}
    for mode in ("query", "vsearch", "search"):
        rows = [state[k] for k in state if k[0] == mode]
        if not rows:
            continue
        summary = {}
        for kind in ("original", "paraphrase", "korean", "keyword", "typo"):
            sub = [r for r in rows if r["kind"] == kind]
            if sub:
                summary[f"full_support@8_{kind}"] = sum(r["full_support"] for r in sub) / len(sub)
        two = [r for r in rows if r["kind"] == "original" and r["hops"] == 2]
        if two:
            summary["full_support@8_2hop"] = sum(r["full_support"] for r in two) / len(two)
        lat = sorted(r["seconds"] for r in rows)
        summary["p50_latency_s"] = lat[len(lat) // 2]
        results[mode] = summary
        print(mode, json.dumps(summary, indent=1))
    save_json(WORK / "results_qmd.json", results)


if __name__ == "__main__":
    main([a for a in sys.argv[1:] if not a.startswith("-")] or ["search", "vsearch"])
