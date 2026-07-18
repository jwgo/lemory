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
import logging
import re
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

import numpy as np

log = logging.getLogger("lemory.store")

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

CREATE TABLE IF NOT EXISTS note_hits (
    doc_id INTEGER PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    hits INTEGER NOT NULL DEFAULT 0,
    last_hit REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS event_log (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,               -- 'search' | 'ask' | 'memory' | 'append' | 'trash'
    client TEXT NOT NULL DEFAULT '',  -- who passed through: cli / http / mcp / ...
    query TEXT,                       -- for search/ask
    path TEXT,                        -- for memory/append/trash
    detail TEXT                       -- JSON: top result paths, note title, ...
);
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
    doc_date: float = 0.0  # epoch seconds; see retrieval.temporal.doc_date

    def subheading(self) -> str:
        """The section heading with the note title stripped off. Headings are
        stored as `Title > Section` breadcrumbs; showing the title again next
        to the note name is noise. Returns "" for a whole-note / title-only
        heading."""
        if not self.heading or self.heading == self.title:
            return ""
        prefix = self.title + " > "
        return self.heading[len(prefix):] if self.heading.startswith(prefix) else self.heading


@dataclass
class DocRecord:
    id: int
    path: str
    title: str
    content_hash: str
    mtime: float
    tags: list[str] = field(default_factory=list)


_HANGUL_RUN = re.compile(r"[가-힣]+")
# 가나(ぁ-ヿ)·CJK 한자(一-鿿)까지: 한국어 위키는 표기 테이블에 일본어/중국어
# 명칭을 함께 적고, unicode61은 스크립트가 섞인 연속 런("ナイトロード나이트로드")
# 을 한 토큰으로 붙여 버려서 바이그램 없이는 영원히 매치되지 않는다
_CJK_RUN = re.compile(r"[가-힣]+|[ぁ-ヿ]+|[一-鿿]+")

# high-frequency single-syllable suffixes: 조사 that attach to single-syllable
# nouns ('윌의', '책은') and verbal 어미 on 2-syllable conjugations ('읽던' /
# '읽는' share only the stem syllable, which bigrams can't see)
_SINGLE_PARTICLES = set("의은는이가를을에와과도만로써서던고기다지요며자게니")


def hangul_bigrams(text: str) -> list[str]:
    """Character unigrams + bigrams of every Hangul run (CJK-analyzer style).

    Korean is agglutinative — '윤하준가'(name+조사) never token-matches
    '윤하준' under unicode61. Indexing and querying Hangul as overlapping
    bigrams ('윤하 하준 준가') restores lexical matching without a
    morphology dictionary. Unigrams are included too because single-syllable
    words are common ('책', '집', '차') and would otherwise never match their
    particle-suffixed forms ('책은') — BM25's IDF keeps frequent single
    syllables from dominating.
    """
    grams: list[str] = []
    for run in _CJK_RUN.findall(text):
        grams.extend(run)
        grams.extend(run[i : i + 2] for i in range(len(run) - 1))
    return grams


def fts_index_text(text: str) -> str:
    """Text as stored in the FTS index: original + Hangul bigrams.

    The FTS table is match-only (display text comes from `chunks`), so
    appending bigrams is invisible to users.
    """
    grams = hangul_bigrams(text)
    return text if not grams else f"{text}\n{' '.join(grams)}"


def query_hangul_grams(text: str) -> list[str]:
    """Query-side Hangul grams: bigrams for multi-syllable runs, the unigram
    only for single-syllable runs ('책').

    The index stores unigrams AND bigrams (`hangul_bigrams`), but putting
    unigrams in the OR-query is what melts big Korean corpora: '이'/'은'/'의'
    match nearly every row, forcing BM25 to score the whole table (~270 ms on
    the 33k-chunk namuwiki corpus). Every occurrence of a multi-syllable word
    already contains that word's bigrams, so dropping its unigrams from the
    QUERY loses only single-shared-syllable noise matches whose IDF weight
    was ~0 anyway."""
    grams: list[str] = []
    for run in _CJK_RUN.findall(text):
        if len(run) == 1:
            grams.append(run)
        else:
            grams.extend(run[i : i + 2] for i in range(len(run) - 1))
            if len(run) == 2 and run[1] in _SINGLE_PARTICLES:
                # '윌의'/'책은': a single-syllable noun + 조사 — the stem
                # unigram is the only token that can reach the noun's own
                # mentions ('윌'). Bounded reintroduction: only 2-syllable
                # runs ending in a particle, so interior syllables of long
                # words (the row-melters '이/은/의') stay out of the query.
                grams.append(run[0])
    return grams


def _fts_escape(query: str) -> str:
    """Turn free text into a safe FTS5 OR-query of quoted terms
    (plus Hangul-bigram terms so 조사-suffixed words still match)."""
    terms = [t.replace('"', "") for t in query.split()]
    terms = [t for t in terms if t.strip()][:16]  # cap pathological queries
    grams = query_hangul_grams(" ".join(terms))[:48]
    all_terms = terms + grams
    if not all_terms:
        return '""'
    return " OR ".join(f'"{t}"' for t in all_terms)


def _loads_or(raw, default):
    """json.loads that returns `default` on any malformed value — the index is
    derived data, so a corrupt cell must degrade gracefully, never crash a read."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default


class Store:
    def __init__(self, db_path: Path | str,
                 ann_threshold: int = 20_000, ann_nprobe: int = 48):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # above `ann_threshold` embedded chunks, vector search switches from
        # the exact float32 scan to an int8 IVF index (storage/ann.py):
        # small vaults keep exact behaviour, huge vaults keep flat latency
        self.ann_threshold = ann_threshold
        self.ann_nprobe = ann_nprobe
        self._ann = None  # Optional[IVFFlatIndex], built lazily
        self._ann_build_lock = threading.Lock()  # serializes builds, held off reads
        self._ann_failed = False  # a build OOM'd/errored → stop retrying this session
        self._local = threading.local()
        self._matrix_lock = threading.Lock()
        self._matrix: Optional[np.ndarray] = None  # [n, dim] float32, L2-normalized
        self._matrix_chunk_ids: Optional[np.ndarray] = None
        self._matrix_pos: dict[int, int] = {}  # chunk_id -> row
        self._lexicon: Optional[dict[str, int]] = None
        self._lexicon_buckets: Optional[dict] = None  # FTS term -> doc count
        self._doc_dates: Optional[dict[int, float]] = None  # doc_id -> epoch
        self._dirty = True
        try:
            with self.conn() as c:
                c.executescript(SCHEMA)
                # migrate pre-wikilinks databases in place
                cols = {r["name"] for r in c.execute("PRAGMA table_info(documents)")}
                if "wikilinks" not in cols:
                    c.execute("ALTER TABLE documents ADD COLUMN wikilinks TEXT NOT NULL DEFAULT '[]'")
        except sqlite3.DatabaseError as e:
            # the vault is the source of truth — a corrupted index is
            # recoverable by rebuilding, never a reason to be dead in the water
            log.warning("index database unreadable (%s); moving it aside and rebuilding", e)
            self.close()
            quarantine = self.db_path.with_suffix(".corrupt")
            for suffix in ("", "-wal", "-shm"):
                p = Path(str(self.db_path) + suffix)
                if p.exists():
                    p.replace(Path(str(quarantine) + suffix))
            with self.conn() as c:
                c.executescript(SCHEMA)

    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.db_path, check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA foreign_keys=ON")
            c.execute("PRAGMA synchronous=NORMAL")
            # a second lemory process (CLI next to a running server) must wait
            # for write locks instead of failing with 'database is locked'
            c.execute("PRAGMA busy_timeout=8000")
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
            tags=_loads_or(row["tags"], []),
        )

    def _mark_dirty(self) -> None:
        """Invalidate the matrix cache. Must be called AFTER the write commits;
        taking the lock orders it against any in-flight _ensure_matrix so the
        invalidation can never be lost."""
        with self._matrix_lock:
            self._dirty = True
            self._ann = None
            self._ann_failed = False  # data changed; a fresh build may fit now
            self._lexicon = None
            self._lexicon_buckets = None
            self._doc_dates = None

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
            (path, title, content_hash, mtime, json.dumps(tags),
             # default=str: YAML frontmatter commonly contains datetime.date
             # values (`date: 2026-07-08`), which plain json.dumps rejects
             json.dumps(frontmatter, default=str),
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
        dates = self.doc_dates()
        return {
            r["id"]: ChunkHit(
                chunk_id=r["id"], doc_id=r["doc_id"], path=r["path"], title=r["title"],
                heading=r["heading"], text=r["text"], score=0.0,
                doc_date=dates.get(r["doc_id"], 0.0),
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

    def docs_matching(self, tags: list[str] | None = None,
                      folders: list[str] | None = None) -> set[int]:
        """Doc ids satisfying scope filters: ALL tags present (AND), path under
        ANY of the folders (OR). Case-insensitive; folders match any depth."""
        want_tags = [t.lower().lstrip("#") for t in (tags or []) if t.strip()]
        want_dirs = [f.lower().strip().strip("/") for f in (folders or []) if f.strip()]
        out: set[int] = set()
        for r in self.conn().execute("SELECT id, path, tags FROM documents"):
            if want_tags:
                have = {t.lower().lstrip("#") for t in _loads_or(r["tags"], [])}
                if not all(t in have for t in want_tags):
                    continue
            if want_dirs:
                hay = "/" + r["path"].lower()
                if not any(f"/{d}/" in hay for d in want_dirs):
                    continue
            out.add(r["id"])
        return out

    def all_links(self) -> list[tuple[int, int, str, float]]:
        """Every graph edge (src, dst, kind, weight) — the `lemory graph`
        export and any future whole-graph consumer."""
        return [(r["src_doc"], r["dst_doc"], r["kind"], r["weight"])
                for r in self.conn().execute(
                    "SELECT src_doc, dst_doc, kind, weight FROM links")]

    def mention_edges(self, doc_id: int | None = None) -> list[tuple[int, int, float]]:
        """Unlinked-mention edges (src, dst, weight). These exist ONLY where
        no wiki edge covers the same pair (indexer merge rule), so every row
        is a live [[link]] suggestion. With doc_id: both directions for that
        note."""
        if doc_id is None:
            q = "SELECT src_doc, dst_doc, weight FROM links WHERE kind='mention'"
            args: tuple = ()
        else:
            q = ("SELECT src_doc, dst_doc, weight FROM links WHERE kind='mention' "
                 "AND (src_doc=? OR dst_doc=?)")
            args = (doc_id, doc_id)
        return [(r["src_doc"], r["dst_doc"], r["weight"])
                for r in self.conn().execute(q, args)]

    def link_degrees(self) -> dict[int, int]:
        """doc_id -> total link degree (in + out), for hub detection."""
        out: dict[int, int] = {}
        for r in self.conn().execute(
                "SELECT src_doc AS a, dst_doc AS b FROM links"):
            out[r["a"]] = out.get(r["a"], 0) + 1
            out[r["b"]] = out.get(r["b"], 0) + 1
        return out

    # ------------------------------------------------------- console queries
    def doc_overview_rows(self) -> list[dict]:
        """Per-note console row: path, title, tags, mtime, chunk/link counts."""
        c = self.conn()
        chunks = {r["d"]: r["n"] for r in c.execute(
            "SELECT doc_id AS d, COUNT(*) AS n FROM chunks GROUP BY doc_id")}
        outl = {r["d"]: r["n"] for r in c.execute(
            "SELECT src_doc AS d, COUNT(*) AS n FROM links GROUP BY src_doc")}
        inl = {r["d"]: r["n"] for r in c.execute(
            "SELECT dst_doc AS d, COUNT(*) AS n FROM links GROUP BY dst_doc")}
        hits = self.hit_stats()
        rows = []
        for r in c.execute("SELECT id, path, title, tags, mtime FROM documents"):
            tags = _loads_or(r["tags"], [])
            h = hits.get(r["id"], (0, 0.0))
            rows.append({
                "path": r["path"], "title": r["title"], "tags": tags,
                "mtime": r["mtime"], "chunks": chunks.get(r["id"], 0),
                "links_out": outl.get(r["id"], 0), "links_in": inl.get(r["id"], 0),
                "hits": h[0], "last_hit": h[1],
            })
        return rows

    def doc_detail(self, path: str) -> Optional[dict]:
        """Full note detail for the console: meta, chunks, in/out links."""
        c = self.conn()
        r = c.execute(
            "SELECT id, path, title, tags, frontmatter, mtime, indexed_at "
            "FROM documents WHERE path=?", (path,)
        ).fetchone()
        if not r:
            return None
        doc_id = r["id"]

        def _links(where: str, join_on: str):
            return [
                {"path": x["path"], "title": x["title"], "kind": x["kind"],
                 "weight": x["weight"]}
                for x in c.execute(
                    f"SELECT d.path, d.title, l.kind, l.weight FROM links l "
                    f"JOIN documents d ON d.id = l.{join_on} WHERE l.{where}=? "
                    f"ORDER BY l.weight DESC, d.title", (doc_id,))
            ]

        chunks = [
            {"heading": x["heading"], "text": x["text"]}
            for x in c.execute(
                "SELECT heading, text FROM chunks WHERE doc_id=? ORDER BY ord",
                (doc_id,))
        ]
        tags = _loads_or(r["tags"], [])
        frontmatter = _loads_or(r["frontmatter"], {})
        hit_row = c.execute(
            "SELECT hits, last_hit FROM note_hits WHERE doc_id=?", (doc_id,)).fetchone()
        return {
            "path": r["path"], "title": r["title"], "tags": tags,
            "frontmatter": frontmatter, "mtime": r["mtime"],
            "indexed_at": r["indexed_at"], "chunks": chunks,
            "links_out": _links("src_doc", "dst_doc"),
            "links_in": _links("dst_doc", "src_doc"),
            "hits": hit_row["hits"] if hit_row else 0,
            "last_hit": hit_row["last_hit"] if hit_row else 0.0,
        }

    def tag_counts(self) -> list[dict]:
        out: dict[str, int] = {}
        for r in self.conn().execute("SELECT tags FROM documents"):
            for t in _loads_or(r["tags"], []):
                out[t] = out.get(t, 0) + 1
        return [
            {"tag": t, "count": n}
            for t, n in sorted(out.items(), key=lambda x: (-x[1], x[0]))
        ]

    def embed_cache_count(self) -> int:
        return int(self.conn().execute(
            "SELECT COUNT(*) AS n FROM embed_cache").fetchone()["n"])

    def doc_wikilinks(self) -> dict[int, list[str]]:
        """doc_id -> raw wikilink targets, as stored at index time."""
        out: dict[int, list[str]] = {}
        for r in self.conn().execute("SELECT id, wikilinks FROM documents"):
            out[r["id"]] = _loads_or(r["wikilinks"], [])
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

    def _embedded_count(self) -> int:
        return self.conn().execute(
            "SELECT COUNT(*) AS n FROM chunks WHERE vec IS NOT NULL").fetchone()["n"]

    def unembedded_chunk_count(self) -> int:
        """Chunks with no vector — left over from a keyless index. Non-zero
        means vector search is silently blind to those notes."""
        return self.conn().execute(
            "SELECT COUNT(*) AS n FROM chunks WHERE vec IS NULL").fetchone()["n"]

    def _ann_path(self) -> Path:
        return self.db_path.parent / "ann-index.npz"

    def _ann_fingerprint(self) -> str:
        r = self.conn().execute(
            "SELECT COUNT(*) AS n, COALESCE(MAX(id),0) AS mx, COALESCE(SUM(id),0) AS sm "
            "FROM chunks WHERE vec IS NOT NULL").fetchone()
        return f"{r['n']}|{r['mx']}|{r['sm']}"

    def _ensure_ann(self):
        """IVF index for big vaults, or None below the threshold (exact scan).

        Persisted next to the DB and fingerprinted against the chunk table, so
        restarts skip the k-means build. When the corpus drifted (incremental
        sync), centroids from the previous build are reused and only the
        assignment pass reruns — the expensive training is a rare event."""
        from .ann import IVFFlatIndex

        # fast path: already built, or below threshold — the only work under
        # the matrix lock
        with self._matrix_lock:
            if self._ann is not None:
                return self._ann
            if self._ann_failed:
                return None  # a prior build OOM'd/errored: don't retry all session
            n = self._embedded_count()
            if n < self.ann_threshold:
                return None

        # the expensive part (load or k-means build) runs WITHOUT the matrix
        # lock, so concurrent /search, watcher commits (_mark_dirty), and the
        # console's date/lexicon queries don't freeze for the whole build. A
        # dedicated build lock stops two threads building at once.
        with self._ann_build_lock:
            if self._ann is not None:      # another thread built it while we waited
                return self._ann
            if self._ann_failed:
                return None
            fp = self._ann_fingerprint()
            idx = IVFFlatIndex.load(self._ann_path(), fp)
            if idx is None:
                n = self._embedded_count()
                dim = self._embedded_dim()
                prev = IVFFlatIndex.load_any(self._ann_path())
                reuse = (prev is not None
                         and 0.5 <= prev.size / max(n, 1) <= 1.5
                         and prev.vectors.shape[1] == dim)
                log.info("building IVF vector index for %d chunks%s", n,
                         " (reusing centroids)" if reuse else "")
                try:
                    idx = IVFFlatIndex.build(
                        self._iter_vec_blocks, total=n, dim=dim,
                        centroids=prev.centroids if reuse else None,
                        scale=prev.scale if reuse else None,
                    )
                except (MemoryError, ValueError) as e:
                    # don't let vector_search re-attempt (and re-OOM) forever —
                    # fall back to the exact scan for the rest of the session
                    log.warning("ANN build failed (%s); falling back to exact "
                                "vector search for this session", e)
                    self._ann_failed = True
                    return None
                try:
                    idx.save(self._ann_path(), fp)
                except OSError:
                    log.warning("could not persist ANN index; it will rebuild next run")
            with self._matrix_lock:
                self._ann = idx
            return idx

    def _embedded_dim(self) -> int:
        r = self.conn().execute(
            "SELECT LENGTH(vec) AS b FROM chunks WHERE vec IS NOT NULL LIMIT 1").fetchone()
        return (r["b"] // 4) if r else 0

    def _iter_vec_blocks(self, block: int = 20_000):
        cur = self.conn().execute(
            "SELECT id, vec FROM chunks WHERE vec IS NOT NULL ORDER BY id")
        while True:
            rows = cur.fetchmany(block)
            if not rows:
                return
            yield (np.vstack([np.frombuffer(r["vec"], dtype=np.float32) for r in rows]),
                   np.array([r["id"] for r in rows], dtype=np.int64))

    def vector_index_kind(self) -> str:
        """'ivf-int8' | 'exact' — what the next vector query will use."""
        if self._ann is not None or self._embedded_count() >= self.ann_threshold:
            return "ivf-int8"
        return "exact"

    def vector_search(self, query_vec: np.ndarray, k: int) -> list[tuple[int, float]]:
        ann = self._ensure_ann()
        if ann is not None:
            # over-fetch from the int8 index, then rescore candidates with
            # their true float32 vectors (a handful of PK lookups): recovers
            # quantization near-tie flips — measured recall@10 0.965 → 0.995
            cand = ann.search(query_vec, max(k + 16, 2 * k), nprobe=self.ann_nprobe)
            if not cand:
                return []
            q = query_vec.astype(np.float32)
            marks = ",".join("?" * len(cand))
            rows = self.conn().execute(
                f"SELECT id, vec FROM chunks WHERE id IN ({marks})",
                [cid for cid, _ in cand]).fetchall()
            rescored = [
                (r["id"], float(np.frombuffer(r["vec"], dtype=np.float32) @ q))
                for r in rows if r["vec"] is not None
            ]
            rescored.sort(key=lambda t: -t[1])
            return rescored[:k]
        matrix, ids, _pos = self._ensure_matrix()
        if matrix.shape[0] == 0 or matrix.shape[1] != query_vec.shape[0]:
            # dim mismatch = embed model/provider changed without `index --full`
            return []
        sims = matrix @ query_vec.astype(np.float32)
        k = min(k, len(ids))
        top = np.argpartition(-sims, k - 1)[:k]
        top = top[np.argsort(-sims[top])]
        return [(int(ids[i]), float(sims[i])) for i in top]

    def similar_cross_doc_pairs(
        self, threshold: float, cap: int = 2000, block: int = 512
    ) -> list[tuple[int, int, float]]:
        """Chunk pairs from DIFFERENT notes with cosine >= threshold, sorted by
        similarity desc. Feeds the conflict/duplicate scan. Blockwise matmul
        over the existing in-memory matrix — no extra storage, no API."""
        matrix, ids, _pos = self._ensure_matrix()
        n = matrix.shape[0]
        if n == 0:
            return []
        doc_of = {
            r["id"]: r["doc_id"] for r in self.conn().execute("SELECT id, doc_id FROM chunks")
        }
        docs = np.array([doc_of.get(int(c), -1) for c in ids])
        pairs: list[tuple[int, int, float]] = []
        for s in range(0, n, block):
            e = min(s + block, n)
            sims = matrix[s:e] @ matrix.T  # (block, n)
            bi_idx, j_idx = np.where(sims >= threshold)
            for bi, j in zip(bi_idx, j_idx):
                i = s + int(bi)
                j = int(j)
                if j <= i or docs[j] == docs[i]:
                    continue
                pairs.append((int(ids[i]), int(ids[j]), float(sims[bi, j])))
            if len(pairs) >= cap * 4:  # plenty for downstream filtering
                break
        pairs.sort(key=lambda p: -p[2])
        return pairs[:cap]

    ENRICH_HEADING = "↩ context"  # marker for index-time enrichment pseudo-chunks

    def replace_enrichment_chunk(self, doc_id: int, title: str, text: str,
                                 vec: Optional[np.ndarray]) -> None:
        """Replace a doc's enrichment pseudo-chunk (frontmatter + backlink
        context for stub notes). Kept separate from content chunks so normal
        re-chunking and the embed cache are untouched."""
        c = self.conn()
        old = [r["id"] for r in c.execute(
            "SELECT id FROM chunks WHERE doc_id=? AND heading=?",
            (doc_id, self.ENRICH_HEADING))]
        for cid in old:
            c.execute("DELETE FROM chunks_fts WHERE rowid=?", (cid,))
        c.execute("DELETE FROM chunks WHERE doc_id=? AND heading=?",
                  (doc_id, self.ENRICH_HEADING))
        if text.strip():
            nxt = c.execute(
                "SELECT COALESCE(MAX(ord), -1) + 1 AS o FROM chunks WHERE doc_id=?",
                (doc_id,)).fetchone()["o"]
            blob = vec.astype(np.float32).tobytes() if vec is not None else None
            cur = c.execute(
                "INSERT INTO chunks(doc_id, ord, heading, text, vec) VALUES(?,?,?,?,?)",
                (doc_id, nxt, self.ENRICH_HEADING, text, blob))
            c.execute(
                "INSERT INTO chunks_fts(rowid, text, title, heading) VALUES(?,?,?,?)",
                (int(cur.lastrowid), fts_index_text(text), fts_index_text(title), ""))
        c.commit()
        self._mark_dirty()

    # -------------------------------------------------------------- hit stats
    def record_hits(self, doc_ids: list[int]) -> None:
        """Count real retrievals per note (console 'working knowledge' stats).

        Only interface layers (server/CLI) record — library calls and
        benchmarks never pollute the numbers."""
        if not doc_ids:
            return
        import time as _t

        now = _t.time()
        c = self.conn()
        c.executemany(
            "INSERT INTO note_hits(doc_id, hits, last_hit) VALUES(?, 1, ?) "
            "ON CONFLICT(doc_id) DO UPDATE SET hits = hits + 1, last_hit = ?",
            [(d, now, now) for d in set(doc_ids)],
        )
        c.commit()

    def hit_stats(self) -> dict[int, tuple[int, float]]:
        """doc_id -> (hits, last_hit)."""
        return {r["doc_id"]: (r["hits"], r["last_hit"]) for r in self.conn().execute(
            "SELECT doc_id, hits, last_hit FROM note_hits")}

    # -------------------------------------------------------------- event log
    EVENT_LOG_MAX = 1000  # ring buffer: the dashboard needs a timeline, not history

    def log_event(self, kind: str, client: str = "", query: Optional[str] = None,
                  path: Optional[str] = None, detail: Optional[dict] = None) -> None:
        """One line in the middleware timeline: what passed through, from whom.
        Local-only (never leaves the SQLite file); capped as a ring buffer."""
        import time as _t

        c = self.conn()
        c.execute(
            "INSERT INTO event_log(ts, kind, client, query, path, detail) "
            "VALUES(?,?,?,?,?,?)",
            (_t.time(), kind, client, query, path,
             json.dumps(detail, ensure_ascii=False) if detail else None),
        )
        c.execute(
            "DELETE FROM event_log WHERE id <= ("
            "  SELECT id FROM event_log ORDER BY id DESC "
            f"  LIMIT 1 OFFSET {self.EVENT_LOG_MAX})")
        c.commit()

    def events(self, kinds: Optional[list[str]] = None, limit: int = 100) -> list[dict]:
        """Newest-first timeline rows, optionally filtered by kind."""
        sql = "SELECT ts, kind, client, query, path, detail FROM event_log"
        args: list = []
        if kinds:
            sql += f" WHERE kind IN ({','.join('?' * len(kinds))})"
            args.extend(kinds)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        out = []
        for r in self.conn().execute(sql, args):
            detail = _loads_or(r["detail"], None) if r["detail"] else None
            out.append({"ts": r["ts"], "kind": r["kind"], "client": r["client"],
                        "query": r["query"], "path": r["path"], "detail": detail})
        return out

    def client_stats(self, days: float = 7.0) -> list[dict]:
        """Per-client event counts in the window — who is using this memory."""
        import time as _t

        cutoff = _t.time() - days * 86400
        return [
            {"client": r["client"] or "unknown", "events": r["n"],
             "queries": r["q"], "writes": r["w"], "last": r["last"]}
            for r in self.conn().execute(
                "SELECT client, COUNT(*) AS n, "
                "  SUM(kind IN ('search','ask')) AS q, "
                "  SUM(kind IN ('memory','append')) AS w, "
                "  MAX(ts) AS last "
                "FROM event_log WHERE ts >= ? GROUP BY client ORDER BY n DESC",
                (cutoff,))
        ]

    def doc_body_len(self) -> dict[int, int]:
        """doc_id -> total chars of content chunks (enrichment excluded)."""
        return {r["d"]: r["n"] for r in self.conn().execute(
            "SELECT doc_id AS d, SUM(LENGTH(text)) AS n FROM chunks "
            "WHERE heading != ? GROUP BY doc_id", (self.ENRICH_HEADING,))}

    def chunk_vectors(self, chunk_ids: list[int]) -> dict[int, "np.ndarray"]:
        """Raw stored vectors for specific chunks (unit-norm rows of the matrix).

        In ANN mode the float32 matrix is never materialized (that's the whole
        point) — rows come dequantized from the int8 index instead."""
        ann = self._ensure_ann()
        if ann is not None:
            return ann.rows_for(chunk_ids)
        matrix, _ids, pos = self._ensure_matrix()
        return {cid: matrix[pos[cid]] for cid in chunk_ids if cid in pos}

    def chunk_sims(self, query_vec: np.ndarray, chunk_ids: list[int]) -> dict[int, float]:
        """Cosine similarity of specific chunks against a query vector."""
        if not chunk_ids:
            return {}
        ann = self._ensure_ann()
        if ann is not None:
            vecs = ann.rows_for(chunk_ids)
            q = query_vec.astype(np.float32)
            if not vecs or next(iter(vecs.values())).shape[0] != q.shape[0]:
                return {}
            return {cid: float(v @ q) for cid, v in vecs.items()}
        matrix, _ids, pos = self._ensure_matrix()
        if matrix.shape[0] == 0 or matrix.shape[1] != query_vec.shape[0]:
            return {}
        wanted = [(cid, pos[cid]) for cid in chunk_ids if cid in pos]
        if not wanted:
            return {}
        rows = np.array([i for _, i in wanted])
        sims = matrix[rows] @ query_vec.astype(np.float32)
        return {cid: float(s) for (cid, _), s in zip(wanted, sims)}

    # ----------------------------------------------------------------- BM25
    def _fts_query(self, match: str, k: int) -> Optional[list]:
        try:
            return self.conn().execute(
                """SELECT rowid, bm25(chunks_fts, 1.0, 0.6, 0.4) AS s
                   FROM chunks_fts WHERE chunks_fts MATCH ?
                   ORDER BY s LIMIT ?""",
                (match, k),
            ).fetchall()
        except sqlite3.OperationalError:
            return None

    def bm25_search(self, query: str, k: int) -> list[tuple[int, float]]:
        # Phase 1 — implicit AND of the raw words: on big corpora the OR query
        # below matches (and scores) nearly every row when the query contains
        # common words, which dominates hybrid latency (~60 ms at 50k chunks).
        # AND restricts the scored set to docs containing every term; when that
        # already yields k docs they are strictly better candidates than any
        # OR-only match, so the OR pass can be skipped. Queries that AND can't
        # satisfy (Korean 조사 variants, paraphrases, typos) fall through to
        # the OR+bigram pass unchanged — a cheap failed AND, not a recall loss.
        terms = [t.replace('"', "") for t in query.split() if t.strip()][:16]
        if len(terms) >= 2:
            rows = self._fts_query(" ".join(f'"{t}"' for t in terms), k)
            if rows is not None and len(rows) >= k:
                return [(int(r["rowid"]), -float(r["s"])) for r in rows]
        # Phase 2 — the recall-oriented OR of terms + Hangul bigrams
        rows = self._fts_query(_fts_escape(query), k)
        if rows is None:
            return []
        # bm25() returns lower-is-better; flip sign so higher is better
        return [(int(r["rowid"]), -float(r["s"])) for r in rows]

    # -------------------------------------------------------------- doc dates
    def doc_dates(self) -> dict[int, float]:
        """doc_id -> best-effort note date (epoch), cached until index change."""
        from ..retrieval.temporal import doc_date as _doc_date

        with self._matrix_lock:
            cached = self._doc_dates
        if cached is not None:
            return cached
        out: dict[int, float] = {}
        for r in self.conn().execute(
            "SELECT id, title, path, frontmatter, mtime FROM documents"
        ):
            out[r["id"]] = _doc_date(r["title"], r["path"], r["frontmatter"], r["mtime"])
        with self._matrix_lock:
            self._doc_dates = out
        return out

    def recent_docs(self, days: float, limit: int) -> list[tuple[float, "DocRecord"]]:
        """(date, doc) for notes touched in the last `days`, newest first.
        Shared by `lemory recent`, the MCP recent_notes tool, and the context
        block so they can't drift."""
        import time as _t

        docs = {d.id: d for d in self.all_docs()}
        dates = self.doc_dates()
        cutoff = _t.time() - days * 86400
        rows = [(ts, docs[did]) for did, ts in dates.items()
                if ts >= cutoff and did in docs]
        rows.sort(key=lambda x: -x[0])
        return rows[:limit]

    # ------------------------------------------------------------ typo lexicon
    _LEX_WORD_RE = re.compile(r"[A-Za-z]{3,}|[가-힣]{2,}")

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

    def lexicon_buckets(self) -> dict[str, list[tuple[str, int]]]:
        """lexicon() grouped by first AND second character — the typo scan's
        candidate filter becomes an O(bucket) lookup instead of a 350k-term
        linear scan. Second-char buckets (prefixed '\x02') let a typo in the
        FIRST syllable ('메이플' typed '매이플/이메플') still find its word:
        first-char-equal filtering alone is blind exactly there."""
        with self._matrix_lock:
            buckets = self._lexicon_buckets
        if buckets is not None:
            return buckets
        buckets = {}
        for term, count in self.lexicon().items():
            buckets.setdefault(term[0], []).append((term, count))
            if len(term) >= 2:
                buckets.setdefault("\x02" + term[1], []).append((term, count))
        with self._matrix_lock:
            self._lexicon_buckets = buckets
        return buckets

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

    def token_chunk_df(self, token: str) -> int:
        """How many CHUNKS contain the token — true document frequency, unlike
        lexicon()'s occurrence counts (which one note repeating a term, or the
        per-chunk title join, can inflate). Used by the boilerplate gate:
        'common' must mean spread across the corpus, not merely repeated in
        one place. One indexed FTS count per call (~sub-ms)."""
        safe = token.replace('"', "")
        if not safe:
            return 0
        try:
            row = self.conn().execute(
                'SELECT count(*) AS n FROM chunks_fts WHERE chunks_fts MATCH ?',
                (f'"{safe}"',),
            ).fetchone()
        except sqlite3.OperationalError:
            return 0  # unparseable token: treat as rare/discriminative
        return int(row["n"] if row else 0)

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
