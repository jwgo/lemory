"""Lemory storage: one SQLite file + an in-memory vector matrix.

Tables
------
documents   one row per note (path, title, hash, tags, frontmatter)
chunks      heading-aware chunks, with embedded vector as BLOB
chunks_fts  FTS5 index over chunk text for BM25
links       note-level graph edges: wikilink / mention / entity
entities    optional LLM-extracted entities (cognify-style enrichment)
embed_cache content-hash -> vector, so re-indexing never re-pays the API

Personal-vault scale (up to ~100k chunks) makes exact cosine over a numpy
matrix both faster and dramatically simpler than running a vector DB.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

import numpy as np

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    mtime REAL NOT NULL DEFAULT 0,
    tags TEXT NOT NULL DEFAULT '[]',
    frontmatter TEXT NOT NULL DEFAULT '{}',
    wikilinks TEXT NOT NULL DEFAULT '[]',
    indexed_at REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_documents_title ON documents(title);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ord INTEGER NOT NULL,
    heading TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL,
    vec BLOB
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text, title, heading, tokenize='porter unicode61'
);

CREATE TABLE IF NOT EXISTS links (
    src_doc INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    dst_doc INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,             -- 'wiki' | 'mention' | 'entity'
    weight REAL NOT NULL DEFAULT 1.0,
    PRIMARY KEY (src_doc, dst_doc, kind)
);
CREATE INDEX IF NOT EXISTS idx_links_src ON links(src_doc);
CREATE INDEX IF NOT EXISTS idx_links_dst ON links(dst_doc);

CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL
);
CREATE TABLE IF NOT EXISTS entity_mentions (
    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    PRIMARY KEY (entity_id, doc_id)
);

CREATE TABLE IF NOT EXISTS embed_cache (
    key TEXT PRIMARY KEY,           -- sha256(model|dim|task|text)
    vec BLOB NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


@dataclass
class ChunkHit:
    chunk_id: int
    doc_id: int
    path: str
    title: str
    heading: str
    text: str
    score: float


@dataclass
class DocRecord:
    id: int
    path: str
    title: str
    content_hash: str
    mtime: float
    tags: list[str] = field(default_factory=list)


_HANGUL_RUN = re.compile(r"[가-힣]{2,}")


def hangul_bigrams(text: str) -> list[str]:
    """Character bigrams of every Hangul run (CJK-analyzer style).

    Korean is agglutinative — '윤하준가'(name+조사) never token-matches
    '윤하준' under unicode61. Indexing and querying Hangul as overlapping
    bigrams ('윤하 하준 준가') restores lexical matching without a
    morphology dictionary.
    """
    grams: list[str] = []
    for run in _HANGUL_RUN.findall(text):
        grams.extend(run[i : i + 2] for i in range(len(run) - 1))
    return grams


def fts_index_text(text: str) -> str:
    """Text as stored in the FTS index: original + Hangul bigrams.

    The FTS table is match-only (display text comes from `chunks`), so
    appending bigrams is invisible to users.
    """
    grams = hangul_bigrams(text)
    return text if not grams else f"{text}\n{' '.join(grams)}"


def _fts_escape(query: str) -> str:
    """Turn free text into a safe FTS5 OR-query of quoted terms
    (plus Hangul-bigram terms so 조사-suffixed words still match)."""
    terms = [t.replace('"', "") for t in query.split()]
    terms = [t for t in terms if t.strip()][:16]  # cap pathological queries
    grams = hangul_bigrams(" ".join(terms))[:48]
    all_terms = terms + grams
    if not all_terms:
        return '""'
    return " OR ".join(f'"{t}"' for t in all_terms)


class Store:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._matrix_lock = threading.Lock()
        self._matrix: Optional[np.ndarray] = None  # [n, dim] float32, L2-normalized
        self._matrix_chunk_ids: Optional[np.ndarray] = None
        self._matrix_pos: dict[int, int] = {}  # chunk_id -> row
        self._lexicon: Optional[dict[str, int]] = None  # FTS term -> doc count
        self._dirty = True
        with self.conn() as c:
            c.executescript(SCHEMA)
            # migrate pre-wikilinks databases in place
            cols = {r["name"] for r in c.execute("PRAGMA table_info(documents)")}
            if "wikilinks" not in cols:
                c.execute("ALTER TABLE documents ADD COLUMN wikilinks TEXT NOT NULL DEFAULT '[]'")

    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.db_path, check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA foreign_keys=ON")
            c.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = c
        return c

    # ------------------------------------------------------------- documents
    def get_doc_by_path(self, path: str) -> Optional[DocRecord]:
        row = self.conn().execute("SELECT * FROM documents WHERE path=?", (path,)).fetchone()
        return self._doc(row) if row else None

    def all_docs(self) -> list[DocRecord]:
        rows = self.conn().execute("SELECT * FROM documents").fetchall()
        return [self._doc(r) for r in rows]

    @staticmethod
    def _doc(row: sqlite3.Row) -> DocRecord:
        return DocRecord(
            id=row["id"], path=row["path"], title=row["title"],
            content_hash=row["content_hash"], mtime=row["mtime"],
            tags=json.loads(row["tags"]),
        )

    def _mark_dirty(self) -> None:
        """Invalidate the matrix cache. Must be called AFTER the write commits;
        taking the lock orders it against any in-flight _ensure_matrix so the
        invalidation can never be lost."""
        with self._matrix_lock:
            self._dirty = True
            self._lexicon = None

    def _upsert_document_tx(
        self, c: sqlite3.Connection, path: str, title: str, content_hash: str,
        mtime: float, tags: list[str], frontmatter: dict, indexed_at: float,
        wikilinks: list[str] | None,
    ) -> int:
        c.execute(
            """INSERT INTO documents(path,title,content_hash,mtime,tags,frontmatter,wikilinks,indexed_at)
               VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(path) DO UPDATE SET title=excluded.title,
                 content_hash=excluded.content_hash, mtime=excluded.mtime,
                 tags=excluded.tags, frontmatter=excluded.frontmatter,
                 wikilinks=excluded.wikilinks, indexed_at=excluded.indexed_at""",
            (path, title, content_hash, mtime, json.dumps(tags), json.dumps(frontmatter),
             json.dumps(wikilinks or []), indexed_at),
        )
        row = c.execute("SELECT id FROM documents WHERE path=?", (path,)).fetchone()
        return int(row["id"])

    def _replace_chunks_tx(
        self, c: sqlite3.Connection, doc_id: int, title: str,
        chunks: list[tuple[str, str]], vectors: Optional[np.ndarray],
    ) -> list[int]:
        old = [r["id"] for r in c.execute("SELECT id FROM chunks WHERE doc_id=?", (doc_id,))]
        for cid in old:
            c.execute("DELETE FROM chunks_fts WHERE rowid=?", (cid,))
        c.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
        ids: list[int] = []
        for i, (heading, text) in enumerate(chunks):
            vec_blob = vectors[i].astype(np.float32).tobytes() if vectors is not None else None
            cur = c.execute(
                "INSERT INTO chunks(doc_id, ord, heading, text, vec) VALUES(?,?,?,?,?)",
                (doc_id, i, heading, text, vec_blob),
            )
            cid = int(cur.lastrowid)
            ids.append(cid)
            c.execute(
                "INSERT INTO chunks_fts(rowid, text, title, heading) VALUES(?,?,?,?)",
                (cid, fts_index_text(text), fts_index_text(title), heading),
            )
        return ids

    def upsert_document(
        self, path: str, title: str, content_hash: str, mtime: float,
        tags: list[str], frontmatter: dict, indexed_at: float,
        wikilinks: list[str] | None = None,
    ) -> int:
        c = self.conn()
        doc_id = self._upsert_document_tx(
            c, path, title, content_hash, mtime, tags, frontmatter, indexed_at, wikilinks)
        c.commit()
        return doc_id

    def store_note(
        self, path: str, title: str, content_hash: str, mtime: float,
        tags: list[str], frontmatter: dict, indexed_at: float,
        wikilinks: list[str] | None,
        chunks: list[tuple[str, str]], vectors: Optional[np.ndarray],
    ) -> int:
        """Atomically write a note's document row AND its chunks in one
        transaction, so a crash can never leave the hash committed while the
        chunks are stale (which incremental sync would then skip forever)."""
        c = self.conn()
        try:
            doc_id = self._upsert_document_tx(
                c, path, title, content_hash, mtime, tags, frontmatter, indexed_at, wikilinks)
            self._replace_chunks_tx(c, doc_id, title, chunks, vectors)
            c.commit()
        except BaseException:
            c.rollback()
            raise
        self._mark_dirty()
        return doc_id

    def delete_document(self, path: str) -> None:
        c = self.conn()
        row = c.execute("SELECT id FROM documents WHERE path=?", (path,)).fetchone()
        if not row:
            return
        doc_id = row["id"]
        chunk_ids = [r["id"] for r in c.execute("SELECT id FROM chunks WHERE doc_id=?", (doc_id,))]
        for cid in chunk_ids:
            c.execute("DELETE FROM chunks_fts WHERE rowid=?", (cid,))
        c.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        c.commit()
        self._mark_dirty()

    # ---------------------------------------------------------------- chunks
    def replace_chunks(
        self, doc_id: int, title: str,
        chunks: list[tuple[str, str]],  # (heading, text)
        vectors: Optional[np.ndarray],
    ) -> list[int]:
        c = self.conn()
        ids = self._replace_chunks_tx(c, doc_id, title, chunks, vectors)
        c.commit()
        self._mark_dirty()
        return ids

    def chunk_count(self) -> int:
        return int(self.conn().execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"])

    def doc_count(self) -> int:
        return int(self.conn().execute("SELECT COUNT(*) AS n FROM documents").fetchone()["n"])

    def get_chunks(self, chunk_ids: Iterable[int]) -> dict[int, ChunkHit]:
        ids = list(chunk_ids)
        if not ids:
            return {}
        q = ",".join("?" * len(ids))
        rows = self.conn().execute(
            f"""SELECT ch.id, ch.doc_id, ch.heading, ch.text, d.path, d.title
                FROM chunks ch JOIN documents d ON d.id = ch.doc_id
                WHERE ch.id IN ({q})""",
            ids,
        ).fetchall()
        return {
            r["id"]: ChunkHit(
                chunk_id=r["id"], doc_id=r["doc_id"], path=r["path"], title=r["title"],
                heading=r["heading"], text=r["text"], score=0.0,
            )
            for r in rows
        }

    def doc_chunk_ids(self, doc_id: int) -> list[int]:
        return [r["id"] for r in self.conn().execute(
            "SELECT id FROM chunks WHERE doc_id=? ORDER BY ord", (doc_id,))]

    def doc_chunk_ids_many(self, doc_ids: list[int]) -> dict[int, list[int]]:
        if not doc_ids:
            return {}
        q = ",".join("?" * len(doc_ids))
        out: dict[int, list[int]] = {d: [] for d in doc_ids}
        for r in self.conn().execute(
            f"SELECT id, doc_id FROM chunks WHERE doc_id IN ({q}) ORDER BY ord", doc_ids
        ):
            out[r["doc_id"]].append(r["id"])
        return out

    # ----------------------------------------------------------------- links
    def replace_links(self, src_doc: int, edges: list[tuple[int, str, float]]) -> None:
        c = self.conn()
        c.execute("DELETE FROM links WHERE src_doc=?", (src_doc,))
        c.executemany(
            "INSERT OR REPLACE INTO links(src_doc, dst_doc, kind, weight) VALUES(?,?,?,?)",
            [(src_doc, dst, kind, w) for dst, kind, w in edges],
        )
        c.commit()

    def neighbors(self, doc_ids: Iterable[int]) -> dict[int, list[tuple[int, str, float]]]:
        """Undirected 1-hop neighborhood: doc -> [(neighbor, kind, weight)]."""
        ids = list(set(doc_ids))
        if not ids:
            return {}
        q = ",".join("?" * len(ids))
        out: dict[int, list[tuple[int, str, float]]] = {i: [] for i in ids}
        for r in self.conn().execute(
            f"SELECT src_doc, dst_doc, kind, weight FROM links WHERE src_doc IN ({q}) OR dst_doc IN ({q})",
            ids + ids,
        ):
            if r["src_doc"] in out:
                out[r["src_doc"]].append((r["dst_doc"], r["kind"], r["weight"]))
            if r["dst_doc"] in out and r["src_doc"] != r["dst_doc"]:
                out[r["dst_doc"]].append((r["src_doc"], r["kind"], r["weight"]))
        return out

    def link_count(self) -> int:
        return int(self.conn().execute("SELECT COUNT(*) AS n FROM links").fetchone()["n"])

    def doc_wikilinks(self) -> dict[int, list[str]]:
        """doc_id -> raw wikilink targets, as stored at index time."""
        out: dict[int, list[str]] = {}
        for r in self.conn().execute("SELECT id, wikilinks FROM documents"):
            try:
                out[r["id"]] = json.loads(r["wikilinks"])
            except json.JSONDecodeError:
                out[r["id"]] = []
        return out

    # -------------------------------------------------------------- entities
    def add_entity_mentions(self, doc_id: int, names: list[str]) -> None:
        c = self.conn()
        for name in names:
            name = name.strip()
            if not name:
                continue
            c.execute("INSERT OR IGNORE INTO entities(name) VALUES(?)", (name.lower(),))
            row = c.execute("SELECT id FROM entities WHERE name=?", (name.lower(),)).fetchone()
            c.execute(
                "INSERT OR IGNORE INTO entity_mentions(entity_id, doc_id) VALUES(?,?)",
                (row["id"], doc_id),
            )
        c.commit()

    def rebuild_entity_links(self) -> int:
        """Create 'entity' edges between docs sharing an extracted entity."""
        c = self.conn()
        c.execute("DELETE FROM links WHERE kind='entity'")
        rows = c.execute(
            """SELECT a.doc_id AS s, b.doc_id AS d, COUNT(*) AS n
               FROM entity_mentions a JOIN entity_mentions b
                 ON a.entity_id = b.entity_id AND a.doc_id < b.doc_id
               GROUP BY a.doc_id, b.doc_id"""
        ).fetchall()
        for r in rows:
            w = min(1.0, 0.4 + 0.15 * r["n"])
            c.execute(
                "INSERT OR REPLACE INTO links(src_doc, dst_doc, kind, weight) VALUES(?,?,?,?)",
                (r["s"], r["d"], "entity", w),
            )
        c.commit()
        return len(rows)

    # ------------------------------------------------------------ embed cache
    @staticmethod
    def cache_key(model: str, dim: int, task: str, text: str) -> str:
        h = hashlib.sha256(f"{model}|{dim}|{task}|".encode() + text.encode()).hexdigest()
        return h

    def cache_get_many(self, keys: list[str]) -> dict[str, np.ndarray]:
        if not keys:
            return {}
        out: dict[str, np.ndarray] = {}
        c = self.conn()
        for i in range(0, len(keys), 500):
            batch = keys[i : i + 500]
            q = ",".join("?" * len(batch))
            for r in c.execute(f"SELECT key, vec FROM embed_cache WHERE key IN ({q})", batch):
                out[r["key"]] = np.frombuffer(r["vec"], dtype=np.float32)
        return out

    def cache_put_many(self, items: dict[str, np.ndarray]) -> None:
        c = self.conn()
        c.executemany(
            "INSERT OR REPLACE INTO embed_cache(key, vec) VALUES(?,?)",
            [(k, v.astype(np.float32).tobytes()) for k, v in items.items()],
        )
        c.commit()

    # ------------------------------------------------------------ vector index
    def _ensure_matrix(self) -> tuple[np.ndarray, np.ndarray, dict[int, int]]:
        """Return an atomic (matrix, chunk_ids, id->row) snapshot. The three
        parts are captured together under the lock so concurrent rebuilds can
        never pair a new position map with an old matrix (or vice versa)."""
        with self._matrix_lock:
            if not self._dirty and self._matrix is not None:
                return self._matrix, self._matrix_chunk_ids, self._matrix_pos
            rows = self.conn().execute(
                "SELECT id, vec FROM chunks WHERE vec IS NOT NULL ORDER BY id"
            ).fetchall()
            if not rows:
                self._matrix = np.zeros((0, 1), dtype=np.float32)
                self._matrix_chunk_ids = np.zeros((0,), dtype=np.int64)
                self._matrix_pos = {}
            else:
                vecs = [np.frombuffer(r["vec"], dtype=np.float32) for r in rows]
                self._matrix = np.vstack(vecs)
                self._matrix_chunk_ids = np.array([r["id"] for r in rows], dtype=np.int64)
                self._matrix_pos = {int(cid): i for i, cid in enumerate(self._matrix_chunk_ids)}
            self._dirty = False
            return self._matrix, self._matrix_chunk_ids, self._matrix_pos

    def vector_search(self, query_vec: np.ndarray, k: int) -> list[tuple[int, float]]:
        matrix, ids, _pos = self._ensure_matrix()
        if matrix.shape[0] == 0 or matrix.shape[1] != query_vec.shape[0]:
            # dim mismatch = embed model/provider changed without `index --full`
            return []
        sims = matrix @ query_vec.astype(np.float32)
        k = min(k, len(ids))
        top = np.argpartition(-sims, k - 1)[:k]
        top = top[np.argsort(-sims[top])]
        return [(int(ids[i]), float(sims[i])) for i in top]

    def chunk_sims(self, query_vec: np.ndarray, chunk_ids: list[int]) -> dict[int, float]:
        """Cosine similarity of specific chunks against a query vector."""
        matrix, _ids, pos = self._ensure_matrix()
        if matrix.shape[0] == 0 or matrix.shape[1] != query_vec.shape[0] or not chunk_ids:
            return {}
        wanted = [(cid, pos[cid]) for cid in chunk_ids if cid in pos]
        if not wanted:
            return {}
        rows = np.array([i for _, i in wanted])
        sims = matrix[rows] @ query_vec.astype(np.float32)
        return {cid: float(s) for (cid, _), s in zip(wanted, sims)}

    # ----------------------------------------------------------------- BM25
    def bm25_search(self, query: str, k: int) -> list[tuple[int, float]]:
        match = _fts_escape(query)
        try:
            rows = self.conn().execute(
                """SELECT rowid, bm25(chunks_fts, 1.0, 0.6, 0.4) AS s
                   FROM chunks_fts WHERE chunks_fts MATCH ?
                   ORDER BY s LIMIT ?""",
                (match, k),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        # bm25() returns lower-is-better; flip sign so higher is better
        return [(int(r["rowid"]), -float(r["s"])) for r in rows]

    # ------------------------------------------------------------ typo lexicon
    _LEX_WORD_RE = re.compile(r"[A-Za-z]{3,}")

    def lexicon(self) -> dict[str, int]:
        """Surface-form vocabulary of the indexed text (word -> frequency),
        cached until the index changes. Unstemmed on purpose: typo correction
        compares the user's raw word against real words, then FTS stems the
        replacement normally. Pure local scan — no API involved."""
        with self._matrix_lock:
            lex = self._lexicon
        if lex is not None:
            return lex
        counts: dict[str, int] = {}
        for row in self.conn().execute(
            "SELECT ch.text AS text, d.title AS title FROM chunks ch "
            "JOIN documents d ON d.id = ch.doc_id"
        ):
            for w in self._LEX_WORD_RE.findall(row["text"] + " " + row["title"]):
                lw = w.lower()
                counts[lw] = counts.get(lw, 0) + 1
        with self._matrix_lock:
            self._lexicon = counts
        return counts

    def token_known(self, token: str) -> bool:
        """True if the token (after FTS stemming) matches anything indexed."""
        safe = token.replace('"', "")
        if not safe:
            return True
        try:
            row = self.conn().execute(
                'SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ? LIMIT 1',
                (f'"{safe}"',),
            ).fetchone()
        except sqlite3.OperationalError:
            return True  # never "correct" what we can't verify
        return row is not None

    # ------------------------------------------------------------------ misc
    def title_map(self) -> dict[str, int]:
        """lowercased title -> doc_id (includes aliases from frontmatter)."""
        out: dict[str, int] = {}
        for r in self.conn().execute("SELECT id, title, frontmatter FROM documents"):
            out[r["title"].lower()] = r["id"]
            try:
                fm = json.loads(r["frontmatter"])
                aliases = fm.get("aliases") or fm.get("alias") or []
                if isinstance(aliases, str):
                    aliases = [aliases]
                for a in aliases:
                    if isinstance(a, str) and a.strip():
                        out[a.strip().lower()] = r["id"]
            except (json.JSONDecodeError, AttributeError):
                pass
        return out

    def set_meta(self, key: str, value: str) -> None:
        c = self.conn()
        c.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?,?)", (key, value))
        c.commit()

    def get_meta(self, key: str) -> Optional[str]:
        row = self.conn().execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def close(self) -> None:
        c = getattr(self._local, "conn", None)
        if c is not None:
            c.close()
            self._local.conn = None
