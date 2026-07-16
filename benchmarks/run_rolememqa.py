"""RoleMemQA 평가 러너 — 롤플레잉 장/단기 기억 저장소 축.

지식베이스 QA가 아니라 **채팅 기억 소환**을 측정한다: 8개 페르소나와의
멀티세션(각 30세션, ~7개월) 대화가 세션당 1노트로 적재된 볼트에서,
단기/장기/에피소드/업데이트/시간/2홉/거절 질문의 골드 세션을 찾는가.

지표는 KorMapleQA와 동일 (doc_hit@k / ans_hit@k, twohop full_support@8)
+ 롤플레잉 특화:
  update_trap_above_gold  옛-선호 세션(함정)이 골드(최신) 위에 랭크된 비율
                          — 기억 저장소가 "지금"을 물었는데 과거를 내밀면 실패

    python benchmarks/run_rolememqa.py                 # 4 arms (clean)
    python benchmarks/run_rolememqa.py --messy         # 지저분한 실채팅 변형
    python benchmarks/run_rolememqa.py --arm lemory
"""

from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (DATA, SYSTEMS, WORK, load_env, make_engine, normalize_ko,
                    prewarm_queries, save_json)

from lemory.retrieval.search import hybrid_search

QFILE = DATA / "rolememqa" / "questions.jsonl"
VAULT = DATA / "rolememqa" / "vault"
K = 8

ARMS = SYSTEMS
normalize = normalize_ko


def evaluate(eng, questions: list[dict], mode: str, graph: bool) -> dict:
    per_type: dict[str, list[dict]] = defaultdict(list)
    latencies = []
    abst_rows = []
    for q in questions:
        t0 = time.time()
        res = hybrid_search(eng, q["q"], k=K, mode=mode, graph=graph)
        latencies.append(time.time() - t0)
        hits = res.hits
        if not q.get("answerable", True):
            abst_rows.append({"q": q["q"],
                              "top1": hits[0].title if hits else None})
            continue
        golds = q["gold_notes"]
        ans = normalize(q["answers"][0])
        titles = [h.title for h in hits]
        doc_rank = next((i for i, t in enumerate(titles) if t in golds), None)
        ans_rank = next((i for i, h in enumerate(hits)
                         if h.title in golds and ans in normalize(h.text)),
                        None)
        row = {
            "doc1": doc_rank == 0, "doc8": doc_rank is not None,
            "ans1": ans_rank == 0, "ans8": ans_rank is not None,
        }
        if q["type"] == "twohop":
            row["full_support"] = set(golds) <= set(titles)
        if q.get("trap_note"):
            # 함정(옛 값/가짜 값 세션)이 골드보다 위에 랭크되면 실패 —
            # update(선호 변경)와 retraction(번복) 공통 지표
            trap_rank = next((i for i, t in enumerate(titles)
                              if t == q["trap_note"]), None)
            row["trap_above_gold"] = (trap_rank is not None
                                      and (doc_rank is None or trap_rank < doc_rank))
        per_type[q["type"]].append(row)

    summary: dict[str, float | int] = {}
    all_rows = [r for rows in per_type.values() for r in rows]
    for label, rows in [("all", all_rows)] + sorted(per_type.items()):
        n = len(rows)
        if not n:
            continue
        summary[f"{label}_n"] = n
        for m in ("doc1", "doc8", "ans1", "ans8"):
            summary[f"{label}_{m}"] = round(sum(r[m] for r in rows) / n, 4)
        if any("full_support" in r for r in rows):
            fs = [r for r in rows if "full_support" in r]
            summary[f"{label}_full_support@8"] = round(
                sum(r["full_support"] for r in fs) / len(fs), 4)
        if any("trap_above_gold" in r for r in rows):
            tr = [r for r in rows if "trap_above_gold" in r]
            summary[f"{label}_trap_above_gold"] = round(
                sum(r["trap_above_gold"] for r in tr) / len(tr), 4)
    latencies.sort()
    summary["p50_ms"] = round(latencies[len(latencies) // 2] * 1000, 2)
    summary["abstention_top1"] = abst_rows
    return summary


def main() -> None:
    load_env()
    messy = "--messy" in sys.argv
    qfile = DATA / "rolememqa" / ("questions_messy.jsonl" if messy else "questions.jsonl")
    vault = DATA / "rolememqa" / ("vault-messy" if messy else "vault")
    questions = [json.loads(l) for l in qfile.read_text().splitlines()]
    arms = dict(ARMS)
    if "--arm" in sys.argv:
        name = sys.argv[sys.argv.index("--arm") + 1]
        arms = {name: ARMS[name]}

    eng = make_engine(vault, tag="rolememqa-messy" if messy else "rolememqa")
    rep = eng.index()
    print(f"index: docs={eng.store.doc_count()} chunks={eng.store.chunk_count()} "
          f"embedded={rep.embedded} ({rep.seconds:.0f}s)", flush=True)
    prewarm_queries(eng, [q["q"] for q in questions])

    results = {}
    for name, opts in arms.items():
        s = evaluate(eng, questions, opts["mode"], opts["graph"])
        results[name] = s
        print(name, f"all_doc1={s['all_doc1']} all_doc8={s['all_doc8']} "
                    f"ans8={s['all_ans8']} p50={s['p50_ms']}ms", flush=True)
        for t in ("short", "long", "episodic", "update", "retraction", "joke",
                  "temporal", "twohop"):
            if f"{t}_doc8" in s:
                extra = ""
                if f"{t}_full_support@8" in s:
                    extra += f" fs={s[f'{t}_full_support@8']}"
                if f"{t}_trap_above_gold" in s:
                    extra += f" trap_above_gold={s[f'{t}_trap_above_gold']}"
                print(f"   {t:9s} doc1={s[f'{t}_doc1']} doc8={s[f'{t}_doc8']} "
                      f"ans8={s[f'{t}_ans8']}{extra}", flush=True)
    out = WORK / ("results_rolememqa_messy.json" if messy else "results_rolememqa.json")
    save_json(out, results)
    print("saved ->", out)


if __name__ == "__main__":
    main()
