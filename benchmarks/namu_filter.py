"""나무위키 덤프(namuwiki_20210301.json, ~15GB)에서 메이플스토리 관련 문서를
스트리밍 추출해 옵시디언 볼트로 변환한다.

선택 기준(모든 하위 데이터):
  * 문서의 분류에 '메이플스토리'가 포함 — [[분류:메이플스토리/...]],
    [[분류:...(메이플스토리)]] 등 하위 분류 전부
  * 또는 제목에 '메이플스토리'가 포함
리다이렉트/스텁(#redirect, 80자 미만)은 제외.

    python namu_filter.py            # dump -> raw docs (jsonl)
    python namu_filter.py build      # jsonl -> benchmarks/data/maple_real/vault
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import ijson

sys.path.insert(0, str(Path(__file__).parent))
from namu_parser import extract_categories, namu_to_markdown

DUMP = Path(__file__).parent / "work" / "namudump" / "namuwiki_20210301.json"
JSONL = Path(__file__).parent / "work" / "namudump" / "maple_docs.jsonl"
VAULT = Path(__file__).parent / "data" / "maple_real" / "vault"

CAT_RE = re.compile(r"\[\[분류:[^\]]*메이플스토리")


def scan() -> None:
    n_total = 0
    n_kept = 0
    with open(DUMP, "rb") as fh, open(JSONL, "w", encoding="utf-8") as out:
        for doc in ijson.items(fh, "item"):
            n_total += 1
            if n_total % 100000 == 0:
                print(f"scanned {n_total} docs, kept {n_kept}", flush=True)
            title = doc.get("title", "")
            text = doc.get("text", "")
            if doc.get("namespace") not in (0, "0", None):
                continue
            if text.lstrip()[:9].lower().startswith("#redirect"):
                continue
            if len(text) < 80:
                continue
            if CAT_RE.search(text) or "메이플스토리" in title:
                out.write(json.dumps({"title": title, "text": text}, ensure_ascii=False) + "\n")
                n_kept += 1
    print(f"DONE scanned={n_total} kept={n_kept}", flush=True)


def _safe_name(title: str) -> str:
    return re.sub(r'[/\\:*?"<>|]', "-", title).strip()[:120]


def build() -> None:
    VAULT.mkdir(parents=True, exist_ok=True)
    for f in VAULT.glob("*.md"):
        f.unlink()
    n = 0
    seen = set()
    for line in open(JSONL, encoding="utf-8"):
        doc = json.loads(line)
        title = doc["title"]
        name = _safe_name(title)
        if not name or name in seen:
            continue
        seen.add(name)
        md = namu_to_markdown(doc["text"], title)
        if len(md) < 80:
            continue
        cats = extract_categories(doc["text"])
        tags = " ".join("#" + re.sub(r"[^\w가-힣/]", "_", c)[:40] for c in cats[:6])
        (VAULT / f"{name}.md").write_text(f"{tags}\n\n{md}\n", encoding="utf-8")
        n += 1
    print(f"vault built: {n} notes -> {VAULT}", flush=True)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "build":
        build()
    else:
        scan()
