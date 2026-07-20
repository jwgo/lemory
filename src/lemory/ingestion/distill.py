"""Fact distillation: chat sessions → compact memory-summary notes.

The read half of the memory loop retrieves raw session notes well until small
talk poisons the vocabulary (measured: RoleMemQA-messy episodic doc@1 0.458
vs 0.938 clean). Distillation writes what a person would: a short fact sheet
per conversation group · "지훈의 여동생 이름은 김보람" · which is exactly the
clean text retrieval ranks best.

Boundaries that keep this from rotting the architecture:
- Output is MARKDOWN NOTES IN THE VAULT (기억요약/), indexed like any note.
  No second store, no special retrieval path, visible/editable/deletable.
- Ingest stays LLM-free; this is an opt-in post-pass (`lemory distill`),
  like `lemory enrich`. Keyless installs use the on-device Gemma brain.
- Source notes are never modified or deleted; every digest cites its
  sessions as [[wikilinks]] (provenance + graph edges for free).
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict

log = logging.getLogger("lemory.distill")

_PROMPT = (
    "아래는 사용자와 상대의 대화 기록이다. 사용자에 대해 '기억할 가치가 있는 "
    "사실'만 뽑아 한 줄씩 요약하라.\n"
    "규칙:\n"
    "- 형식: 각 줄 '- <사실 진술문>'. 진술문에는 이름·제목·가게명 같은 "
    "고유한 값을 원문 그대로 포함하라 (값을 빼먹은 요약은 쓸모없다).\n"
    "- 대상: 선호, 인물(이름), 반려동물, 알레르기, 사건, 별명, 바뀐 사실"
    "(가장 최신 값만), 그리고 **둘이 함께 정한 것들 · 약속, 노래, 계획, "
    "주고받은 선물과 그 출처** (관계의 기억이 가장 중요하다).\n"
    "- 농담/번복 주의: '농담이고', '뻥이야', '사실은' 뒤에 나오는 값이 진짜다. "
    "가짜 값은 적지 마라.\n"
    "- 대화에 없는 내용을 지어내지 마라. 기억할 사실이 없으면 '없음'만 출력.\n\n"
    "{convo}"
)

_FM_RE = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)
_BULLET_RE = re.compile(r"^\s*[-*•]\s*(.+)$")


def _chat_docs(engine, folder: str) -> list:
    """Session notes to distill: tagged chat-import (what import-chats, the
    assistant logger, and roleplay logs all write), optionally folder-scoped."""
    out = []
    for d in engine.store.all_docs():
        if folder and not d.path.startswith(folder.rstrip("/") + "/"):
            continue
        if "chat-import" in (d.tags or []):
            out.append(d)
    return out


def _group_key(doc) -> tuple[str, str]:
    """(parent folder, YYYY-MM) · one digest per conversation group per month."""
    parent = doc.path.rsplit("/", 1)[0] if "/" in doc.path else ""
    m = re.search(r"(\d{4}-\d{2})", doc.path) or re.search(r"(\d{4}-\d{2})", doc.title)
    month = m.group(1) if m else "undated"
    return parent, month


def _body(engine, doc) -> str:
    text = (engine.cfg.resolved_vault() / doc.path).read_text(encoding="utf-8")
    return _FM_RE.sub("", text).strip()


def distill(engine, folder: str = "", out_folder: str = "기억요약",
            batch_chars: int = 4000) -> list[str]:
    """Distill chat-session notes into fact-sheet notes. Returns the
    vault-relative paths written. Overwrites each group's digest (the digest
    is derived data · the sessions stay the source of truth)."""
    docs = _chat_docs(engine, folder)
    if not docs:
        return []
    groups: dict[tuple[str, str], list] = defaultdict(list)
    for d in docs:
        groups[_group_key(d)].append(d)

    vault = engine.cfg.resolved_vault()
    base = vault / out_folder
    if not base.resolve().is_relative_to(vault.resolve()):
        out_folder, base = "기억요약", vault / "기억요약"
    base.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    for (parent, month), ds in sorted(groups.items()):
        ds.sort(key=lambda d: d.path)
        bullets: list[str] = []
        batch, size = [], 0
        flushes = [d for d in ds]
        def _flush(batch_docs):
            if not batch_docs:
                return
            convo = "\n\n".join(f"## {d.title}\n{_body(engine, d)}" for d in batch_docs)
            try:
                out = engine.llm.generate(_PROMPT.format(convo=convo[:batch_chars]),
                                          temperature=0.0, max_output_tokens=768)
            except Exception as e:
                log.warning("distill generation failed for %s/%s: %s", parent, month, e)
                return
            for line in str(out).splitlines():
                m = _BULLET_RE.match(line)
                if m:
                    fact = m.group(1).strip()
                    if fact and fact != "없음" and fact not in bullets:
                        bullets.append(fact)
        for d in flushes:
            b = _body(engine, d)
            if size + len(b) > batch_chars and batch:
                _flush(batch)
                batch, size = [], 0
            batch.append(d)
            size += len(b)
        _flush(batch)
        if not bullets:
            continue
        slug = (parent.replace("/", "-") or "chats")
        title = f"기억 {slug} {month}"
        rel = f"{out_folder}/{title}.md"
        sources = " ".join(f"[[{d.title}]]" for d in ds)
        (base / f"{title}.md").write_text(
            f"---\ndate: {month}-01\nsource: distill\nlemory_generated: true\n"
            f"tags: [memory-digest]\n---\n\n# {title}\n\n"
            + "\n".join(f"- {b}" for b in bullets[:24])
            + f"\n\n출처: {sources}\n",
            encoding="utf-8",
        )
        written.append(rel)
    if written:
        engine.index(paths=set(written))
    return written
