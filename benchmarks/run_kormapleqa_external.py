"""KorMapleQA — 외부 로컬 메모리 시스템 (qmd, MemPalace) 평가.

두 시스템 모두 "API 키 없음"이 헤드라인인 실경쟁자이고 완전 로컬로 돈다.
mem0 / cognee / supermemory / LightRAG 는 LLM API 키(또는 호스팅 계정)가
필수라 키 없는 환경에서는 측정 불가 — 해당 열은 키가 생기면 채운다.

지표는 run_kormapleqa.py 와 동일 프로토콜의 문서 수준 doc_hit@8
(+ MemPalace 는 answer-in-output 도 부기 — §4f 프로토콜과의 연속성).

    python benchmarks/run_kormapleqa_external.py qmd search        # full set
    python benchmarks/run_kormapleqa_external.py qmd vsearch 40    # 유형당 40
    python benchmarks/run_kormapleqa_external.py qmd query 12      # 유형당 12
    python benchmarks/run_kormapleqa_external.py mempalace [n]

체크포인트: work/kormapleqa-external/preds.jsonl — 중단·재개 안전.
"""

from __future__ import annotations

import json
import os
import random
import re
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import DATA, WORK, save_json

QFILE = DATA / "kormapleqa" / "questions.jsonl"
OUT = WORK / "kormapleqa-external"
K = 8
SEED = 20260711

QMD_DIR = WORK / "qmd-kormapleqa"
QMD_ENV = {
    **os.environ,
    "PATH": os.path.expanduser("~/.bun/bin") + ":" + os.environ.get("PATH", ""),
    "XDG_CACHE_HOME": str(QMD_DIR / "cache"),
    "XDG_DATA_HOME": str(QMD_DIR / "data"),
    "XDG_CONFIG_HOME": str(QMD_DIR / "config"),
    "QMD_SQLITE_DYLIB": os.path.expanduser("~/.local/lib/libsqlite3.dylib"),
}
MP = Path(sys.executable).parent / "mempalace"
MP_PALACE = str(WORK / "mempalace-kormapleqa")

_JSON_RE = re.compile(r"(\[\s*\{.*\}\s*\]|\[\s*\])", re.S)


def norm_title(s: str) -> str:
    return re.sub(r"[\s\-_]+", " ", s.lower()).strip()


def qmd_run(mode: str, q: str, timeout: int = 900) -> tuple[list[str], float, str]:
    t0 = time.time()
    proc = subprocess.run(
        ["qmd", mode, "--json", q, "-n", str(K * 2)],
        capture_output=True, text=True, timeout=timeout, env=QMD_ENV,
        cwd=str(QMD_DIR),
    )
    dt = time.time() - t0
    m = _JSON_RE.search(proc.stdout)
    if not m:
        raise RuntimeError(f"no JSON (rc={proc.returncode}): {proc.stdout[-160:]} {proc.stderr[-160:]}")
    titles: list[str] = []
    for r in json.loads(m.group(1)):
        f = str(r.get("file", ""))
        t = norm_title(Path(f.split("://")[-1]).stem)
        if t and t not in titles:
            titles.append(t)
    return titles[:K], dt, proc.stdout


def mp_run(q: str, timeout: int = 300) -> tuple[list[str], float, str]:
    t0 = time.time()
    proc = subprocess.run(
        [str(MP), "--palace", MP_PALACE, "search", q, "--results", str(K)],
        capture_output=True, text=True, timeout=timeout,
        env={**os.environ, "MEMPALACE_BACKEND": "sqlite_exact"},
    )
    dt = time.time() - t0
    out = proc.stdout
    # 드로어 헤더의 "Source: <파일명>.md" 라인에서 제목 추출 (공백 포함)
    titles: list[str] = []
    for m in re.finditer(r"Source:\s*(.+?)\.md\s*$", out, re.M):
        t = norm_title(m.group(1))
        if t and t not in titles:
            titles.append(t)
    return titles[:K], dt, out


def normalize_ans(s: str) -> str:
    return re.sub(r"[^\w가-힣]+", "", s.lower())


def main() -> None:
    system = sys.argv[1]
    mode = sys.argv[2] if system == "qmd" else "search"
    per_type = int(sys.argv[3]) if system == "qmd" and len(sys.argv) > 3 else (
        int(sys.argv[2]) if system == "mempalace" and len(sys.argv) > 2 else 0)

    questions = [json.loads(l) for l in QFILE.read_text().splitlines()
                 if json.loads(l).get("answerable", True)]
    if per_type:
        rng = random.Random(SEED)
        by_type = defaultdict(list)
        for q in questions:
            by_type[q["type"]].append(q)
        questions = [q for t, qs in sorted(by_type.items())
                     for q in rng.sample(qs, min(per_type, len(qs)))]

    OUT.mkdir(parents=True, exist_ok=True)
    ck_file = OUT / "preds.jsonl"
    state = {}
    if ck_file.exists():
        for line in ck_file.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                state[(r["system"], r["mode"], r["id"])] = r

    run = qmd_run if system == "qmd" else (lambda q: mp_run(q))
    ck = open(ck_file, "a", encoding="utf-8")
    n_done = 0
    for q in questions:
        key = (system, mode, q["id"])
        if key in state:
            continue
        try:
            if system == "qmd":
                titles, dt, raw = qmd_run(mode, q["q"])
            else:
                titles, dt, raw = mp_run(q["q"])
        except Exception as e:
            print(f"  {q['id']} failed: {str(e)[:140]}", flush=True)
            continue
        golds = [norm_title(g) for g in q["gold_notes"]]
        row = {
            "system": system, "mode": mode, "id": q["id"], "type": q["type"],
            "doc1": bool(titles and titles[0] in golds),
            "doc8": any(t in golds for t in titles),
            "full_support": all(g in titles for g in golds),
            "aic": normalize_ans(q["answers"][0]) in normalize_ans(raw)
                   if q.get("answers") else None,
            "sec": round(dt, 3),
        }
        ck.write(json.dumps(row, ensure_ascii=False) + "\n")
        ck.flush()
        state[key] = row
        n_done += 1
        if n_done % 20 == 0:
            done_rows = [r for (s, m, _), r in state.items()
                         if s == system and m == mode]
            d8 = sum(r["doc8"] for r in done_rows) / len(done_rows)
            print(f"{system}/{mode} {len(done_rows)} done — running doc8 {d8:.3f}",
                  flush=True)

    rows = [r for (s, m, _), r in state.items() if s == system and m == mode]
    per: dict[str, dict] = {}
    for label in ["all"] + sorted({r["type"] for r in rows}):
        sub = rows if label == "all" else [r for r in rows if r["type"] == label]
        if not sub:
            continue
        per[label] = {
            "n": len(sub),
            "doc1": round(sum(r["doc1"] for r in sub) / len(sub), 4),
            "doc8": round(sum(r["doc8"] for r in sub) / len(sub), 4),
            "full_support": round(sum(r["full_support"] for r in sub) / len(sub), 4),
            "aic": round(sum(bool(r["aic"]) for r in sub) / len(sub), 4),
        }
    lat = sorted(r["sec"] for r in rows)
    per["p50_s"] = lat[len(lat) // 2] if lat else None
    print(json.dumps(per, indent=2, ensure_ascii=False))
    save_json(OUT / f"results_{system}_{mode}.json", per)


if __name__ == "__main__":
    main()
