"""KorMapleQA — LLM 파이프라인 경쟁자 (mem0, LightRAG), 서브코퍼스 프로토콜.

전량(1,469노트) LLM 인제스트는 문서당 LLM 호출이 필요해 예산을 초과하므로,
**라벨 명시 서브코퍼스**로 측정한다: 층화 질문 샘플(유형당 40 + 해당
single의 변형)의 골드 노트 전부 + 시드 고정 디스트랙터로 400노트. 두
시스템 모두 같은 서브코퍼스·같은 질문·같은 Gemini 모델(flash-lite 추출,
embedding-001)을 쓴다. Lemory 비교 행도 같은 서브코퍼스로 다시 계산한다
(전량 수치와 섞이지 않도록).

    python benchmarks/run_kormapleqa_llm_rivals.py prep      # 서브코퍼스 생성
    python benchmarks/run_kormapleqa_llm_rivals.py mem0
    python benchmarks/run_kormapleqa_llm_rivals.py lightrag
    python benchmarks/run_kormapleqa_llm_rivals.py lemory    # 동일조건 비교행
"""

from __future__ import annotations

import json
import random
import shutil
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (DATA, WORK, load_env, make_engine, normalize_ko,
                    prewarm_queries, save_json)

from lemory.config import LemoryConfig

QFILE = DATA / "kormapleqa" / "questions.jsonl"
VAULT = DATA / "maple_real" / "vault"
SUB_DIR = WORK / "kormapleqa-sub"
SUB_VAULT = SUB_DIR / "vault"
SUB_Q = SUB_DIR / "questions.json"
SEED = 20260711
PER_TYPE = 40
N_NOTES = 400
K = 8


norm = normalize_ko


def prep() -> None:
    rows = [json.loads(l) for l in QFILE.read_text().splitlines()
            if json.loads(l).get("answerable", True)]
    rng = random.Random(SEED)
    by_type = defaultdict(list)
    for q in rows:
        by_type[q["type"]].append(q)
    core = []
    for t in ("single", "masked", "twohop", "temporal"):
        core.extend(rng.sample(by_type[t], min(PER_TYPE, len(by_type[t]))))
    # 그 single들의 변형(kw/casual/typo)도 포함 — 같은 골드
    core_single_gold = {tuple(q["gold_notes"]) for q in core if q["type"] == "single"}
    for t in ("kw", "casual", "typo"):
        core.extend(q for q in by_type[t]
                    if tuple(q["gold_notes"]) in core_single_gold)
    golds = {g for q in core for g in q["gold_notes"]}
    all_titles = sorted(p.stem for p in VAULT.glob("*.md"))
    distractors = [t for t in all_titles if t not in golds]
    rng.shuffle(distractors)
    keep = sorted(golds) + distractors[: max(0, N_NOTES - len(golds))]

    if SUB_VAULT.exists():
        shutil.rmtree(SUB_VAULT)
    SUB_VAULT.mkdir(parents=True)
    for t in keep:
        shutil.copy(VAULT / f"{t}.md", SUB_VAULT / f"{t}.md")
    SUB_Q.write_text(json.dumps(core, ensure_ascii=False))
    chars = sum(len((SUB_VAULT / f"{t}.md").read_text()) for t in keep)
    print(f"subcorpus: {len(keep)} notes ({len(golds)} golds), "
          f"{len(core)} questions, {chars/1e6:.1f}M chars")


def evaluate_titles(questions, get_titles) -> dict:
    per_type = defaultdict(lambda: {"doc1": 0, "doc8": 0, "fs": 0, "n": 0})
    lat = []
    for q in questions:
        t0 = time.time()
        titles = get_titles(q["q"])
        lat.append(time.time() - t0)
        golds = q["gold_notes"]
        st = per_type[q["type"]]
        st["n"] += 1
        st["doc1"] += bool(titles and titles[0] in golds)
        st["doc8"] += any(t in golds for t in titles)
        st["fs"] += all(g in titles for g in golds)
    out = {}
    tot = {"doc1": 0, "doc8": 0, "fs": 0, "n": 0}
    for t, st in sorted(per_type.items()):
        for k in tot:
            tot[k] += st[k]
        out[t] = {k: round(st[k] / st["n"], 4) if k != "n" else st["n"]
                  for k in ("doc1", "doc8", "fs", "n")}
    out["all"] = {k: round(tot[k] / tot["n"], 4) if k != "n" else tot["n"]
                  for k in ("doc1", "doc8", "fs", "n")}
    lat.sort()
    out["p50_s"] = round(lat[len(lat) // 2], 3)
    return out


def run_lemory() -> None:
    questions = json.loads(SUB_Q.read_text())
    eng = make_engine(SUB_VAULT, tag="kormapleqa-sub")
    eng.index()
    prewarm_queries(eng, [q["q"] for q in questions])

    def get_titles(q):
        return [h.title for h in eng.search(q, k=K)]

    res = evaluate_titles(questions, get_titles)
    print(json.dumps(res, indent=1, ensure_ascii=False))
    save_json(SUB_DIR / "results_lemory.json", res)


def run_mem0() -> None:
    from mem0 import Memory

    questions = json.loads(SUB_Q.read_text())
    key = LemoryConfig().resolved_gemini_key()
    config = {
        "llm": {"provider": "gemini",
                "config": {"model": "gemini-2.5-flash-lite", "api_key": key,
                           "temperature": 0.0}},
        "embedder": {"provider": "gemini",
                     "config": {"model": "models/gemini-embedding-001",
                                "api_key": key, "embedding_dims": 768}},
        "vector_store": {"provider": "qdrant",
                         "config": {"embedding_model_dims": 768,
                                    "path": str(SUB_DIR / "mem0_qdrant"),
                                    "on_disk": True}},
    }
    m = Memory.from_config(config)
    state_file = SUB_DIR / "mem0_state.json"
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    added = set(state.get("added", []))
    files = sorted(SUB_VAULT.glob("*.md"))
    t0 = time.time()
    for i, f in enumerate(files):
        if f.stem in added:
            continue
        text = f.read_text()[:60000]
        for attempt in range(8):
            try:
                m.add(text, user_id="bench", metadata={"note": f.stem})
                break
            except Exception as e:
                print(f"add {f.stem} failed ({str(e)[:100]}) retry {attempt+1}",
                      flush=True)
                time.sleep(min(20 * (attempt + 1), 90))
        added.add(f.stem)
        state["added"] = sorted(added)
        save_json(state_file, state)
        if (i + 1) % 25 == 0:
            print(f"mem0 add {i+1}/{len(files)}", flush=True)
    state.setdefault("add_seconds", time.time() - t0)
    save_json(state_file, state)

    def get_titles(q):
        res = m.search(q, filters={"user_id": "bench"}, limit=K)
        rows = res.get("results", res) if isinstance(res, dict) else res
        titles = []
        for r in rows:
            t = (r.get("metadata") or {}).get("note")
            if t and t not in titles:
                titles.append(t)
        return titles

    res = evaluate_titles(questions, get_titles)
    res["ingest_seconds"] = state["add_seconds"]
    print(json.dumps(res, indent=1, ensure_ascii=False))
    save_json(SUB_DIR / "results_mem0.json", res)


def run_lightrag() -> None:
    import asyncio

    import numpy as np
    from lightrag import LightRAG, QueryParam
    from lightrag.utils import EmbeddingFunc

    from lemory.providers.gemini import GeminiClient

    questions = json.loads(SUB_Q.read_text())
    cfg = LemoryConfig()
    client = GeminiClient(api_key=cfg.resolved_gemini_key(),
                          llm_model="gemini-2.5-flash-lite", llm_rpm=60,
                          max_output_tokens=4096)

    async def llm_fn(prompt, system_prompt=None, history_messages=None, **kw):
        full = (system_prompt + "\n\n" if system_prompt else "") + prompt
        for attempt in range(8):
            try:
                return await asyncio.to_thread(
                    client.generate, full, max_output_tokens=4096)
            except Exception as e:
                await asyncio.sleep(min(20 * (attempt + 1), 90))
        raise RuntimeError("llm failed")

    async def embed_fn(texts):
        return np.array(await asyncio.to_thread(client.embed, list(texts)))

    lr_dir = SUB_DIR / "lightrag"
    lr_dir.mkdir(parents=True, exist_ok=True)

    async def main_async():
        rag = LightRAG(
            working_dir=str(lr_dir), llm_model_func=llm_fn,
            embedding_func=EmbeddingFunc(embedding_dim=768, max_token_size=2048,
                                         func=embed_fn),
        )
        await rag.initialize_storages()
        state_file = SUB_DIR / "lightrag_state.json"
        state = json.loads(state_file.read_text()) if state_file.exists() else {}
        added = set(state.get("added", []))
        t0 = time.time()
        files = sorted(SUB_VAULT.glob("*.md"))
        for i, f in enumerate(files):
            if f.stem in added:
                continue
            await rag.ainsert(f"[{f.stem}]\n" + f.read_text()[:60000],
                              file_paths=[f.name])
            added.add(f.stem)
            state["added"] = sorted(added)
            save_json(state_file, state)
            if (i + 1) % 20 == 0:
                print(f"lightrag insert {i+1}/{len(files)}", flush=True)
        state.setdefault("ingest_seconds", time.time() - t0)
        save_json(state_file, state)

        def titles_from_context(ctx: str, limit: int = K) -> list[str]:
            titles = []
            stems = {p.stem for p in files}
            for stem in stems:
                if stem in ctx and stem not in titles:
                    titles.append(stem)
            return titles[:limit]

        rows = {}
        for i, q in enumerate(questions):
            t0q = time.time()
            ctx = await rag.aquery(q["q"], param=QueryParam(
                mode="mix", only_need_context=True, top_k=K))
            rows[q["id"]] = {"titles": titles_from_context(str(ctx)),
                             "sec": time.time() - t0q}
            if (i + 1) % 20 == 0:
                print(f"lightrag query {i+1}/{len(questions)}", flush=True)
        save_json(SUB_DIR / "lightrag_preds.json", rows)

        def get_titles(qtext, _rows=rows,
                       _byq={q["q"]: q["id"] for q in questions}):
            return _rows[_byq[qtext]]["titles"]

        res = evaluate_titles(questions, get_titles)
        res["ingest_seconds"] = state["ingest_seconds"]
        print(json.dumps(res, indent=1, ensure_ascii=False))
        save_json(SUB_DIR / "results_lightrag.json", res)

    asyncio.run(main_async())


if __name__ == "__main__":
    load_env()
    cmd = sys.argv[1]
    if cmd == "prep":
        prep()
    elif cmd == "lemory":
        run_lemory()
    elif cmd == "mem0":
        run_mem0()
    elif cmd == "lightrag":
        run_lightrag()
