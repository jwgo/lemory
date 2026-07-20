"""Regression tests for bugs found in the 8-angle code review."""

import json
import threading
from lemory.config import tomllib  # 3.10-safe (tomli fallback)

import numpy as np
import pytest

from lemory.config import LemoryConfig, load_config
from lemory.storage import Store


def test_store_note_is_atomic(tmp_path):
    """A failure mid-write must roll back BOTH the doc hash and the chunks —
    otherwise incremental sync would skip the note forever."""
    s = Store(tmp_path / "t.db")
    vecs = np.ones((1, 4), dtype=np.float32)
    s.store_note("a.md", "A", "hash-v1", 0.0, [], {}, 0.0, [], [("", "old text")], vecs)

    bad_vectors = np.ones((0, 4), dtype=np.float32)  # shorter than chunks -> IndexError
    with pytest.raises(IndexError):
        s.store_note("a.md", "A", "hash-v2", 1.0, [], {}, 1.0, [],
                     [("", "new text one"), ("", "new text two")], bad_vectors)

    doc = s.get_doc_by_path("a.md")
    assert doc.content_hash == "hash-v1"  # hash NOT advanced past the chunks
    chunks = s.get_chunks(s.doc_chunk_ids(doc.id))
    assert [c.text for c in chunks.values()] == ["old text"]
    assert s.bm25_search("old", 5)
    s.close()


def test_env_beats_toml(tmp_path, monkeypatch):
    (tmp_path / "lemory.toml").write_text("[lemory]\nchunk_chars = 999\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LEMORY_CHUNK_CHARS", "555")
    assert load_config().chunk_chars == 555
    monkeypatch.delenv("LEMORY_CHUNK_CHARS")
    assert load_config().chunk_chars == 999


def test_concurrent_index_and_search(engine, vault):
    """Watcher-style concurrent index() + search() must not corrupt the
    matrix snapshot or raise (races found in review: _dirty loss, pos map)."""
    engine.index()
    errors = []

    def churn_files():
        try:
            for i in range(8):
                (vault / f"Churn {i}.md").write_text(f"note number {i} about churn topics")
                engine.index()
        except Exception as e:  # pragma: no cover
            errors.append(e)

    def churn_search():
        try:
            for _ in range(40):
                engine.search("mercury pricing churn", k=5)
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=churn_files)] + [
        threading.Thread(target=churn_search) for _ in range(3)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert engine.store.doc_count() == 12


def test_init_toml_escapes_special_paths(tmp_path, monkeypatch):
    weird = tmp_path / 'va"ult\\dir'
    weird.mkdir()
    monkeypatch.chdir(tmp_path)
    from typer.testing import CliRunner

    from lemory.interfaces.cli import app

    result = CliRunner().invoke(app, ["init", str(weird)])
    assert result.exit_code == 0
    # `init` (now an alias for `up`) writes the config into the vault root;
    # config discovery honors both the vault root and CWD.
    parsed = tomllib.loads((weird / "lemory.toml").read_text())
    assert parsed["lemory"]["vault"] == str(weird)


def test_status_without_any_api_key(tmp_path, monkeypatch):
    from lemory.engine import Engine

    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    v = tmp_path / "v"
    v.mkdir()
    eng = Engine(LemoryConfig(vault=v, data_dir=tmp_path / "d"))
    st = eng.status()  # must not raise
    assert st["documents"] == 0
    # keyless: either search-only, or the on-device answer model when
    # llama.cpp happens to be installed — never a cloud model name
    assert ("local" in st["llm_model"] or "unconfigured" in st["llm_model"]
            or "on-device" in st["llm_model"])
    eng.close()


def test_targeted_sync_edit_add_delete(engine, vault):
    """paths= mode must handle edit, add, and delete without a full scan."""
    engine.index()

    p = vault / "Weekly Log.md"
    p.write_text(p.read_text() + "\n- targeted edit line\n")
    rep = engine.index(paths={"Weekly Log.md"})
    assert rep.updated == 1 and rep.added == 0 and rep.removed == 0

    (vault / "Brand New.md").write_text("about targeted syncing of vaults")
    rep = engine.index(paths={"Brand New.md"})
    assert rep.added == 1
    assert engine.search("targeted syncing", k=3, mode="bm25")

    (vault / "Brand New.md").unlink()
    rep = engine.index(paths={"Brand New.md"})
    assert rep.removed == 1
    assert engine.store.get_doc_by_path("Brand New.md") is None


def test_targeted_sync_does_not_touch_other_docs(engine, vault):
    engine.index()
    before = engine.store.doc_count()
    # delete a file on disk but only sync a different path: no phantom removal
    (vault / "Weekly Log.md").unlink()
    rep = engine.index(paths={"Dana Petrov.md"})
    assert rep.removed == 0
    assert engine.store.doc_count() == before
    # full sync catches up
    rep = engine.index()
    assert rep.removed == 1


def test_alias_edit_triggers_link_rebuild(engine, vault):
    """Adding an alias to note A must resolve other notes' wikilinks to it."""
    (vault / "Pointer2.md").write_text("References [[K8s Cluster]] often.")
    engine.index()
    docs = {d.title: d.id for d in engine.store.all_docs()}
    assert engine.store.neighbors([docs["Pointer2"]])[docs["Pointer2"]] == []

    # alias edit only (update, not add/remove of any file)
    p = vault / "Dana Petrov.md"
    p.write_text("---\naliases: [K8s Cluster]\n---\n" + p.read_text())
    engine.index()
    docs = {d.title: d.id for d in engine.store.all_docs()}
    nbrs = engine.store.neighbors([docs["Pointer2"]])[docs["Pointer2"]]
    assert any(dst == docs["Dana Petrov"] and k == "wiki" for dst, k, _ in nbrs)
