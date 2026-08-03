"""기억 피라미드 벤치 — 부트 컨텍스트 토큰 대비 페르소나 질문 커버리지.

TencentDB Agent Memory의 헤드라인 구조(항상 주입되는 L3 페르소나 + L2 장면
목차, 세부는 드릴다운)를 우리 파이프라인(distill → consolidate)으로 재현하고,
같은 걸 측정한다:

  boot        페르소나 노트 + 장면 지도만 주입했을 때, 페르소나 사실 질문의
              답이 그 안에 이미 있는 비율 (드릴다운 0회)
  boot+scene  boot + 해당 인물의 장면 노트 1개를 read_note (드릴다운 1회)
  raw-dump    비교선: 세션 원문 전체 주입이라면 몇 토큰인가

토큰은 그쪽 fast_token_estimate와 같은 목적의 근사(cl100k 기준 문자 계수)로
센다. 재현: python benchmarks/run_pyramid.py  (.env에 GEMINI_API_KEY 필요.
--no-llm 이면 결정적 폴백 본문으로 같은 측정을 돌린다)

그쪽 발표치(PersonaMem 48%→76%)는 리포에 하네스가 없어 재현 불가 —
여기 수치는 전부 이 스크립트로 재현된다.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import DATA, WORK, load_env, make_engine, normalize_ko, save_json

QFILE = DATA / "rolememqa" / "questions.jsonl"
SRC_VAULT = DATA / "rolememqa" / "vault"
VAULT = WORK / "pyramid-vault"
TAG = "pyramid"

_CJK = re.compile(r"[가-힣ぁ-ヿ一-鿿]")


def approx_tokens(text: str) -> int:
    """cl100k 근사: CJK ≈ 1.6 tok/자, 그 외 ≈ 0.25 tok/자 (공백 포함).
    tdbam의 fast_token_estimate와 같은 목적의 단일 패스 문자 계수."""
    cjk = len(_CJK.findall(text))
    other = len(text) - cjk
    return int(cjk * 1.6 + other * 0.25)


def build(use_llm: bool, reuse: bool = False):
    from lemory.ingestion.distill import distill
    from lemory.ingestion.pyramid import consolidate

    if reuse and VAULT.exists():
        return make_engine(VAULT, TAG)
    if VAULT.exists():
        shutil.rmtree(VAULT)
    shutil.copytree(SRC_VAULT, VAULT)
    data_dir = WORK / f"index-{TAG}"
    if data_dir.exists():
        shutil.rmtree(data_dir)

    eng = make_engine(VAULT, TAG)
    t0 = time.time()
    eng.index()
    t_index = time.time() - t0

    t0 = time.time()
    if use_llm:
        digests = distill(eng)
    else:
        digests = distill(eng)  # distill needs the LLM either way (or brain)
    t_l1 = time.time() - t0

    t0 = time.time()
    rep = consolidate(eng, use_llm=use_llm)
    t_l23 = time.time() - t0
    print(f"index {t_index:.1f}s · L1 digests {len(digests)} ({t_l1:.1f}s) · "
          f"L2/L3 atoms {rep.atoms}, scenes +{len(rep.scenes_created)}"
          f"/{len(rep.scenes_updated)}u, persona={bool(rep.persona)} ({t_l23:.1f}s)")
    return eng


def boot_text(eng) -> str:
    from lemory.ingestion.pyramid import persona_block, scene_index

    lines = [persona_block(eng, max_chars=2400)]
    for s in scene_index(eng, limit=12):
        lines.append(f"- {s['title']} ({s['path']}) heat {s['heat']} · {s['summary']}")
    return "\n".join(lines)


def scene_body_for(eng, question: str) -> str:
    """드릴다운 1회: 장면 폴더로 스코프한 실제 하이브리드 검색 top-1의 본문.
    에이전트가 '장면에서 찾아봐'를 하는 것과 같은 기계적 절차다."""
    folder = eng.cfg.scene_folder.strip("/")
    hits = eng.search(f"folder:{folder} {question}", k=1)
    if not hits:
        return ""
    try:
        return (eng.cfg.resolved_vault() / hits[0].path).read_text(encoding="utf-8")
    except OSError:
        return ""


def main() -> None:
    load_env()
    use_llm = "--no-llm" not in sys.argv
    reuse = "--measure-only" in sys.argv
    qs = [json.loads(l) for l in QFILE.read_text(encoding="utf-8").splitlines() if l.strip()]
    # 페르소나 사실 축만: long(안정 사실)+short(단기 사실). episodic/temporal은
    # 검색층의 몫이고 이미 run_rolememqa가 측정한다.
    qs = [q for q in qs if q["type"] in ("long", "short") and q.get("answerable")]

    eng = build(use_llm, reuse=reuse)
    boot = boot_text(eng)
    boot_tok = approx_tokens(boot)
    nboot = normalize_ko(boot)

    raw_dump = "\n".join(
        p.read_text(encoding="utf-8") for p in sorted(SRC_VAULT.rglob("*.md")))
    raw_tok = approx_tokens(raw_dump)

    hit_boot = hit_drill = hit_search = 0
    drill_toks, search_toks = [], []
    for q in qs:
        answers = [normalize_ko(a) for a in q["answers"]]
        in_boot = any(a in nboot for a in answers)
        if in_boot:
            hit_boot += 1
            hit_drill += 1
            drill_toks.append(boot_tok)
        else:
            body = scene_body_for(eng, q["q"])
            drill_toks.append(boot_tok + approx_tokens(body))
            if any(a in normalize_ko(body) for a in answers):
                hit_drill += 1
        # 대조군: 피라미드 없이 원문 검색 top-8 청크 (기존 검색층의 비용/커버리지)
        hits = eng.search(q["q"], k=8)
        blob = " ".join(h.text for h in hits)
        search_toks.append(approx_tokens(blob))
        if any(a in normalize_ko(blob) for a in answers):
            hit_search += 1

    n = len(qs)
    out = {
        "n_questions": n,
        "llm": use_llm,
        "boot_tokens": boot_tok,
        "raw_dump_tokens": raw_tok,
        "token_ratio_vs_dump": round(raw_tok / max(1, boot_tok), 1),
        "boot_coverage": round(hit_boot / n, 4),
        "boot_plus_1scene_coverage": round(hit_drill / n, 4),
        "avg_boot_plus_scene_tokens": int(sum(drill_toks) / n),
        "search_top8_coverage": round(hit_search / n, 4),
        "avg_search_top8_tokens": int(sum(search_toks) / n),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    save_json(WORK / f"results_pyramid{'_nollm' if not use_llm else ''}.json", out)


if __name__ == "__main__":
    main()
