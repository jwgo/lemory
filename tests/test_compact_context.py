"""Compact fact-sheet context (supermemory-style aggregation, LLM-free)."""

from lemory.retrieval.compact import build_compact_context, split_sentences


def test_split_sentences_kr_en():
    text = ("The Mercury Initiative launched in March. We decided to price at $0.04. "
            "요즘 읽는 책은 피라네시다. 자기 전에 몇 챕터씩 읽고 있다.")
    sents = split_sentences(text)
    assert any("price" in s for s in sents)
    assert any("피라네시" in s for s in sents)
    assert len(sents) >= 3


def test_compact_is_smaller_and_keeps_answer(engine):
    engine.index()
    q = "what price per compute-minute did we decide"
    hits = engine.search(q, k=6)
    from lemory.retrieval.answer import build_context

    full = build_context(hits)
    compact = build_compact_context(engine, q, hits)
    assert len(compact) < len(full)
    assert "0.04" in compact  # the answer fact survives aggregation
    assert "[1]" in compact   # citation numbering preserved


def test_compact_falls_back_on_tiny_chunks(engine, vault):
    (vault / "Tiny.md").write_text("short")
    engine.index()
    hits = engine.search("tiny short note", k=2)
    ctx = build_compact_context(engine, "tiny short note", hits)
    assert ctx  # never empty


def test_ask_uses_compact_when_configured(engine):
    engine.index()
    engine.cfg.context_style = "compact"
    ans = engine.ask("what is atlas?")
    assert ans.text  # generation path works with compact context
