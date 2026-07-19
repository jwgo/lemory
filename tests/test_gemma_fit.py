"""gemma._fit prioritizes freshly-retrieved grounding over stale chat history,
and _contextual_query folds the antecedent (prior assistant turn) into the
retrieval query."""

import lemory.providers.gemma as g
from lemory.interfaces.http import _contextual_query


class FakeLLM:
    """~1 token per whitespace word, fixed small window."""
    def __init__(self, n_ctx=200):
        self._n = n_ctx

    def n_ctx(self):
        return self._n

    def tokenize(self, b: bytes):
        return (b.decode("utf-8", "ignore").split() or [""])

    def detokenize(self, ids):
        return (" ".join(ids)).encode("utf-8")


def test_fit_keeps_grounding_drops_old_history():
    llm = FakeLLM(n_ctx=500)
    grounding = "NOTE " * 100  # 100 tokens of evidence — must survive
    history = [
        {"role": "user", "content": "oldest " * 150},      # dropped first
        {"role": "assistant", "content": "middle " * 150},
        {"role": "user", "content": "recent " * 50},        # newest, kept
    ]
    system, kept = g._fit(llm, grounding, history, "current question", 20)
    # grounding preserved intact (evidence outranks stale turns)
    assert system.split().count("NOTE") == 100
    # the oldest turn was dropped; the most recent survives
    assert len(kept) < len(history)
    assert kept[-1]["content"].startswith("recent")
    assert not any(m["content"].startswith("oldest") for m in kept)


def test_fit_trims_huge_grounding_below_window():
    llm = FakeLLM(n_ctx=500)
    grounding = "X " * 5000  # absurdly long — capped, never overflows
    system, kept = g._fit(llm, grounding, [], "q", 20)
    assert len(system.split()) < 500  # capped under the window


def test_contextual_query_folds_prior_assistant_answer():
    msgs = [
        {"role": "user", "content": "결제팀 리드 누구야?"},
        {"role": "assistant", "content": "결제팀 리드는 김지수입니다."},
        {"role": "user", "content": "그 사람 좋아하는 DB는?"},
    ]
    q = _contextual_query("그 사람 좋아하는 DB는?", msgs)
    # the entity the user refers to (김지수) must reach the retrieval query
    assert "김지수" in q
    assert "그 사람 좋아하는 DB" in q


def test_contextual_query_passthrough_for_standalone_question():
    msgs = [{"role": "user", "content": "프로젝트 아틀라스 예산이 얼마였지?"}]
    q = _contextual_query("프로젝트 아틀라스 예산이 얼마였지?", msgs)
    assert q == "프로젝트 아틀라스 예산이 얼마였지?"
