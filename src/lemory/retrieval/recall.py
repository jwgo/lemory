"""Scoped recall over typed fragments, and work-thread reconstruction.

`recall()` is `search()` with the agent-memory axis attached: narrow by type /
case / status / topic / recency, then rank with the full hybrid stack. The
narrowing is a prefilter, not a replacement for ranking — a hosted memory
service that answers `type=error` with a cosine top-k gives you the most
semantically similar error; this gives you the one BM25, vectors, the link
graph and recency all agree on, out of the errors only.

`resume_case()` is the part a filter cannot do. A case id in a WHERE clause
returns rows; a work thread needs the shape of the work — when it started,
what was decided, what is still broken, what the last session said to do
next. Because fragments are notes, that reconstruction is a read over
frontmatter plus the episode sections `reflect()` wrote, with no LLM call and
no second store.
"""

from __future__ import annotations

import re
import time
from datetime import datetime

from ..ingestion.fragments import normalize_case

# sections `reflect()` writes, in the order resume renders them back
_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.M)
_NEXT_STEPS_H = "다음 단계"
_DECISIONS_H = "결정"


def recall(
    engine,
    query: str = "",
    type: str = "",
    case: str = "",
    topic: str = "",
    status: str = "",
    since_days: int = 0,
    k: int = 8,
) -> list[dict]:
    """Retrieve fragments matching the scope, ranked by the hybrid retriever.

    With no query this degrades to a newest-first listing of the scope, which
    is the right answer for "what do I know about case X" — there is nothing
    to rank against."""
    fields: dict[str, list[str]] = {}
    for key, val in (("type", type), ("case", normalize_case(case)),
                     ("topic", topic), ("status", status)):
        v = (val or "").strip()
        if v:
            fields[key] = [v]

    # Over-fetch: both the recency window and the one-row-per-fragment rule
    # below thin the list, and an agent that asked for k fragments should get
    # k fragments.
    hits = engine.search(query.strip(), k=k * 3, fields=fields or None)

    cutoff = time.time() - since_days * 86400 if since_days > 0 else 0.0
    meta = engine.store.docs_meta({h.doc_id for h in hits})
    mtimes = ({d.id: d.mtime for d in engine.store.all_docs()} if cutoff else {})
    # a fragment is short enough to be a "stub", so the chunk that wins is
    # often the enrichment pseudo-chunk — great for ranking, unreadable as an
    # excerpt ("date: … source: assistant …"). Show the prose instead.
    bodies = engine.store.body_text(
        {h.doc_id for h in hits if h.heading == engine.store.ENRICH_HEADING})

    out: list[dict] = []
    seen: set[int] = set()
    for h in hits:
        # a fragment IS a note, so it gets one row — document search wants
        # several chunks of a long note, recall never does
        if h.doc_id in seen:
            continue
        if cutoff and mtimes.get(h.doc_id, 0.0) < cutoff:
            continue
        seen.add(h.doc_id)
        fm = meta.get(h.doc_id, {})
        out.append({
            "note": h.title,
            "path": h.path,
            "type": str(fm.get("type", "") or ""),
            "case": str(fm.get("case", "") or ""),
            "status": str(fm.get("status", "") or ""),
            "topic": str(fm.get("topic", "") or ""),
            "anchor": bool(fm.get("anchor", False)),
            "text": bodies.get(h.doc_id, h.text) if h.heading == engine.store.ENRICH_HEADING
                    else h.text,
            "score": round(h.score, 4),
        })
        if len(out) >= k:
            break
    return out


def _section(body: str, heading: str) -> list[str]:
    """Bullet lines under a `## heading` in an episode note."""
    lines = body.splitlines()
    out: list[str] = []
    grabbing = False
    for ln in lines:
        m = _SECTION_RE.match(ln)
        if m:
            grabbing = m.group(1).strip() == heading
            continue
        if grabbing and ln.strip().startswith("-"):
            out.append(ln.strip().lstrip("-").strip())
    return out


def resume_case(engine, case: str, limit: int = 40) -> dict:
    """Reconstruct a work thread so the next session starts where the last one
    stopped: timeline, decisions, still-open failures, and the next steps the
    last reflection recorded."""
    case_n = normalize_case(case)
    if not case_n:
        raise ValueError("empty case id")
    ids = engine.store.docs_matching(fields={"case": [case_n]})
    if not ids:
        return {"case": case_n, "found": 0, "fragments": [], "open": [],
                "decisions": [], "next_steps": [], "brief": f"'{case_n}' 케이스 기록 없음"}

    docs = {d.id: d for d in engine.store.all_docs() if d.id in ids}
    meta = engine.store.docs_meta(ids)
    ordered = sorted(docs.values(), key=lambda d: d.mtime)[-limit:]

    vault = engine.cfg.resolved_vault()
    fragments, open_items, decisions, next_steps = [], [], [], []
    phases: list[str] = []

    for d in ordered:
        fm = meta.get(d.id, {})
        ftype = str(fm.get("type", "") or "")
        status = str(fm.get("status", "") or "")
        phase = str(fm.get("phase", "") or "")
        if phase and phase not in phases:
            phases.append(phase)
        row = {
            "date": datetime.fromtimestamp(d.mtime).strftime("%Y-%m-%d %H:%M"),
            "type": ftype, "status": status, "phase": phase,
            "note": d.title, "path": d.path,
        }
        fragments.append(row)
        if ftype == "error" and status != "resolved":
            open_items.append(row)
        if ftype == "episode":
            try:
                body = (vault / d.path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            decisions.extend(_section(body, _DECISIONS_H))
            # only the LATEST episode's next steps matter — an earlier
            # session's plan is superseded, not additive
            steps = _section(body, _NEXT_STEPS_H)
            if steps:
                next_steps = steps

    brief = _render_brief(case_n, fragments, phases, decisions, open_items, next_steps)
    return {
        "case": case_n,
        "found": len(ids),
        "phases": phases,
        "fragments": fragments,
        "open": open_items,
        "decisions": decisions,
        "next_steps": next_steps,
        "brief": brief,
    }


def _render_brief(case, fragments, phases, decisions, open_items, next_steps) -> str:
    """One paste-ready block: what an agent should read before touching the
    case again. Ordered by what changes behaviour soonest — unfinished work
    first, history last."""
    lines = [f"# 케이스 재개 — {case}",
             f"기록 {len(fragments)}건" + (f" · 단계: {' → '.join(phases)}" if phases else "")]
    if next_steps:
        lines.append("\n## 다음 단계 (직전 세션 기준)")
        lines += [f"- {s}" for s in next_steps]
    if open_items:
        lines.append("\n## 미해결")
        lines += [f"- [{o['status'] or 'open'}] {o['note']} ({o['path']})"
                  for o in open_items]
    if decisions:
        lines.append("\n## 지금까지의 결정")
        lines += [f"- {d}" for d in decisions[-12:]]
    if fragments:
        lines.append("\n## 타임라인")
        lines += [f"- {f['date']} · {f['type'] or 'note'} · {f['note']} ({f['path']})"
                  for f in fragments[-12:]]
    return "\n".join(lines)


def open_cases(engine, limit: int = 20) -> list[dict]:
    """Every case with unfinished business, most-recently-touched first — the
    "what was I in the middle of" question, answered without naming a case."""
    meta = engine.store.docs_meta()
    agg: dict[str, dict] = {}
    for d in engine.store.all_docs():
        fm = meta.get(d.id, {})
        case = str(fm.get("case", "") or "").strip()
        if not case:
            continue
        row = agg.setdefault(case, {"case": case, "fragments": 0, "open": 0,
                                    "last": 0.0, "phase": "", "phase_at": 0.0})
        row["fragments"] += 1
        if str(fm.get("type", "")) == "error" and str(fm.get("status", "")) != "resolved":
            row["open"] += 1
        if d.mtime > row["last"]:
            row["last"] = d.mtime
        # the latest NON-EMPTY phase: fragments written mid-case often omit it,
        # and blanking the case's phase because the last write skipped the
        # field would lose the only progress marker there is
        phase = str(fm.get("phase", "") or "")
        if phase and d.mtime >= row["phase_at"]:
            row["phase"], row["phase_at"] = phase, d.mtime
    rows = sorted(agg.values(), key=lambda r: -r["last"])[:limit]
    for r in rows:
        r.pop("phase_at", None)
        r["last_touched"] = datetime.fromtimestamp(r.pop("last")).strftime("%Y-%m-%d")
    return rows
