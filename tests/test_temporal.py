"""Temporal awareness: doc dates, KR/EN intent parsing, recency-boosted search."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta

from lemory.retrieval.temporal import doc_date, parse_temporal, recency_weight

NOW = datetime(2026, 7, 9, 15, 0).timestamp()


# ------------------------------------------------------------------ doc_date
def test_doc_date_from_frontmatter_beats_mtime():
    ts = doc_date("Note", "Note.md", json.dumps({"date": "2026-07-01"}), mtime=1.0)
    assert datetime.fromtimestamp(ts).date().isoformat() == "2026-07-01"


def test_doc_date_from_daily_note_filename():
    for name in ("2026-07-03", "2026.07.03", "20260703"):
        ts = doc_date(name, f"Daily/{name}.md", "{}", mtime=1.0)
        assert datetime.fromtimestamp(ts).date().isoformat() == "2026-07-03", name


def test_doc_date_falls_back_to_mtime():
    assert doc_date("Ideas", "Ideas.md", "{}", mtime=1234.5) == 1234.5


def test_doc_date_ignores_phone_numbers():
    # 8-digit runs inside longer digit strings must not parse as dates
    ts = doc_date("Contact 01012345678", "c.md", "{}", mtime=7.0)
    assert ts == 7.0


# ------------------------------------------------------------- intent parsing
def test_vague_recent_korean_and_english():
    for q in ("요새 내가 읽던 책", "요즘 하던 운동", "최근 결정한 것", "what did I do recently"):
        it = parse_temporal(q, NOW)
        assert it.active and it.recent and it.range_start is None, q


def test_yesterday_window():
    it = parse_temporal("어제 회의에서 뭐 정했지", NOW)
    assert it.range_start is not None
    s = datetime.fromtimestamp(it.range_start)
    assert s.date().isoformat() == "2026-07-08"


def test_last_week_window():
    it = parse_temporal("지난주에 뭐 했더라", NOW)
    s = datetime.fromtimestamp(it.range_start).date()
    e = datetime.fromtimestamp(it.range_end).date()
    assert s.isoformat() == "2026-06-29" and e.isoformat() == "2026-07-06"  # Mon..Sun+1


def test_n_days_ago():
    it = parse_temporal("3일 전에 적어둔 링크", NOW)
    assert it.range_start is not None
    mid = datetime.fromtimestamp((it.range_start + it.range_end) / 2).date()
    assert abs((datetime(2026, 7, 6).date() - mid).days) <= 1


def test_non_temporal_query_inactive():
    assert not parse_temporal("파이썬 데코레이터 정리", NOW).active
    assert not parse_temporal("what is the budget of Project Atlas", NOW).active


def test_recency_weight_decays():
    assert recency_weight(NOW, NOW, 21) == 1.0
    w21 = recency_weight(NOW - 21 * 86400, NOW, 21)
    assert abs(w21 - 0.5) < 1e-6
    assert recency_weight(NOW - 180 * 86400, NOW, 21) < 0.01


# --------------------------------------------------------- end-to-end search
def test_recent_note_wins_on_temporal_query(engine, vault):
    import os

    old_day = (datetime.fromtimestamp(NOW) - timedelta(days=150)).date().isoformat()
    new_day = (datetime.fromtimestamp(NOW) - timedelta(days=2)).date().isoformat()
    (vault / f"{old_day}.md").write_text(
        "Started reading the book Snow Crash this evening. Reading log.",
        encoding="utf-8",
    )
    (vault / f"{new_day}.md").write_text(
        "Started reading the book Piranesi this evening. Reading log.",
        encoding="utf-8",
    )
    # fixture notes without dated names would otherwise all look freshly
    # edited (mtime = test run time); age them like a real months-old vault
    for f in vault.rglob("*.md"):
        if f.stem not in (old_day, new_day):
            os.utime(f, (NOW - 200 * 86400, NOW - 200 * 86400))
    engine.index()
    engine.now = lambda: NOW

    hits = engine.search("요즘 내가 읽던 book reading log", k=2)
    assert hits and hits[0].title == new_day, [h.title for h in hits]

    # without temporal wording, recency must not override relevance
    hits2 = engine.search("book Snow Crash reading log", k=2)
    assert hits2[0].title == old_day


def test_explicit_window_beats_pure_recency(engine, vault):
    d_yesterday = (datetime.fromtimestamp(NOW) - timedelta(days=1)).date().isoformat()
    d_today = datetime.fromtimestamp(NOW).date().isoformat()
    (vault / f"{d_yesterday}.md").write_text("Meeting: decided to use FoundationDB for tracing.")
    (vault / f"{d_today}.md").write_text("Meeting: decided nothing, rescheduled.")
    engine.index()
    engine.now = lambda: NOW

    hits = engine.search("어제 meeting decided", k=2)
    assert hits and hits[0].title == d_yesterday, [h.title for h in hits]


def test_ask_context_includes_dates(engine, vault):
    from lemory.retrieval.answer import build_context

    engine.index()
    engine.now = lambda: NOW
    day = datetime.fromtimestamp(NOW).date().isoformat()
    (vault / f"{day}.md").write_text("Today I benchmarked the kimchi fridge sensors.")
    engine.index()
    hits = engine.search("kimchi fridge sensors", k=3)
    ctx = build_context(hits)
    assert day in ctx  # date tag rendered next to the note title
