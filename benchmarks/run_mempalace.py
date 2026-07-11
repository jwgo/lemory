"""External competitor: MemPalace (57k stars, Apr 2026) on the multi-hop vault.

Configuration = its own marketing headline: `sqlite_exact` backend + the
bundled local embeddinggemma ONNX — "zero API calls", verbatim storage.
The vault is mined with its own CLI (`mempalace mine`); queries go through
`mempalace search --results 8`, and the metric checks whether the gold
answer string appears anywhere in the CLI output an agent would consume —
the same answer-in-context contract as the mem0/cognee/supermemory runs
(generous: the formatted output includes drawer metadata beyond raw chunks).

Also runs the §4d robustness variants (paraphrase / Korean / keyword / typo)
— MemPalace has no Korean-specific lexical path, which is exactly the flank
this measures.

Run:  python benchmarks/run_mempalace.py [--palace DIR]
      (mine once: MEMPALACE_BACKEND=sqlite_exact mempalace --palace DIR mine
       benchmarks/data/multihop/vault --no-gitignore)
"""

from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import DATA, WORK, answer_in_text, save_json  # noqa: E402

MP = Path(sys.executable).parent / "mempalace"
K = 8


def search(palace: str, query: str) -> tuple[str, float]:
    t0 = time.time()
    out = subprocess.run(
        [str(MP), "--palace", palace, "search", query, "--results", str(K)],
        capture_output=True, text=True, timeout=180,
        env={**os.environ, "MEMPALACE_BACKEND": "sqlite_exact"},
    )
    return out.stdout, time.time() - t0


def main() -> None:
    palace = sys.argv[sys.argv.index("--palace") + 1] if "--palace" in sys.argv \
        else str(WORK / "mempalace-palace")

    questions = json.loads((DATA / "multihop" / "questions.json").read_text())
    aic, by_hops, lat = [], {1: [], 2: []}, []
    for i, q in enumerate(questions):
        text, dt = search(palace, q["q"])
        lat.append(dt)
        ok = answer_in_text(text, q["answers"])
        aic.append(ok)
        by_hops[q["hops"]].append(ok)
        if (i + 1) % 10 == 0:
            print(f"multihop {i+1}/{len(questions)} — running aic {sum(aic)/len(aic):.3f}")

    result = {
        "answer_in_context@8": sum(aic) / len(aic),
        "aic_1hop": sum(by_hops[1]) / max(1, len(by_hops[1])),
        "aic_2hop": sum(by_hops[2]) / max(1, len(by_hops[2])),
        "p50_latency_ms": statistics.median(lat) * 1000,
        "latency_note": "CLI wall-clock incl. process startup — see docs note",
    }
    print("mempalace multihop:", json.dumps(result, indent=2))

    robust_file = DATA / "multihop" / "robust_queries.json"
    if robust_file.exists():
        variants = json.loads(robust_file.read_text())  # {orig_q: {kind: variant}}
        answers_by_q = {q["q"]: q["answers"] for q in questions}
        rob: dict[str, list[bool]] = {"original": aic}
        for i, (orig, kinds) in enumerate(variants.items()):
            answers = answers_by_q.get(orig)
            if not answers:
                continue
            for kind, qtext in kinds.items():
                text, _ = search(palace, qtext)
                rob.setdefault(kind, []).append(answer_in_text(text, answers))
            if (i + 1) % 10 == 0:
                print(f"robustness {i+1}/{len(variants)}")
        result["robustness"] = {k: sum(v) / len(v) for k, v in rob.items()}
        print("mempalace robustness:", result["robustness"])

    save_json(WORK / "results_mempalace.json", result)


if __name__ == "__main__":
    main()
