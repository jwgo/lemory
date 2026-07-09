"""Reliability: corrupted index recovery, concurrent access, date frontmatter."""

from __future__ import annotations

import sqlite3
import threading

from lemory.storage.sqlite_store import Store


def test_corrupt_db_quarantined_and_rebuilt(tmp_path):
    db = tmp_path / "lemory.db"
    db.write_bytes(b"this is definitely not a sqlite database " * 40)
    store = Store(db)  # must not raise
    assert store.doc_count() == 0
    assert (tmp_path / "lemory.corrupt").exists()  # original preserved for forensics
    store.close()


def test_concurrent_writers_do_not_lock_error(tmp_path):
    db = tmp_path / "lemory.db"
    Store(db).close()
    errors: list[Exception] = []

    def writer(n: int):
        try:
            s = Store(db)
            for i in range(20):
                s.set_meta(f"k{n}-{i}", "v")
            s.close()
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors


def test_date_frontmatter_indexes_without_crash(engine, vault):
    (vault / "Daily Note.md").write_text(
        "---\ndate: 2026-07-08\ncreated: 2026-07-08 09:30:00\ntags: [daily]\n---\n"
        "Wrote the quarterly summary today.",
        encoding="utf-8",
    )
    rep = engine.index()
    assert not rep.errors
    hits = engine.search("quarterly summary", k=3)
    assert any(h.title == "Daily Note" for h in hits)
    # and the frontmatter date became the note's doc_date
    doc = next(d for d in engine.store.all_docs() if d.title == "Daily Note")
    from datetime import datetime
    ts = engine.store.doc_dates()[doc.id]
    assert datetime.fromtimestamp(ts).date().isoformat() == "2026-07-08"


def test_second_store_sees_first_stores_writes(tmp_path):
    db = tmp_path / "lemory.db"
    a = Store(db)
    a.set_meta("hello", "world")
    b = Store(db)
    assert b.get_meta("hello") == "world"
    a.close(), b.close()
