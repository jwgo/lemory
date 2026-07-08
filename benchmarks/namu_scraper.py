"""나무위키 메이플스토리 문서 트리 수집기 (network policy가 namu.wiki를
허용해야 동작 — 현재 이 환경에서는 차단되어 있음).

    python namu_scraper.py crawl   # 분류:메이플스토리 하위 트리 전체 수집
    python namu_scraper.py build   # 수집본 -> 옵시디언 볼트 변환

정중한 수집: 1 req/1.2s, 재시작 가능(문서별 저장), 원문(raw)만 요청.
결과: benchmarks/work/namu_maple/raw/*.txt  (나무마크 원문)
      benchmarks/work/namu_maple/vault/*.md (변환된 볼트)
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from namu_parser import extract_categories, namu_to_markdown

BASE = "https://namu.wiki"
ROOT_CATEGORY = "분류:메이플스토리"
OUT = Path(__file__).parent / "work" / "namu_maple"
RAW = OUT / "raw"
STATE = OUT / "state.json"
DELAY = 1.2
MAX_DOCS = 4000  # safety cap

HEADERS = {
    "User-Agent": "LemoryBenchmark/0.1 (personal knowledge-base research; polite crawler)",
    "Accept-Language": "ko",
}


def _get(client: httpx.Client, url: str) -> httpx.Response | None:
    for attempt in range(4):
        try:
            r = client.get(url, headers=HEADERS, timeout=30, follow_redirects=True)
        except httpx.HTTPError:
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code == 200:
            return r
        if r.status_code in (403, 429):
            time.sleep(20 * (attempt + 1))  # be extra polite on pushback
            continue
        return None
    return None


def _safe_name(title: str) -> str:
    return re.sub(r'[/\\:*?"<>|]', "-", title)[:120]


def fetch_raw(client: httpx.Client, title: str) -> str | None:
    url = f"{BASE}/raw/{urllib.parse.quote(title, safe='')}"
    r = _get(client, url)
    time.sleep(DELAY)
    return r.text if r is not None else None


def category_members(client: httpx.Client, category: str) -> tuple[list[str], list[str]]:
    """Return (subcategories, documents) of a 분류 page via its raw + html."""
    docs: list[str] = []
    subcats: list[str] = []
    url = f"{BASE}/w/{urllib.parse.quote(category, safe='')}"
    r = _get(client, url)
    time.sleep(DELAY)
    if r is None:
        return subcats, docs
    for m in re.finditer(r'href="/w/([^"#?]+)"', r.text):
        title = urllib.parse.unquote(m.group(1))
        if title.startswith("분류:"):
            if title != category:
                subcats.append(title)
        elif not title.startswith(("파일:", "틀:", "사용자:", "나무위키:", "휴지통:")):
            docs.append(title)
    return sorted(set(subcats)), sorted(set(docs))


def crawl() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    state = json.loads(STATE.read_text()) if STATE.exists() else {
        "queue_cats": [ROOT_CATEGORY], "seen_cats": [], "docs": {}, "fetched": []}
    seen_cats = set(state["seen_cats"])
    fetched = set(state["fetched"])

    with httpx.Client() as client:
        # discover the category tree
        while state["queue_cats"]:
            cat = state["queue_cats"].pop(0)
            if cat in seen_cats:
                continue
            seen_cats.add(cat)
            subcats, docs = category_members(client, cat)
            for sc in subcats:
                if sc not in seen_cats:
                    state["queue_cats"].append(sc)
            for d in docs:
                state["docs"][d] = cat
            state["seen_cats"] = sorted(seen_cats)
            STATE.write_text(json.dumps(state, ensure_ascii=False))
            print(f"[cat] {cat}: +{len(docs)} docs, +{len(subcats)} subcats "
                  f"(total {len(state['docs'])})", flush=True)

        # fetch raw namumark for every document
        todo = [d for d in state["docs"] if d not in fetched][:MAX_DOCS]
        for i, title in enumerate(todo):
            raw = fetch_raw(client, title)
            if raw:
                (RAW / f"{_safe_name(title)}.txt").write_text(raw, encoding="utf-8")
            fetched.add(title)
            state["fetched"] = sorted(fetched)
            if i % 20 == 0:
                STATE.write_text(json.dumps(state, ensure_ascii=False))
                print(f"[doc] {i+1}/{len(todo)} {title}", flush=True)
        STATE.write_text(json.dumps(state, ensure_ascii=False))
    print(f"crawl done: {len(fetched)} documents")


def build() -> None:
    vault = OUT / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in RAW.glob("*.txt"):
        raw = f.read_text(encoding="utf-8")
        title = f.stem
        md = namu_to_markdown(raw, title)
        if len(md) < 80:  # redirects/stubs
            continue
        cats = extract_categories(raw)
        tags = " ".join(f"#{c.replace(' ', '_')}" for c in cats[:6])
        (vault / f"{title}.md").write_text(f"{tags}\n\n{md}\n", encoding="utf-8")
        n += 1
    print(f"vault built: {n} notes -> {vault}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "crawl"
    if cmd == "crawl":
        crawl()
    elif cmd == "build":
        build()
    else:
        raise SystemExit("usage: namu_scraper.py crawl|build")
