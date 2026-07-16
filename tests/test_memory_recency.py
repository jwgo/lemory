"""Roleplay/chat-memory retrieval behaviors (RoleMemQA-driven).

Covers the three mechanisms measured on the roleplay long/short-term memory
benchmark: (1) vague recency anchored to the vault's own newest note so an
archival vault keeps its internal timeline, (2) the recency-weighted verbatim
pin choice so "요즘 X?" pins the newer covering session over the stale one,
(3) the boilerplate-only specificity gate that abstains lexical machinery on
queries with no discriminative token.
"""
from __future__ import annotations

import calendar

import pytest
from conftest import DIM, FakeGemini

from lemory.config import LemoryConfig
from lemory.engine import Engine
from lemory.retrieval.search import _all_tokens_common


def _mk_engine(tmp_path, notes: dict[str, str]) -> Engine:
    v = tmp_path / "vault"
    v.mkdir()
    for name, body in notes.items():
        (v / f"{name}.md").write_text(body, encoding="utf-8")
    cfg = LemoryConfig(vault=v, data_dir=tmp_path / "data", embed_dim=DIM,
                       gemini_api_key="test", chunk_chars=400)
    eng = Engine(cfg, llm=FakeGemini())
    eng.index()
    return eng


def _ts(y, m, d) -> float:
    return calendar.timegm((y, m, d, 12, 0, 0))


def test_recency_anchors_to_newest_note_in_archival_vault(tmp_path):
    """'요즘' in an ARCHIVAL vault (every note far in the past) must still
    prefer the newer note: recency is anchored at the vault's newest note,
    not the wall clock, so wall-clock distance can't flatten the timeline."""
    eng = _mk_engine(tmp_path, {
        "옛 취향": ("---\ndate: 2024-01-05\n---\n"
                  "내가 제일 좋아하는 음식은 김치찌개야. "
                  "제일 좋아하는 음식은 역시 김치찌개."),
        "새 취향": ("---\ndate: 2024-06-20\n---\n"
                  "요즘은 입맛이 바뀌어서 제일 좋아하는 음식이 파스타가 됐어."),
    })
    eng.now = lambda: _ts(2026, 7, 1)  # wall clock: years later
    hits = eng.search("요즘 제일 좋아하는 음식은 뭐야?", k=2)
    assert hits and hits[0].title == "새 취향"


def test_recency_boost_gated_on_temporal_intent(tmp_path):
    """Without a recency marker the older (lexically stronger) note keeps
    rank 1 — the anchor must not leak recency into non-temporal queries."""
    eng = _mk_engine(tmp_path, {
        "옛 취향": ("---\ndate: 2024-01-05\n---\n"
                  "내가 제일 좋아하는 음식은 김치찌개야. "
                  "제일 좋아하는 음식은 역시 김치찌개. 좋아하는 음식 얘기."),
        "새 취향": ("---\ndate: 2024-06-20\n---\n"
                  "어제는 파스타를 먹었는데 그냥 그랬어."),
    })
    eng.now = lambda: _ts(2026, 7, 1)
    hits = eng.search("제일 좋아하는 음식", k=2)
    assert hits and hits[0].title == "옛 취향"


def test_all_tokens_common_gate(tmp_path):
    """A query made only of boilerplate-common tokens abstains the verbatim
    machinery; one discriminative token re-enables it."""
    notes = {f"잡담 {i:02d}": f"---\ndate: 2024-03-{i+1:02d}\n---\n"
                             f"오늘도 약속 잊지마! 그리고 안녕 잘자."
             for i in range(12)}
    notes["보물"] = "---\ndate: 2024-03-20\n---\n은하수문방구에서 약속 도장을 샀다."
    eng = _mk_engine(tmp_path, notes)
    store = eng.store
    # '약속' occurs in 13/13 notes -> rate >> gate -> all-common
    assert _all_tokens_common(store, "약속이 뭐였지?") is True
    # '은하수문방구' is rare -> query carries discriminative evidence
    assert _all_tokens_common(store, "은하수문방구 약속 뭐였지?") is False
    # unknown token (never indexed) counts as discriminative, not common
    assert _all_tokens_common(store, "크툴루와의 약속") is False


def test_title_boost_ignores_date_stamp_tokens(tmp_path):
    """A dated daily-note title ('2023-09-12 Meeting with Steph') gets the
    title boost when its WORDS are covered — the numeric stamp tokens are
    never part of a natural question and must not veto the boost."""
    eng = _mk_engine(tmp_path, {
        "2023-09-12 Meeting with Steph": (
            "We discussed the roadmap. Steph brought a book about emergence "
            "published years ago."),
        "Reading List": (
            "Books on my shelf: a meeting-notes guide and other titles. "
            "meeting steph meeting steph appears often here."),
    })
    hits = eng.search("meeting with steph roadmap", k=2)
    assert hits and hits[0].title == "2023-09-12 Meeting with Steph"


def test_update_style_query_end_to_end(tmp_path):
    """RoleMemQA update-type in miniature: old preference stated verbatim
    twice vs a newer correction phrased differently — '요즘' query must
    surface the correction at rank 1 (pin choice is recency-weighted)."""
    eng = _mk_engine(tmp_path, {
        "s05": ("---\ndate: 2025-03-01\n---\n"
                "**민지**: 내가 제일 좋아하는 음식은 민트초코야! "
                "정말 제일 좋아하는 음식은 민트초코."),
        "s23": ("---\ndate: 2025-07-10\n---\n"
                "**민지**: 요즘은 제일 좋아하는 음식이 마라탕이 됐어."),
        "s30": ("---\ndate: 2025-08-20\n---\n"
                "**도윤**: 오늘 날씨 참 좋다. 산책 다녀왔어."),
    })
    eng.now = lambda: _ts(2026, 7, 1)
    hits = eng.search("민지가 요즘 제일 좋아하는 음식은 뭐야?", k=3)
    assert hits and hits[0].title == "s23"


def test_indexer_keeps_public_enrich_api():
    """Regression: inserting _MentionAutomaton above Indexer's tail methods
    once swallowed enrich_entities into the new class (review finding #1)."""
    from lemory.ingestion.indexer import Indexer, _MentionAutomaton
    assert hasattr(Indexer, "enrich_entities")
    assert not hasattr(_MentionAutomaton, "enrich_entities")
