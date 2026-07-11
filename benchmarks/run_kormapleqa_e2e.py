"""KorMapleQA e2e: ask()가 실제로 정답을 생성하는가 (+ 무응답 행동).

층화 샘플(기본 유형당 25 + 무응답 전부)에 대해 Gemini 생성기로 답을 만들고
containment-EM / token-F1 로 채점한다. 무응답 문항은 '모른다'류 응답이
정답 — 환각(그럴듯한 오답)을 별도 카운트한다.

    python benchmarks/run_kormapleqa_e2e.py [per_type]
"""

from __future__ import annotations

import json
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import DATA, WORK, best_f1, load_env, make_engine, normalize_answer, save_json

QFILE = DATA / "kormapleqa" / "questions.jsonl"
SEED = 20260711

_IDK = ("모른", "몰라", "없습니다", "없어", "찾을 수 없", "알 수 없", "정보가 없",
        "나와 있지 않", "확인할 수 없", "don't know", "not found", "no information")


def is_abstain(text: str) -> bool:
    t = text.strip().lower()
    return any(k in t for k in _IDK)


def main() -> None:
    load_env()
    per_type = int(sys.argv[1]) if len(sys.argv) > 1 else 25
    rows = [json.loads(l) for l in QFILE.read_text().splitlines()]
    answerable = [q for q in rows if q.get("answerable", True)]
    abstention = [q for q in rows if not q.get("answerable", True)]

    rng = random.Random(SEED)
    by_type = defaultdict(list)
    for q in answerable:
        by_type[q["type"]].append(q)
    sample = [q for t, qs in sorted(by_type.items())
              for q in rng.sample(qs, min(per_type, len(qs)))]

    eng = make_engine(DATA / "maple_real" / "vault", tag="maple_real")
    eng.index()

    per_t = defaultdict(lambda: {"em": 0, "f1": 0.0, "n": 0})
    lat = []
    for i, q in enumerate(sample):
        t0 = time.time()
        try:
            ans = eng.ask(q["q"], k=8)
        except Exception as e:
            print(f"  {q['id']} failed: {str(e)[:100]}", flush=True)
            continue
        lat.append(time.time() - t0)
        pred = ans.text
        em = float(normalize_answer(q["answers"][0]) in normalize_answer(pred))
        f1 = best_f1(pred, q["answers"])
        st = per_t[q["type"]]
        st["em"] += em; st["f1"] += f1; st["n"] += 1
        if (i + 1) % 20 == 0:
            done = sum(v["n"] for v in per_t.values())
            em_all = sum(v["em"] for v in per_t.values()) / max(1, done)
            print(f"{done}/{len(sample)} — running EM {em_all:.3f}", flush=True)

    abst_ok = halluc = 0
    abst_rows = []
    for q in abstention:
        try:
            ans = eng.ask(q["q"], k=8)
        except Exception:
            continue
        ok = is_abstain(ans.text)
        abst_ok += ok
        halluc += (not ok)
        abst_rows.append({"q": q["q"], "abstained": ok, "answer": ans.text[:160]})

    out = {"n": sum(v["n"] for v in per_t.values())}
    out["em"] = round(sum(v["em"] for v in per_t.values()) / max(1, out["n"]), 4)
    out["f1"] = round(sum(v["f1"] for v in per_t.values()) / max(1, out["n"]), 4)
    for t, v in sorted(per_t.items()):
        out[f"{t}_em"] = round(v["em"] / max(1, v["n"]), 4)
        out[f"{t}_f1"] = round(v["f1"] / max(1, v["n"]), 4)
    lat.sort()
    out["p50_s"] = round(lat[len(lat) // 2], 2) if lat else None
    out["abstention"] = {"n": len(abst_rows), "abstained": abst_ok,
                         "hallucinated": halluc, "rows": abst_rows}
    print(json.dumps({k: v for k, v in out.items() if k != "abstention"},
                     indent=2, ensure_ascii=False))
    print("abstention:", abst_ok, "/", len(abst_rows), "correct refusals")
    save_json(WORK / "results_kormapleqa_e2e.json", out)


if __name__ == "__main__":
    main()
