"""KorQuAD 1.0 (실제 한국어 위키피디아 + 사람이 만든 질문) 검색 벤치마크.

140개 실제 위키 문서(964 문단)를 노트로, dev의 인간 작성 질문에서 층화 샘플.
Hit = 반환된 청크가 정답 문서에서 나왔고 정답 스팬 문자열을 포함.
자작 코퍼스가 아니므로 외부에서 검증 가능한 한국어 성능 증명.

    python benchmarks/run_korquad.py           # 400 questions, 3 systems
    python benchmarks/run_korquad.py --e2e     # +40-question generation eval
"""

from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (SYSTEMS, WORK, answer_in_text, best_f1, load_env, make_engine,
                    normalize_answer, prewarm_queries, rank_metrics, save_json)

DATA_FILE = Path(__file__).parent / "data" / "korquad" / "KorQuAD_v1.0_dev.json"
VAULT = WORK / "korquad_vault"
N_QUESTIONS = 400
SEED = 13
K = 8


def prepare() -> list[dict]:
    data = json.loads(DATA_FILE.read_text())["data"]
    VAULT.mkdir(parents=True, exist_ok=True)
    for f in VAULT.glob("*.md"):
        f.unlink()
    questions = []
    for art in data:
        title = art["title"].replace("/", "-")
        body = "\n\n".join(p["context"] for p in art["paragraphs"])
        (VAULT / f"{title}.md").write_text(body, encoding="utf-8")
        for p in art["paragraphs"]:
            for qa in p["qas"]:
                golds = sorted({a["text"] for a in qa["answers"]})
                questions.append({"q": qa["question"], "article": title, "answers": golds})
    rng = random.Random(SEED)
    rng.shuffle(questions)
    return questions[:N_QUESTIONS]


def main(e2e: bool = False) -> None:
    load_env()
    questions = prepare()
    engine = make_engine(VAULT, tag="korquad")
    rep = engine.index()
    print(f"index: {rep.chunks} chunks ({rep.embedded} embedded, {rep.seconds:.0f}s); "
          f"{engine.store.doc_count()} real wiki articles", flush=True)
    prewarm_queries(engine, [q["q"] for q in questions])

    results = {}
    for sys_name, opts in SYSTEMS.items():
        flags, lat = [], []
        for q in questions:
            t = time.time()
            hits = engine.search(q["q"], k=K, **opts)
            lat.append(time.time() - t)
            flags.append([
                h.title == q["article"] and answer_in_text(h.text, q["answers"])
                for h in hits
            ])
        m = rank_metrics(flags)
        m["ms_per_query"] = sorted(lat)[len(lat) // 2] * 1000
        results[sys_name] = m
        print(sys_name, json.dumps(m), flush=True)
    out = {"n_questions": len(questions), "k": K, "systems": results}

    if e2e:
        from lemory.retrieval.answer import SYSTEM, build_context, build_prompt

        rng = random.Random(29)
        sample = rng.sample(questions, 40)
        gen_results = {}
        for sys_name in ("lemory", "vector", "bm25"):
            f1s, ems = [], []
            for q in sample:
                hits = engine.search(q["q"], k=K, **SYSTEMS[sys_name])
                pred = engine.llm.generate(
                    build_prompt(build_context(hits, max_chars=12000), q["q"],
                                 instruction="정답 구절만 짧게 답하세요."),
                    system=SYSTEM, temperature=0.0, max_output_tokens=64,
                ).strip()
                f1s.append(best_f1(pred, q["answers"]))
                ems.append(float(any(normalize_answer(g) in normalize_answer(pred)
                                     for g in q["answers"])))
            gen_results[sys_name] = {"f1": sum(f1s) / 40, "contain_em": sum(ems) / 40}
            print("e2e", sys_name, gen_results[sys_name], flush=True)
        out["e2e_40q"] = gen_results

    save_json(WORK / "results_korquad.json", out)


if __name__ == "__main__":
    main(e2e="--e2e" in sys.argv)
