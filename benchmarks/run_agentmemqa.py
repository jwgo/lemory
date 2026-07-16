"""AgentMemQA 평가 러너 — 일반 에이전트 메모리 축 (업무/코딩 비서).

RoleMemQA(롤플레잉)와 짝을 이루는 벤치: 5개 프로젝트 12주치 세션 기억에서
설정값/결정(번복 함정)/담당자/버그픽스/일정/컨벤션/2홉을 소환한다. 지표는
RoleMemQA와 동일 (doc/ans/ans_any@k, trap_above_gold, twohop full-support).

    python benchmarks/run_agentmemqa.py                # 4 arms
    python benchmarks/run_agentmemqa.py --arm lemory
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import DATA, SYSTEMS, WORK, load_env, make_engine, prewarm_queries, save_json
from run_rolememqa import evaluate

QFILE = DATA / "agentmemqa" / "questions.jsonl"
VAULT = DATA / "agentmemqa" / "vault"


def main() -> None:
    load_env()
    questions = [json.loads(l) for l in QFILE.read_text().splitlines()]
    arms = dict(SYSTEMS)
    if "--arm" in sys.argv:
        name = sys.argv[sys.argv.index("--arm") + 1]
        arms = {name: SYSTEMS[name]}

    eng = make_engine(VAULT, tag="agentmemqa")
    rep = eng.index()
    print(f"index: docs={eng.store.doc_count()} chunks={eng.store.chunk_count()} "
          f"embedded={rep.embedded} ({rep.seconds:.0f}s)", flush=True)
    prewarm_queries(eng, [q["q"] for q in questions])

    results = {}
    for name, opts in arms.items():
        s = evaluate(eng, questions, opts["mode"], opts["graph"])
        results[name] = s
        print(name, f"all_doc1={s['all_doc1']} all_doc8={s['all_doc8']} "
                    f"ans_any1={s['all_ans_any1']} ans_any8={s['all_ans_any8']} "
                    f"p50={s['p50_ms']}ms", flush=True)
        for t in ("value", "decision", "person", "bugfix", "temporal",
                  "convention", "twohop"):
            if f"{t}_doc8" in s:
                extra = ""
                if f"{t}_full_support@8" in s:
                    extra += f" fs={s[f'{t}_full_support@8']}"
                if f"{t}_trap_above_gold" in s:
                    extra += f" trap_above_gold={s[f'{t}_trap_above_gold']}"
                print(f"   {t:10s} doc1={s[f'{t}_doc1']} doc8={s[f'{t}_doc8']} "
                      f"ans8={s[f'{t}_ans8']}{extra}", flush=True)
    out = WORK / "results_agentmemqa.json"
    save_json(out, results)
    print("saved ->", out)


if __name__ == "__main__":
    main()
