"""External competitor: supermemory (hosted API).

Two comparisons, same protocols as the other external systems:

  python run_supermemory.py multihop   # answer-in-context@8 on LemoryBench
  python run_supermemory.py locomo     # judged QA on the LOCOMO sample
                                       # (appends system=supermemory rows to
                                       #  the shared preds.jsonl checkpoint)

Documents are ingested once per corpus (state tracked locally); supermemory
processes asynchronously, so ingestion waits for indexing to settle before
searching. Retrieval uses its hosted /v3/search; answer generation and the
LLM judge are identical to every other system's run.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from common import DATA, WORK, answer_in_text, load_env, save_json

API = "https://api.supermemory.ai/v3"
K = 8


class Supermemory:
    def __init__(self, api_key: str):
        self.http = httpx.Client(
            timeout=60,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )

    def _post(self, path: str, payload: dict, tries: int = 5) -> dict:
        last = None
        for attempt in range(tries):
            try:
                r = self.http.post(f"{API}{path}", json=payload)
            except httpx.HTTPError as e:
                last = e
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 200:
                return r.json()
            last = RuntimeError(f"{r.status_code}: {r.text[:200]}")
            if r.status_code in (429, 500, 502, 503):
                time.sleep(min(2 ** attempt * 2, 30))
                continue
            raise last
        raise RuntimeError(f"supermemory request failed: {last}")

    def add(self, content: str, tag: str, title: str) -> str:
        d = self._post("/documents", {
            "content": content,
            "containerTag": tag,
            "metadata": {"title": title},
        })
        return d.get("id", "")

    def count(self, tag: str) -> tuple[int, int]:
        """(total docs, docs still processing) for a container tag."""
        d = self._post("/documents/list", {"containerTags": [tag], "limit": 200})
        docs = d.get("memories", d.get("documents", []))
        pending = sum(1 for x in docs if x.get("status") not in ("done", "completed", "success", None))
        return len(docs), pending

    def search(self, q: str, tag: str, limit: int = K) -> list[str]:
        d = self._post("/search", {"q": q, "containerTags": [tag], "limit": limit})
        texts: list[str] = []
        for res in d.get("results", []):
            chunks = res.get("chunks") or []
            got = [c.get("content", "") for c in chunks if c.get("content")]
            if not got and res.get("content"):
                got = [res["content"]]
            if got:
                texts.append("\n".join(got))
        return texts[:limit]


def ingest_corpus(sm: Supermemory, files: list[tuple[str, str, str]], state_file: Path) -> None:
    """files: (tag, title, content). Skips already-ingested titles."""
    done = set(json.loads(state_file.read_text())) if state_file.exists() else set()
    todo = [(t, ti, c) for t, ti, c in files if f"{t}/{ti}" not in done]
    for i, (tag, title, content) in enumerate(todo):
        sm.add(content, tag, title)
        done.add(f"{tag}/{title}")
        state_file.write_text(json.dumps(sorted(done)))
        if (i + 1) % 20 == 0:
            print(f"ingested {i+1}/{len(todo)}")
        time.sleep(0.35)
    if todo:
        print(f"ingested {len(todo)} docs; waiting for processing to settle...")
        for _ in range(30):
            time.sleep(10)
            tags = {t for t, _, _ in files}
            pending = sum(sm.count(t)[1] for t in tags)
            if pending == 0:
                break
            print(f"  {pending} docs still processing")


def bench_multihop(sm: Supermemory) -> None:
    vault = DATA / "multihop" / "vault"
    files = [("lemorybench", f.stem, f.read_text(encoding="utf-8")) for f in sorted(vault.glob("*.md"))]
    ingest_corpus(sm, files, WORK / "supermemory_multihop_ingested.json")

    questions = json.loads((DATA / "multihop" / "questions.json").read_text())
    flags, by_hops, latencies = [], {1: [], 2: []}, []
    for i, q in enumerate(questions):
        t = time.time()
        texts = sm.search(q["q"], "lemorybench", K)
        latencies.append(time.time() - t)
        ok = any(answer_in_text(t_, q["answers"]) for t_ in texts)
        flags.append(ok)
        by_hops[q["hops"]].append(ok)
        if (i + 1) % 10 == 0:
            print(f"search {i+1}/{len(questions)} aic so far {sum(flags)/len(flags):.3f}")
        time.sleep(0.3)
    out = {
        "answer_in_context@8": sum(flags) / len(flags),
        "aic_1hop": sum(by_hops[1]) / max(1, len(by_hops[1])),
        "aic_2hop": sum(by_hops[2]) / max(1, len(by_hops[2])),
        "p50_latency_ms": sorted(latencies)[len(latencies) // 2] * 1000,
    }
    print("supermemory multihop:", out)
    save_json(WORK / "results_supermemory.json", out)


def bench_locomo(sm: Supermemory) -> None:
    from run_locomo import GEN_SYSTEM, JUDGE_PROMPT, GEN_MODEL, OUT, append_state, load_state, turn_texts

    from lemory.providers.gemini import GeminiClient

    eval_set = json.loads((OUT / "eval_set.json").read_text())
    vaults = OUT / "vaults"
    files = []
    for conv_dir in sorted(vaults.glob("conv*")):
        tag = f"locomo-{conv_dir.name}"
        for f in sorted(conv_dir.glob("*.md")):
            files.append((tag, f.stem, f.read_text(encoding="utf-8")))
    ingest_corpus(sm, files, WORK / "supermemory_locomo_ingested.json")

    llm = GeminiClient(api_key=os.environ["GEMINI_API_KEY"], llm_model=GEN_MODEL,
                       llm_fallback_model="gemini-2.5-flash", llm_rpm=12)
    state = load_state()
    for q in eval_set:
        key = ("supermemory", q["conv"], q["q"])
        if key in state:
            continue
        texts = sm.search(q["q"], f"locomo-conv{q['conv']}", 10)
        ev_texts = turn_texts(q["conv"], q["evidence"])
        joined = " ".join(texts).lower()
        ev_found = sum(1 for t in ev_texts if t.lower() in joined)
        ctx = "\n\n".join(f"[{i+1}] {t[:1500]}" for i, t in enumerate(texts))[:12000]
        pred = llm.generate(
            f"NOTES:\n{ctx}\n\nQUESTION: {q['q']}\n\nANSWER:", system=GEN_SYSTEM,
            temperature=0.0, max_output_tokens=64,
        ).strip()
        verdict = llm.generate(
            JUDGE_PROMPT.format(q=q["q"], gold=q["answer"], pred=pred),
            temperature=0.0, max_output_tokens=8,
        ).strip().lower()
        row = {
            "system": "supermemory", "conv": q["conv"], "q": q["q"],
            "category": q["category"], "gold": q["answer"], "pred": pred,
            "judge": 1 if verdict.startswith("yes") else 0,
            "ev_found": ev_found, "ev_total": len(ev_texts),
        }
        append_state(row)
        state[key] = row
        n = sum(1 for k in state if k[0] == "supermemory")
        if n % 10 == 0:
            rows = [state[k] for k in state if k[0] == "supermemory"]
            print(f"supermemory: {n}/{len(eval_set)} judge-acc {sum(r['judge'] for r in rows)/len(rows):.3f}", flush=True)


if __name__ == "__main__":
    load_env()
    sm = Supermemory(os.environ["SUPERMEMORY_API_KEY"])
    which = sys.argv[1] if len(sys.argv) > 1 else "multihop"
    if which == "multihop":
        bench_multihop(sm)
    else:
        bench_locomo(sm)
