"""Enumeration-query detection and adaptive retrieval depth."""

from lemory.retrieval.intent import adaptive_k, is_enumeration_query


def test_enumeration_english():
    assert is_enumeration_query("What books has Melanie read?")
    assert is_enumeration_query("Which US cities does John mention visiting?")
    assert is_enumeration_query("What activities does Deborah pursue besides teaching?")
    assert is_enumeration_query("How many times did I go climbing?")
    assert is_enumeration_query("List every restaurant we discussed")


def test_enumeration_korean():
    assert is_enumeration_query("올해 읽은 책들을 전부 알려줘")
    assert is_enumeration_query("클라이밍 몇 번 갔지?")
    assert is_enumeration_query("어떤 것들을 결정했지?")
    assert is_enumeration_query("회의에서 언급한 도구들이 뭐였지?")


def test_single_fact_not_enumeration():
    assert not is_enumeration_query("What is Dana's favorite database?")
    assert not is_enumeration_query("When was Acme founded?")
    assert not is_enumeration_query("요새 읽던 책 뭐였지?")
    assert not is_enumeration_query("Where does the author of Dune work?")


def test_adaptive_k_values():
    assert adaptive_k("What books has Melanie read?", 8) == 16
    assert adaptive_k("What is Dana's favorite database?", 8) == 8
    assert adaptive_k("List all projects", 16, cap=24) == 24
    assert adaptive_k("List all projects", 8, multiplier=1.0) == 8  # disabled


def test_ask_widens_for_list_question(engine):
    engine.index()
    calls = {}
    orig = engine.search

    def spy(q, k=8, **kw):
        calls["k"] = k
        return orig(q, k=k, **kw)

    engine.search = spy
    engine.ask("What projects exist? List all of them")
    assert calls["k"] == 16
    engine.ask("what is the mercury initiative price decision?")
    assert calls["k"] == 8
