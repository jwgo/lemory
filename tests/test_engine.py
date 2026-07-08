import time


def test_index_and_counts(engine):
    rep = engine.index()
    assert rep.added == 4
    assert engine.store.doc_count() == 4
    assert engine.store.chunk_count() >= 4
    st = engine.status()
    assert st["documents"] == 4


def test_incremental_sync_uses_cache(engine, vault):
    rep1 = engine.index()
    assert rep1.embedded > 0
    rep2 = engine.index()
    assert rep2.added == 0 and rep2.updated == 0 and rep2.unchanged == 4
    assert rep2.embedded == 0  # nothing re-embedded

    # editing one file only reindexes that file, cache covers unchanged chunks
    p = vault / "Weekly Log.md"
    p.write_text(p.read_text() + "\n- New line about latency budgets\n")
    rep3 = engine.index()
    assert rep3.updated == 1 and rep3.added == 0


def test_delete_removes_doc(engine, vault):
    engine.index()
    (vault / "Weekly Log.md").unlink()
    rep = engine.index()
    assert rep.removed == 1
    assert engine.store.doc_count() == 3


def test_graph_links_wiki_and_mention(engine):
    engine.index()
    store = engine.store
    docs = {d.title: d.id for d in store.all_docs()}
    nbrs = store.neighbors([docs["Mercury Initiative"]])[docs["Mercury Initiative"]]
    kinds = {(dst, kind) for dst, kind, _ in nbrs}
    # explicit wikilink to Dana Petrov
    assert (docs["Dana Petrov"], "wiki") in kinds
    # unlinked mention: Atlas Notes mentions "Mercury Initiative"
    assert any(dst == docs["Atlas Notes"] for dst, _, _ in nbrs)


def test_alias_title_map(engine):
    engine.index()
    tm = engine.store.title_map()
    assert tm["project mercury"] == tm["mercury initiative"]


def test_search_direct_hit(engine):
    engine.index()
    hits = engine.search("what price per compute-minute did we decide", k=4)
    assert hits, "no hits"
    assert hits[0].title == "Mercury Initiative"
    assert "0.04" in hits[0].text


def test_search_multihop_graph_expansion(engine):
    engine.index()
    # "Mercury Initiative leader's favorite database" — answer lives in Dana's
    # note, which shares few tokens with the query; graph should surface it.
    hits_graph = engine.search("Mercury Initiative lead favorite database", k=6, graph=True)
    titles = [h.title for h in hits_graph]
    assert "Dana Petrov" in titles


def test_modes_run(engine):
    engine.index()
    for mode in ("hybrid", "vector", "bm25"):
        assert engine.search("pricing pilot", k=3, mode=mode)


def test_ask_returns_sources(engine):
    engine.index()
    ans = engine.ask("what is atlas?")
    assert ans.text == "fake answer [1]"
    assert ans.sources


def test_watch_debounce_smoke(engine, vault):
    # not running the watcher loop; just ensure indexer handles rapid re-sync
    engine.index()
    (vault / "New Note.md").write_text("Fresh note about quantum kettles")
    t0 = time.time()
    rep = engine.index()
    assert rep.added == 1
    assert time.time() - t0 < 10
