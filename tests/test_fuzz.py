"""Property/fuzz tests: randomized documents and queries must never break
invariants. Seeded and deterministic, but broad (hundreds of cases per run)."""

import random
import string

import numpy as np
import pytest

from lemory.ingestion.markdown import chunk_note, parse_note, render_plain, split_sections
from lemory.storage import Store
from lemory.storage.sqlite_store import _fts_escape

PIECES = [
    "# Heading {i}", "## Sub {i}", "###### deep {i}",
    "plain paragraph {i} with some words and numbers 42",
    "- bullet {i}\n- another", "1. numbered {i}",
    "[[Wiki Link {i}]]", "[[Target|alias {i}]]", "[md link {i}](https://x.example)",
    "```python\ncode block {i}\nwith [[not-a-link]]\n```",
    "**bold {i}** and *italic* and `code`",
    "#tag{i} in line", "> quote {i}",
    "---", "| a | b |\n|---|---|\n| 1 | 2 |",
    "unicode: 한국어 문장 {i} — em-dash, émigré, 日本語",
    "", "   ", "\t",
    'weird chars: {{}} [[]] (()) "quotes" \'single\' 100% <tags>',
]


def random_doc(rng: random.Random, n_pieces: int) -> str:
    parts = []
    if rng.random() < 0.3:
        parts.append("---\ntags: [a, b]\ntitle: X\n---")
    for _ in range(n_pieces):
        parts.append(rng.choice(PIECES).replace("{i}", str(rng.randint(0, 999))))
    return "\n\n".join(parts)


@pytest.mark.parametrize("seed", range(60))
def test_parse_and_chunk_invariants(seed):
    rng = random.Random(seed)
    raw = random_doc(rng, rng.randint(0, 40))
    note = parse_note(raw, f"Doc {seed}")

    assert isinstance(note.tags, list)
    assert all(isinstance(t, str) for t in note.tags)
    assert isinstance(note.wikilinks, list)

    chunk_chars = rng.choice([200, 400, 1400])
    overlap = rng.choice([0, 50, 180])
    chunks = chunk_note(note.body, chunk_chars, overlap, min_chars=50)
    for heading, text in chunks:
        assert text.strip(), "empty chunk"
        assert len(text) <= chunk_chars * 1.8 + overlap, f"oversized chunk: {len(text)}"
        assert isinstance(heading, str)

    # plain rendering must not blow up, and never returns None
    plain = render_plain(note.body)
    assert isinstance(plain, str)
    sections = split_sections(note.body)
    assert all(isinstance(s.heading, str) for s in sections)


@pytest.mark.parametrize("seed", range(20))
def test_fts_random_queries_never_raise(tmp_path, seed):
    rng = random.Random(seed)
    store = Store(tmp_path / f"f{seed}.db")
    doc = store.upsert_document("a.md", "A", "h", 0.0, [], {}, 0.0)
    store.replace_chunks(doc, "A", [("", "hello world sample text 한국어")],
                         np.ones((1, 4), dtype=np.float32))
    alphabet = string.printable + "한글語日"
    for _ in range(25):
        q = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 30)))
        store.bm25_search(q, 5)  # must not raise
        assert isinstance(_fts_escape(q), str)
    store.close()


@pytest.mark.parametrize("seed", range(10))
def test_engine_random_vault(tmp_path, seed):
    """Random small vaults index and search without errors."""
    from lemory.config import LemoryConfig
    from lemory.engine import Engine
    from tests.conftest import DIM, FakeGemini

    rng = random.Random(seed)
    vault = tmp_path / "v"
    vault.mkdir()
    n = rng.randint(1, 8)
    for i in range(n):
        name = f"Note {seed}-{i}.md"
        (vault / name).write_text(random_doc(rng, rng.randint(0, 15)), encoding="utf-8")
    cfg = LemoryConfig(vault=vault, data_dir=tmp_path / "d", embed_dim=DIM,
                       gemini_api_key="x", chunk_chars=300)
    eng = Engine(cfg, llm=FakeGemini())
    rep = eng.index()
    assert rep.errors == []
    assert eng.store.doc_count() == n
    for mode in ("hybrid", "vector", "bm25"):
        eng.search("hello 한국어 sample", k=5, mode=mode)
    rep2 = eng.index()
    assert rep2.unchanged == n and rep2.embedded == 0
    eng.close()
