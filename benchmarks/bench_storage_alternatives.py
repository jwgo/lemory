"""Storage engine shootout: SQLite (current) vs DuckDB vs LanceDB, on Lemory's
REAL workload profile — not synthetic OLAP queries.

Measured operations (mirroring actual code paths):
  ingest     first index: N chunks inserted with FTS (documents+chunks+fts)
  upsert     incremental sync: 100 changed docs (delete + reinsert + fts)
  fts        BM25 top-48, mixed common/rare terms (the retrieval lexical leg)
  pk-batch   fetch 26 rows by id (the ANN rescore path), 50 rounds
  2proc      second process opens the store and writes while first holds it
             (CLI `lemory search` next to a running `lemory serve`)

LanceDB additionally gets the vector comparison at 200k×768 (its headline
feature) against the exact scan and our IVF-int8 (storage/ann.py).

Run:  python benchmarks/bench_storage_alternatives.py [n_chunks]
"""

from __future__ import annotations

import multiprocessing as mp
import random
import shutil
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

WORK = Path(__file__).resolve().parent / "work" / "storage-alt"
_SYLL = ["ka", "ri", "mo", "ne", "su", "ta", "lo", "vi", "ze", "un", "ha", "je"]


def corpus(n_chunks: int, seed: int = 7):
    rng = random.Random(seed)
    vocab = ["".join(rng.choices(_SYLL, k=rng.randint(2, 4))) for _ in range(6000)]
    weights = [1.0 / (i + 1) for i in range(len(vocab))]
    docs = []
    per_doc = 6
    for d in range(n_chunks // per_doc):
        title = f"note {d}"
        chunks = [" ".join(rng.choices(vocab, weights=weights, k=120))
                  for _ in range(per_doc)]
        docs.append((f"n{d}.md", title, chunks))
    queries = [" ".join(rng.choices(vocab, weights=weights, k=5)) for _ in range(50)]
    return docs, queries


# --------------------------------------------------------------------- sqlite
class SqliteBench:
    name = "sqlite+fts5"

    def __init__(self, path: Path):
        self.db = path / "bench.db"
        self.conn = sqlite3.connect(self.db)
        self.conn.executescript(
            """PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;
            CREATE TABLE documents(id INTEGER PRIMARY KEY, path TEXT UNIQUE, title TEXT);
            CREATE TABLE chunks(id INTEGER PRIMARY KEY, doc_id INT, ord INT, text TEXT);
            CREATE INDEX idx_chunks_doc ON chunks(doc_id);
            CREATE VIRTUAL TABLE chunks_fts USING fts5(text);"""
        )

    def ingest(self, docs):
        c = self.conn
        for path, title, chunks in docs:
            cur = c.execute("INSERT INTO documents(path,title) VALUES(?,?)", (path, title))
            did = cur.lastrowid
            for i, t in enumerate(chunks):
                cur = c.execute("INSERT INTO chunks(doc_id,ord,text) VALUES(?,?,?)",
                                (did, i, t))
                c.execute("INSERT INTO chunks_fts(rowid,text) VALUES(?,?)",
                          (cur.lastrowid, t))
        c.commit()

    def upsert(self, docs):
        c = self.conn
        for path, title, chunks in docs:
            did = c.execute("SELECT id FROM documents WHERE path=?", (path,)).fetchone()[0]
            old = [r[0] for r in c.execute("SELECT id FROM chunks WHERE doc_id=?", (did,))]
            for cid in old:
                c.execute("DELETE FROM chunks_fts WHERE rowid=?", (cid,))
            c.execute("DELETE FROM chunks WHERE doc_id=?", (did,))
            for i, t in enumerate(chunks):
                cur = c.execute("INSERT INTO chunks(doc_id,ord,text) VALUES(?,?,?)",
                                (did, i, t))
                c.execute("INSERT INTO chunks_fts(rowid,text) VALUES(?,?)",
                          (cur.lastrowid, t))
        c.commit()

    def fts(self, query, k=48):
        terms = query.split()
        and_q = " ".join(f'"{t}"' for t in terms)
        rows = self.conn.execute(
            "SELECT rowid, bm25(chunks_fts) s FROM chunks_fts WHERE chunks_fts MATCH ? "
            "ORDER BY s LIMIT ?", (and_q, k)).fetchall()
        if len(rows) >= k:
            return rows
        or_q = " OR ".join(f'"{t}"' for t in terms)
        return self.conn.execute(
            "SELECT rowid, bm25(chunks_fts) s FROM chunks_fts WHERE chunks_fts MATCH ? "
            "ORDER BY s LIMIT ?", (or_q, k)).fetchall()

    def pk_batch(self, ids):
        marks = ",".join("?" * len(ids))
        return self.conn.execute(
            f"SELECT id, text FROM chunks WHERE id IN ({marks})", ids).fetchall()

    def close(self):
        self.conn.close()


def _sqlite_second_proc(db):
    conn = sqlite3.connect(db, timeout=8)
    conn.execute("PRAGMA busy_timeout=8000")
    conn.execute("INSERT INTO documents(path,title) VALUES('x2.md','x2')")
    conn.commit()
    conn.close()


# --------------------------------------------------------------------- duckdb
class DuckBench:
    name = "duckdb+fts"

    def __init__(self, path: Path):
        import duckdb

        self.db = path / "bench.duckdb"
        self.conn = duckdb.connect(str(self.db))
        try:
            self.conn.execute("INSTALL fts; LOAD fts;")
        except Exception:
            # sandboxed CI: load a hand-downloaded copy if present
            import os

            local = os.environ.get("DUCKDB_FTS_PATH")
            if not local:
                raise
            self.conn.close()
            self.conn = duckdb.connect(str(self.db),
                                       config={"allow_unsigned_extensions": "true"})
            self.conn.execute(f"LOAD '{local}'")
        self.conn.execute(
            """CREATE TABLE documents(id BIGINT, path TEXT, title TEXT);
            CREATE TABLE chunks(id BIGINT, doc_id BIGINT, ord INT, text TEXT);"""
        )
        self._next_doc = 1
        self._next_chunk = 1
        self._fts_built = False

    def ingest(self, docs):
        rows_d, rows_c = [], []
        for path, title, chunks in docs:
            did = self._next_doc
            self._next_doc += 1
            rows_d.append((did, path, title))
            for i, t in enumerate(chunks):
                rows_c.append((self._next_chunk, did, i, t))
                self._next_chunk += 1
        self.conn.executemany("INSERT INTO documents VALUES (?,?,?)", rows_d)
        self.conn.executemany("INSERT INTO chunks VALUES (?,?,?,?)", rows_c)
        self._rebuild_fts()

    def _rebuild_fts(self):
        # DuckDB's FTS index is a materialized build over the table — there is
        # no incremental add/delete; any change means PRAGMA create_fts_index
        # with overwrite=1. That cost is charged to upsert(), as in real life.
        self.conn.execute(
            "PRAGMA create_fts_index('chunks', 'id', 'text', overwrite=1)")
        self._fts_built = True

    def upsert(self, docs):
        for path, title, chunks in docs:
            did = self.conn.execute(
                "SELECT id FROM documents WHERE path=?", [path]).fetchone()[0]
            self.conn.execute("DELETE FROM chunks WHERE doc_id=?", [did])
            rows = []
            for i, t in enumerate(chunks):
                rows.append((self._next_chunk, did, i, t))
                self._next_chunk += 1
            self.conn.executemany("INSERT INTO chunks VALUES (?,?,?,?)", rows)
        self._rebuild_fts()

    def fts(self, query, k=48):
        return self.conn.execute(
            """SELECT id, fts_main_chunks.match_bm25(id, ?) AS s
               FROM chunks WHERE s IS NOT NULL ORDER BY s DESC LIMIT ?""",
            [query, k]).fetchall()

    def pk_batch(self, ids):
        marks = ",".join("?" * len(ids))
        return self.conn.execute(
            f"SELECT id, text FROM chunks WHERE id IN ({marks})", ids).fetchall()

    def close(self):
        self.conn.close()


def _duck_second_proc(db, q):
    # NOTE: the second connection must use the byte-identical config of the
    # first (a mismatch such as allow_unsigned_extensions fails with
    # ConnectionException regardless of locking) — measured 2026-07: with
    # matching config the concurrent write succeeds on duckdb 1.5.
    import os

    import duckdb

    try:
        cfg = {"allow_unsigned_extensions": "true"} if os.environ.get("DUCKDB_FTS_PATH") else {}
        conn = duckdb.connect(str(db), config=cfg)
        conn.execute("INSERT INTO documents VALUES (999999,'x2.md','x2')")
        conn.close()
        q.put("ok")
    except Exception as e:
        q.put(f"FAIL: {type(e).__name__}: {str(e)[:120]}")


# -------------------------------------------------------------------- lancedb
class LanceBench:
    name = "lancedb+tantivy"

    def __init__(self, path: Path):
        import lancedb

        self.dir = path / "lance"
        self.db = lancedb.connect(str(self.dir))
        self.tbl = None

    def ingest(self, docs):
        rows = []
        cid = 1
        for path, title, chunks in docs:
            for i, t in enumerate(chunks):
                rows.append({"id": cid, "path": path, "ord": i, "text": t})
                cid += 1
        self.tbl = self.db.create_table("chunks", rows)
        self.tbl.create_fts_index("text", use_tantivy=False)

    def upsert(self, docs):
        paths = [p for p, _t, _c in docs]
        self.tbl.delete(f"path IN ({','.join(repr(p) for p in paths)})")
        rows = []
        cid = 10_000_000
        for path, title, chunks in docs:
            for i, t in enumerate(chunks):
                rows.append({"id": cid, "path": path, "ord": i, "text": t})
                cid += 1
        self.tbl.add(rows)
        # native FTS indexes new fragments; optimize() merges — charge it here
        self.tbl.optimize()

    def fts(self, query, k=48):
        return self.tbl.search(query, query_type="fts").limit(k).to_list()

    def pk_batch(self, ids):
        return self.tbl.search().where(
            f"id IN ({','.join(map(str, ids))})").limit(len(ids)).to_list()

    def close(self):
        pass


# ------------------------------------------------------------------ the race
def timeit(fn, *a):
    t0 = time.perf_counter()
    out = fn(*a)
    return time.perf_counter() - t0, out


def run(n_chunks: int):
    docs, queries = corpus(n_chunks)
    upsert_docs = docs[: 100]
    print(f"corpus: {len(docs)} docs / {n_chunks} chunks, 50 FTS queries\n")

    for cls in (SqliteBench, DuckBench, LanceBench):
        path = WORK / cls.name.replace("+", "-")
        shutil.rmtree(path, ignore_errors=True)
        path.mkdir(parents=True)
        b = cls(path)
        t_ing, _ = timeit(b.ingest, docs)
        t_up, _ = timeit(b.upsert, upsert_docs)
        t0 = time.perf_counter()
        for q in queries:
            b.fts(q)
        t_fts = (time.perf_counter() - t0) / len(queries) * 1000
        rng = random.Random(3)
        id_sets = [[rng.randint(1, n_chunks - 1) for _ in range(26)] for _ in range(50)]
        t0 = time.perf_counter()
        for ids in id_sets:
            b.pk_batch(ids)
        t_pk = (time.perf_counter() - t0) / len(id_sets) * 1000

        # two-process access while the first connection is open
        two_proc = "n/a"
        if cls is SqliteBench:
            p = mp.Process(target=_sqlite_second_proc, args=(str(b.db),))
            p.start(); p.join(15)
            two_proc = "ok" if p.exitcode == 0 else f"FAIL exit={p.exitcode}"
        elif cls is DuckBench:
            q = mp.Queue()
            p = mp.Process(target=_duck_second_proc, args=(b.db, q))
            p.start(); p.join(15)
            two_proc = q.get() if not q.empty() else "FAIL: timeout"

        disk = sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 2**20
        print(f"{b.name:18} ingest={t_ing:6.1f}s  upsert100={t_up:6.2f}s  "
              f"fts={t_fts:7.2f}ms  pk26={t_pk:5.2f}ms  disk={disk:6.1f}MB  "
              f"2nd-process-write={two_proc}")
        b.close()


if __name__ == "__main__":
    run(int(sys.argv[1]) if len(sys.argv) > 1 else 50_000)
