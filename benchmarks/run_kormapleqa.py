"""KorMapleQA 평가 러너.

두 층위의 지표를 모두 계산한다:
  doc_hit@k   골드 문서가 top-k에 등장 (문서 수준 — Omnisearch처럼 문서
              단위로만 검색하는 시스템과의 공정 비교 지표)
  ans_hit@k   골드 문서의 청크이면서 정답 문자열을 실제로 포함 (엄격 —
              생성기가 컨텍스트로 쓸 수 있는 증거인지까지 본다)
  twohop 은 full_support@8(두 골드 문서 모두 top-8)도 계산.
  abstention 문항(answerable=false)은 별도 리포트 (top-1 제목만 기록).

    python benchmarks/run_kormapleqa.py                 # 4 arms
    python benchmarks/run_kormapleqa.py --arm lemory    # 하나만
    python benchmarks/run_kormapleqa.py --smartconn     # SC-class 추가 arm
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

QFILE = DATA / "kormapleqa" / "questions.jsonl"
VAULT = DATA / "maple_real" / "vault"
K = 8

ARMS = SYSTEMS  # one source of truth (benchmarks/common.py)


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
                         if h.title == golds[-1] and ans in normalize(h.text)),
                        None)
        row = {
            "doc1": doc_rank == 0, "doc8": doc_rank is not None,
            "ans1": ans_rank == 0, "ans8": ans_rank is not None,
        }
        if q["type"] == "twohop":
            row["full_support"] = set(golds) <= set(titles)
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
    latencies.sort()
    summary["p50_ms"] = round(latencies[len(latencies) // 2] * 1000, 2)
    summary["abstention_top1"] = abst_rows
    return summary


def main() -> None:
    load_env()
    questions = [json.loads(l) for l in QFILE.read_text().splitlines()]
    arms = dict(ARMS)
    if "--arm" in sys.argv:
        name = sys.argv[sys.argv.index("--arm") + 1]
        arms = {name: ARMS[name]}
    overrides = {}
    tag = "maple_real"
    if "--smartconn" in sys.argv:
        # Smart-Connections-class: 그 플러그인의 기본 로컬 모델, 순수 코사인
        from fastembed import TextEmbedding
        from fastembed.common.model_description import ModelSource, PoolingType
        try:
            TextEmbedding.add_custom_model(
                model="TaylorAI/bge-micro-v2", pooling=PoolingType.CLS,
                normalization=True,
                sources=ModelSource(hf="TaylorAI/bge-micro-v2"), dim=384)
        except Exception:
            pass
        overrides["local_embed_model"] = "TaylorAI/bge-micro-v2"
        tag = "kormapleqa-sc"
        arms = {"smartconn-class": dict(mode="vector", graph=False)}

    eng = make_engine(VAULT, tag=tag, **overrides)
    rep = eng.index()
    print(f"index: docs={eng.store.doc_count()} chunks={eng.store.chunk_count()} "
          f"embedded={rep.embedded} ({rep.seconds:.0f}s)")
    prewarm_queries(eng, [q["q"] for q in questions])

    results = {}
    for name, opts in arms.items():
        s = evaluate(eng, questions, opts["mode"], opts["graph"])
        results[name] = s
        keys = ["all_doc1", "all_doc8", "all_ans8", "p50_ms"]
        print(name, " ".join(f"{k}={s[k]}" for k in keys if k in s))
        for t in ("single", "masked", "twohop", "temporal", "kw", "casual", "typo"):
            if f"{t}_doc8" in s:
                extra = (f" fs={s.get(f'{t}_full_support@8')}"
                         if f"{t}_full_support@8" in s else "")
                print(f"   {t:9s} doc1={s[f'{t}_doc1']} doc8={s[f'{t}_doc8']} "
                      f"ans8={s[f'{t}_ans8']}{extra}")
    out = WORK / ("results_kormapleqa_sc.json" if "--smartconn" in sys.argv
                  else "results_kormapleqa.json")
    save_json(out, results)
    print("saved ->", out)


if __name__ == "__main__":
    main()
