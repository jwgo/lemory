"""Typo correction: local did-you-mean over the FTS lexicon."""

from lemory.retrieval.search import correct_typos


def test_unknown_word_corrected(engine, vault):
    engine.index()
    fixed = correct_typos(engine.store, "mercury initative pricing")
    assert "initi" in fixed  # 'initative' repaired toward the indexed term
    assert fixed != "mercury initative pricing"


def test_known_words_untouched(engine):
    engine.index()
    q = "mercury initiative pricing decision"
    assert correct_typos(engine.store, q) == q


def test_gibberish_left_alone(engine):
    engine.index()
    q = "xqzvw flurbelplex"
    assert correct_typos(engine.store, q) == q  # nothing close in the lexicon


def test_search_survives_typo(engine):
    engine.index()
    hits = engine.search("mercury initative pricing decizion", k=4)
    assert hits and hits[0].title == "Mercury Initiative"


def test_typo_correction_can_be_disabled(engine):
    engine.index()
    engine.cfg.typo_correction = False
    assert engine.search("mercury initiative pricing", k=4)  # still works


def test_korean_tokens_skipped(engine, vault):
    engine.index()
    q = "김지수의 프로젝트"
    assert correct_typos(engine.store, q) == q
