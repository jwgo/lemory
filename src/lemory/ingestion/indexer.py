"""Incremental vault indexing + live watcher.

The sync loop is mem0-style incremental: only notes whose content hash changed
are re-chunked/re-embedded; the embedding cache means even a full rebuild of
an unchanged vault costs zero API calls.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

from .markdown import chunk_note, embed_text_for_chunk, parse_note, render_plain
from ..storage import Store

if TYPE_CHECKING:
    from ..engine import Engine

log = logging.getLogger("lemory.ingest")


@dataclass
class IndexPlan:
    """Dry-run answer to "what would indexing do, and how long will it take?"."""

    files_total: int = 0
    to_process: int = 0        # notes that would be (re)chunked
    to_remove: int = 0
    chunks_total: int = 0      # chunks across to-be-processed notes
    embeds_needed: int = 0     # chunks that would actually hit the embedder
    est_seconds: float = 0.0
    rate_chunks_per_s: float = 0.0
    rate_measured: bool = False  # False → provider default, not observed speed

    def human_eta(self) -> str:
        s = self.est_seconds
        if self.embeds_needed == 0:
            return "즉시 (임베딩 캐시 적중)"
        if s < 5:
            return "몇 초"
        if s < 90:
            return f"약 {int(round(s / 5) * 5)}초"
        if s < 5400:
            return f"약 {int(round(s / 60))}분"
        return f"약 {s / 3600:.1f}시간"


@dataclass
class SyncReport:
    added: int = 0
    updated: int = 0
    removed: int = 0
    unchanged: int = 0
    chunks: int = 0
    embedded: int = 0  # chunks that actually hit the API (cache misses)
    seconds: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.added or self.updated or self.removed)


def note_title(path: Path) -> str:
    return path.stem


def iter_vault_files(vault: Path, include: list[str], exclude_dirs: list[str]) -> list[Path]:
    out = []
    for pattern in include:
        for p in vault.glob(pattern):
            if not p.is_file():
                continue
            rel = p.relative_to(vault)
            if any(part in exclude_dirs for part in rel.parts[:-1]):
                continue
            out.append(p)
    return sorted(set(out))


def active_globs(cfg) -> list[str]:
    """include_globs plus attachment types enabled in config."""
    globs = list(cfg.include_globs)
    if getattr(cfg, "index_pdf", False) and "**/*.pdf" not in globs:
        globs.append("**/*.pdf")
    if getattr(cfg, "index_docx", False) and "**/*.docx" not in globs:
        globs.append("**/*.docx")
    return globs


_DOCX_TAG = re.compile(rb"<[^>]+>")


def _read_docx(f: Path) -> str:
    """Word text extraction with the stdlib only: a .docx is a zip whose
    word/document.xml holds every paragraph as <w:p>…</w:p>. Paragraph tags
    become newlines, remaining tags are stripped, entities unescaped. No
    python-docx dependency — formatting is irrelevant to retrieval."""
    import html
    import zipfile

    try:
        with zipfile.ZipFile(f) as z:
            xml = z.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError, OSError) as e:
        raise OSError(f"unreadable docx: {e}")
    xml = xml.replace(b"</w:p>", b"\n").replace(b"<w:tab/>", b"\t")
    text = _DOCX_TAG.sub(b"", xml).decode("utf-8", errors="replace")
    return html.unescape(text).strip()


def read_note_text(f: Path) -> str:
    """File → indexable text. Markdown is read verbatim; PDFs (opt-in via
    cfg.index_pdf) go through pypdf text extraction; .docx (opt-in via
    cfg.index_docx) through a stdlib zip/XML reader. Raises OSError on
    unreadable files so callers' existing error paths apply."""
    suffix = f.suffix.lower()
    if suffix == ".docx":
        return _read_docx(f)
    if suffix != ".pdf":
        return f.read_text(encoding="utf-8", errors="replace")
    try:
        from pypdf import PdfReader
    except ImportError:
        raise OSError("PDF indexing requires pypdf — pip install 'lemory[pdf]'")
    try:
        reader = PdfReader(str(f))
        pages = [(p.extract_text() or "") for p in reader.pages]
    except Exception as e:  # pypdf raises a zoo of types on corrupt files
        raise OSError(f"unreadable PDF: {e}")
    return "\n\n".join(pages).strip()


class Indexer:
    def __init__(self, engine: "Engine"):
        self.engine = engine
        self.cfg = engine.cfg
        self.store: Store = engine.store

    def _chunk(self, note, title: str) -> list[tuple[str, str]]:
        """Chunk a note, with the whole-note fallback for notes that produce no
        chunks (0-byte, frontmatter-only). Shared by plan() and sync() so the
        dry-run estimate and the real sync can never disagree on chunk counts."""
        chunks = chunk_note(
            note.body, self.cfg.chunk_chars, self.cfg.chunk_overlap,
            self.cfg.min_chunk_chars,
        )
        if not chunks:
            plain = render_plain(note.body)
            chunks = [("", plain)] if plain else [("", title)]
        return chunks

    # ------------------------------------------------------------------ plan
    # provider defaults (chunks/s) used until a real rate has been observed
    _DEFAULT_RATES = {"gemini": 40.0, "openai": 40.0, "local": 20.0}

    def plan(self, full: bool = False) -> IndexPlan:
        """Estimate what sync() would do — no writes, no API calls.

        Chunks changed notes locally (fast) and checks the embedding cache to
        count real API/model work, then divides by the observed embed rate
        (persisted EMA from previous runs) or a provider default.
        """
        p = IndexPlan()
        vault = self.cfg.resolved_vault()
        files = iter_vault_files(vault, active_globs(self.cfg), self.cfg.exclude_dirs)
        p.files_total = len(files)
        seen: set[str] = set()

        keyless = self.engine.keyless
        model = dim = None
        if not keyless:
            model = self.cfg.active_embed_model()
            dim = self.cfg.active_embed_dim()
            # a pending model switch makes the next sync a full re-embed
            stored_sig = self.store.get_meta("embed_signature")
            if stored_sig is not None and stored_sig != f"{model}|{dim}" and self.store.chunk_count() > 0:
                full = True
            # keyless→keyed upgrade: the next sync full-embeds the leftover
            # NULL-vector chunks (mirrors Engine.index) — so the ETA is honest
            elif self.store.unembedded_chunk_count() > 0:
                full = True

        embed_keys: list[str] = []
        for f in files:
            rel = str(f.relative_to(vault))
            seen.add(rel)
            try:
                raw = read_note_text(f)
            except OSError:
                continue
            content_hash = hashlib.sha256(raw.encode()).hexdigest()
            existing = self.store.get_doc_by_path(rel)
            if existing and existing.content_hash == content_hash and not full:
                continue
            p.to_process += 1
            title = note_title(f)
            note = parse_note(raw, title)
            chunks = self._chunk(note, title)
            p.chunks_total += len(chunks)
            if not keyless:
                embed_keys.extend(
                    Store.cache_key(model, dim, "doc", embed_text_for_chunk(title, h, t))
                    for h, t in chunks
                )

        p.to_remove = sum(1 for d in self.store.all_docs() if d.path not in seen)
        cached = self.store.cache_get_many(embed_keys)
        p.embeds_needed = sum(1 for k in embed_keys if k not in cached)

        rate_meta = self.store.get_meta("embed_rate_ema")
        if rate_meta:
            p.rate_chunks_per_s = max(0.5, float(rate_meta))
            p.rate_measured = True
        else:
            provider = "none" if keyless else self.cfg.resolved_provider()
            p.rate_chunks_per_s = self._DEFAULT_RATES.get(provider, 20.0)
        p.est_seconds = p.embeds_needed / p.rate_chunks_per_s + p.chunks_total * 0.002 + 1.0
        return p

    # ------------------------------------------------------------------ sync
    def sync(
        self, full: bool = False, progress: Optional[Callable[[str], None]] = None,
        paths: Optional[set[str]] = None,
    ) -> SyncReport:
        """Sync the index with the vault.

        With `paths` (vault-relative), only those files are read/hashed and
        deletions are checked only among them — the fast path the watcher uses
        so one edit doesn't rescan a 10k-note vault. Without it, the full
        vault is scanned (start-up, CLI `lemory index`, safety net).
        """
        t0 = time.time()
        rep = SyncReport()
        vault = self.cfg.resolved_vault()
        targeted = paths is not None and not full
        if targeted:
            files = []
            for rel in paths:
                p = vault / rel
                if p.is_file():
                    files.append(p)
                elif self.store.get_doc_by_path(rel):
                    self.store.delete_document(rel)
                    rep.removed += 1
                    if progress:
                        progress(f"removed {rel}")
        else:
            files = iter_vault_files(vault, active_globs(self.cfg), self.cfg.exclude_dirs)
        seen_paths: set[str] = set()
        changed_docs: list[tuple[int, list[str]]] = []  # (doc_id, wikilinks)

        for f in files:
            rel = str(f.relative_to(vault))
            seen_paths.add(rel)
            try:
                raw = read_note_text(f)
            except OSError as e:
                rep.errors.append(f"{rel}: {e}")
                continue
            content_hash = hashlib.sha256(raw.encode()).hexdigest()
            existing = self.store.get_doc_by_path(rel)
            if existing and existing.content_hash == content_hash and not full:
                rep.unchanged += 1
                continue

            title = note_title(f)
            note = parse_note(raw, title)

            # privacy exclusion: `lemory: false` in frontmatter keeps a note
            # out of the index entirely — never searchable, never sent to any
            # model. If it was indexed before the flag, it is removed now.
            _priv = note.frontmatter.get("lemory")
            # accept the quoted-string forms too (lemory: "false"/no/off) so a
            # privacy opt-out never silently fails because YAML kept it a string
            if _priv is False or (isinstance(_priv, str)
                                  and _priv.strip().lower() in ("false", "no", "off")):
                if existing:
                    self.store.delete_document(rel)
                    rep.removed += 1
                    if progress:
                        progress(f"excluded (lemory: false): {rel}")
                continue  # stays in seen_paths so the delete sweep skips it

            chunks = self._chunk(note, title)

            if self.engine.keyless:
                # no embedding provider: index lexically (BM25 + link graph
                # still work); a key added later fills vectors on next sync
                vectors, misses = None, 0
            else:
                embed_texts = [embed_text_for_chunk(title, h, t) for h, t in chunks]
                vectors, misses = self.engine.embed_documents_cached(embed_texts)
            rep.embedded += misses

            doc_id = self.store.store_note(
                rel, title, content_hash, f.stat().st_mtime, note.tags,
                note.frontmatter, time.time(), note.wikilinks, chunks, vectors,
            )
            changed_docs.append((doc_id, note.wikilinks))
            rep.chunks += len(chunks)
            if existing:
                rep.updated += 1
            else:
                rep.added += 1
            if progress:
                progress(f"indexed {rel} ({len(chunks)} chunks)")

        # deletions (targeted mode already handled its own removals above)
        if not targeted:
            for doc in self.store.all_docs():
                if doc.path not in seen_paths:
                    self.store.delete_document(doc.path)
                    rep.removed += 1
                    if progress:
                        progress(f"removed {doc.path}")

        # graph: rebuild links for changed docs. When the set of resolvable
        # titles changed (add/remove/rename/ALIAS edits), links FROM unchanged
        # docs can change too — their wikilinks/mentions may now resolve — so
        # rebuild everything. Wikilinks are persisted per doc, which makes a
        # full rebuild always correct; the title-set hash detects all cases.
        if rep.changed:
            title_hash = hashlib.sha256(
                "\n".join(sorted(self.store.title_map())).encode()
            ).hexdigest()
            titles_changed = title_hash != self.store.get_meta("title_set_hash")
            self._rebuild_links(
                changed_ids=[d for d, _ in changed_docs],
                full=bool(titles_changed or full),
            )
            self.store.set_meta("title_set_hash", title_hash)
            if self.cfg.semantic_links:
                self._semantic_fallback_links()

        # runs on change, and once on upgrade (pre-enrichment indexes)
        if self.cfg.stub_enrichment and (
            rep.changed or self.store.get_meta("stub_enriched") != "1"
        ):
            rep.embedded += self._enrich_stubs()
            self.store.set_meta("stub_enriched", "1")

        rep.seconds = time.time() - t0
        self.store.set_meta("last_sync", str(time.time()))
        return rep

    # ----------------------------------------------------------------- graph
    def _rebuild_links(self, changed_ids: list[int], full: bool) -> None:
        """Rebuild wiki + mention edges. `full` rebuilds every doc (needed when
        titles were added/removed); otherwise only the changed docs — safe
        because wikilinks are persisted per doc in the documents table."""
        title_to_id = self.store.title_map()
        all_wikilinks = self.store.doc_wikilinks()
        rebuild_ids = list(all_wikilinks.keys()) if full else changed_ids

        targets = self._cached_mention_targets(title_to_id) if self.cfg.mention_links else None
        for doc_id in rebuild_ids:
            merged: dict[tuple[int, str], float] = {}
            for target in all_wikilinks.get(doc_id, []):
                tid = title_to_id.get(target.strip().lower())
                if tid and tid != doc_id:
                    merged[(tid, "wiki")] = 1.0
            for dst, w in self._find_mentions(doc_id, targets).items():
                if (dst, "wiki") not in merged:
                    merged[(dst, "mention")] = w
            self.store.replace_links(doc_id, [(dst, kind, w) for (dst, kind), w in merged.items()])

    def _semantic_fallback_links(self) -> None:
        """The linkless-vault answer: a note with ZERO outgoing edges gets up
        to k cosine-nearest neighbor edges (kind='sem') so graph expansion has
        something to walk. Notes with any real edge are untouched — linked
        vaults (and every published benchmark) stay byte-identical. Purely
        vector math over the existing index; no LLM, nothing new stored
        besides the edges themselves."""
        import numpy as np

        cfg = self.cfg
        vecs, doc_ids = self.store.doc_mean_vectors()
        if vecs.shape[0] < 2:
            return
        out_counts = self.store.outgoing_link_counts()
        # 'sem' edges don't count as real links — they must be replaceable on
        # every rebuild, and must never suppress themselves on the next sync
        sem_only = {
            d for d, n in out_counts.items()
            if n == self.store.sem_only_out_count(d)
        }
        linkless_idx = [i for i, d in enumerate(doc_ids)
                        if out_counts.get(int(d), 0) == 0 or int(d) in sem_only]
        if not linkless_idx:
            return
        sims = vecs[linkless_idx] @ vecs.T  # (m, n)
        for row, i in zip(sims, linkless_idx):
            src = int(doc_ids[i])
            row[i] = -1.0  # not self
            top = np.argsort(-row)[: cfg.semantic_links_k]
            edges = [
                (int(doc_ids[j]), "sem", float(row[j]) * cfg.semantic_links_weight)
                for j in top if row[j] >= cfg.semantic_links_floor
            ]
            self.store.replace_links(src, edges)

    # -------------------------------------------------------- stub enrichment
    _SENT_SPLIT = re.compile(r"(?<=[.!?다요음됨])\s+|\n+")

    def _enrich_stubs(self) -> int:
        """Give stub notes an indexed representation others can find.

        A 3-line reference note is nearly invisible to BM25 and embeddings,
        yet most wikilinks in real vaults point at exactly such notes. For
        every doc whose content is shorter than cfg.stub_chars, index one
        extra pseudo-chunk: flattened frontmatter properties + the sentences
        surrounding inbound links in other notes (anchor-text style). Runs
        after every link rebuild; the embed cache absorbs unchanged contexts.
        Returns the number of enrichment chunks that hit the embedder.
        """
        import json as _json

        store = self.store
        body_len = store.doc_body_len()
        stubs = [d for d, ln in body_len.items() if ln < self.cfg.stub_chars]
        if not stubs:
            return 0
        docs = {d.id: d for d in store.all_docs()}
        c = store.conn()

        to_embed: list[tuple[int, str, str]] = []  # (doc_id, title, text)
        for doc_id in stubs:
            doc = docs.get(doc_id)
            if doc is None:
                continue
            parts: list[str] = []
            row = c.execute("SELECT frontmatter FROM documents WHERE id=?", (doc_id,)).fetchone()
            try:
                fm = _json.loads(row["frontmatter"]) if row else {}
            except _json.JSONDecodeError:
                fm = {}
            props = []
            for k, v in fm.items():
                if isinstance(v, (str, int, float)) and str(v).strip():
                    props.append(f"{k}: {v}")
                elif isinstance(v, list):
                    vals = [str(x) for x in v if isinstance(x, (str, int, float))][:6]
                    if vals:
                        props.append(f"{k}: {', '.join(vals)}")
            if props:
                parts.append(" · ".join(props[:10]))

            # backlink contexts: sentences in OTHER notes around links/mentions here
            srcs = [r["src_doc"] for r in c.execute(
                "SELECT DISTINCT src_doc FROM links WHERE dst_doc=? "
                "AND kind IN ('wiki','mention') LIMIT 6", (doc_id,))]
            tl = doc.title.lower()
            ctx: list[str] = []
            for src in srcs:
                src_doc = docs.get(src)
                if src_doc is None:
                    continue
                rows = c.execute(
                    "SELECT text FROM chunks WHERE doc_id=? AND heading != ? ORDER BY ord",
                    (src, store.ENRICH_HEADING)).fetchall()
                for r in rows:
                    for sent in self._SENT_SPLIT.split(r["text"]):
                        if tl in sent.lower() and 20 <= len(sent) <= 400:
                            ctx.append(f"({src_doc.title}) {sent.strip()}")
                            break
                    if len(ctx) and ctx[-1].startswith(f"({src_doc.title})"):
                        break
            if ctx:
                parts.append("\n".join(ctx[:6]))

            text = "\n".join(parts).strip()
            existing = c.execute(
                "SELECT text FROM chunks WHERE doc_id=? AND heading=?",
                (doc_id, store.ENRICH_HEADING)).fetchone()
            if (existing["text"] if existing else "") == text:
                continue  # unchanged — don't dirty the matrix
            to_embed.append((doc_id, doc.title, text))

        if not to_embed:
            return 0
        if self.engine.keyless:
            vectors, misses = None, 0
        else:
            embed_texts = [embed_text_for_chunk(t, "", txt) for _, t, txt in to_embed]
            vectors, misses = self.engine.embed_documents_cached(embed_texts)
        for i, (doc_id, title, text) in enumerate(to_embed):
            vec = vectors[i] if vectors is not None and text else None
            store.replace_enrichment_chunk(doc_id, title, text, vec)
        return misses

    def _cached_mention_targets(self, title_to_id: dict[str, int]) -> "_MentionAutomaton":
        """Mention automaton, rebuilt only when the title set changes."""
        key = hash(tuple(sorted(title_to_id.items())))
        cached = getattr(self, "_mention_cache", None)
        if cached and cached[0] == key:
            return cached[1]
        automaton = _MentionAutomaton(title_to_id)
        self._mention_cache = (key, automaton)
        return automaton

    def _find_mentions(self, doc_id: int, automaton: "_MentionAutomaton") -> dict[int, float]:
        if automaton is None or automaton.empty:
            return {}
        c = self.store.conn()
        # scan the note's OWN text only: enrichment pseudo-chunks quote
        # sentences from OTHER notes ("(A) ... mentions C"), and counting
        # those would give this note mention edges its author never wrote
        rows = c.execute("SELECT text FROM chunks WHERE doc_id=? AND heading != ?",
                         (doc_id, self.store.ENRICH_HEADING)).fetchall()
        text = "\n".join(r["text"] for r in rows).lower()
        return {tid: 0.85 for tid in automaton.find(text) if tid != doc_id}

    # ------------------------------------------------- optional LLM enrichment
    def enrich_entities(self, max_docs: int = 50) -> int:
        """cognify-style enrichment: extract entities per note, link co-mentions.

        Optional (off by default) — the wikilink+mention graph is free, this
        spends LLM quota for extra recall on vaults with few links.
        """
        c = self.store.conn()
        rows = c.execute(
            """SELECT d.id, d.title FROM documents d
               WHERE d.id NOT IN (SELECT DISTINCT doc_id FROM entity_mentions)
               LIMIT ?""",
            (max_docs,),
        ).fetchall()
        n = 0
        for r in rows:
            chunk_rows = c.execute(
                "SELECT text FROM chunks WHERE doc_id=? ORDER BY ord LIMIT 4", (r["id"],)
            ).fetchall()
            text = "\n".join(x["text"] for x in chunk_rows)[:6000]
            try:
                data = self.engine.llm.generate_json(
                    "Extract the named entities (people, organizations, places, products, "
                    "projects, concepts) central to this note. Return JSON: "
                    '{"entities": ["..."]} with at most 12 entities.\n\n'
                    f"NOTE TITLE: {r['title']}\n\n{text}"
                )
                names = [e for e in data.get("entities", []) if isinstance(e, str)][:12]
                self.store.add_entity_mentions(r["id"], names)
                n += 1
            except Exception as e:
                log.warning("entity extraction failed for %s: %s", r["title"], e)
        if n:
            self.store.rebuild_entity_links()
        return n


class _MentionAutomaton:
    """Aho-Corasick over lowercased note titles: ONE linear pass per document
    instead of one regex search per title. The old per-title loop was
    O(text × titles) — at BEIR-fiqa scale (57k titles × 57k docs) that is
    billions of regex scans and a first index appeared to hang for hours;
    this is O(text) per doc with the same word-boundary semantics as the
    old ``(?<!\\w)title(?!\\w)`` pattern (callers pass lowered text, matching
    the old IGNORECASE)."""

    def __init__(self, title_to_id: dict[str, int]):
        goto: list[dict[str, int]] = [{}]
        out: list[list[tuple[int, int]]] = [[]]  # node -> [(title_len, doc_id)]
        for title, doc_id in title_to_id.items():
            # short/generic single words create noise ("home", "index") —
            # identical filters to the old regex builder
            if len(title) < 4 or (" " not in title and len(title) < 6):
                continue
            node = 0
            for ch in title:
                nxt = goto[node].get(ch)
                if nxt is None:
                    goto.append({})
                    out.append([])
                    nxt = len(goto) - 1
                    goto[node][ch] = nxt
                node = nxt
            out[node].append((len(title), doc_id))
        # BFS failure links; outputs are merged down the fail chain so a title
        # that is a suffix of another path is still reported
        fail = [0] * len(goto)
        from collections import deque

        dq = deque(goto[0].values())
        while dq:
            node = dq.popleft()
            for ch, nxt in goto[node].items():
                dq.append(nxt)
                f = fail[node]
                while f and ch not in goto[f]:
                    f = fail[f]
                cand = goto[f].get(ch, 0)
                fail[nxt] = cand if cand != nxt else 0
                out[nxt].extend(out[fail[nxt]])
        self._goto, self._fail, self._out = goto, fail, out
        self.empty = len(goto) == 1

    @staticmethod
    def _is_word(ch: str) -> bool:
        # mirrors Python re's \w for the characters that occur in note text
        return ch.isalnum() or ch == "_"

    def find(self, text: str) -> set[int]:
        """doc_ids of all titles occurring in `text` with word boundaries."""
        goto, fail, out = self._goto, self._fail, self._out
        found: set[int] = set()
        node = 0
        n = len(text)
        for i, ch in enumerate(text):
            while node and ch not in goto[node]:
                node = fail[node]
            node = goto[node].get(ch, 0)
            if out[node]:
                for tlen, doc_id in out[node]:
                    if doc_id in found:
                        continue
                    start = i - tlen + 1
                    if ((start == 0 or not self._is_word(text[start - 1]))
                            and (i + 1 == n or not self._is_word(text[i + 1]))):
                        found.add(doc_id)
        return found


# --------------------------------------------------------------------- watch
def watch(engine: "Engine", debounce: float = 2.0, on_sync: Optional[Callable] = None) -> None:
    """Block and keep the index in sync with the vault (watchdog-based)."""
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    vault = engine.cfg.resolved_vault()
    lock = threading.Lock()
    pending: dict = {"paths": set(), "last": 0.0, "overflow": False}
    # react to whatever the include globs cover, not just .md
    suffixes = {Path(g).suffix for g in active_globs(engine.cfg) if Path(g).suffix} or {".md"}

    def note_path(p: str) -> Optional[str]:
        pp = Path(p)
        if pp.suffix not in suffixes:
            return None
        if any(part in engine.cfg.exclude_dirs for part in pp.parts):
            return None
        try:
            return str(pp.resolve().relative_to(vault))
        except ValueError:
            return None

    class Handler(FileSystemEventHandler):
        def on_any_event(self, event):
            if event.is_directory:
                return
            with lock:
                for raw in (getattr(event, "dest_path", "") or "", event.src_path or ""):
                    rel = note_path(str(raw)) if raw else None
                    if rel:
                        pending["paths"].add(rel)
                        pending["last"] = time.time()
                if len(pending["paths"]) > 200:
                    pending["overflow"] = True  # bulk change: cheaper to full-scan

    observer = Observer()
    observer.schedule(Handler(), str(vault), recursive=True)
    observer.start()
    log.info("watching %s", vault)
    try:
        while True:
            time.sleep(0.5)
            with lock:
                ready = pending["paths"] and time.time() - pending["last"] >= debounce
                paths = set(pending["paths"]) if ready else None
                overflow = pending["overflow"]
                if ready:
                    pending["paths"].clear()
                    pending["overflow"] = False
            if not ready:
                continue
            # targeted sync for small edits; full scan for bulk changes
            rep = engine.index() if overflow else engine.index(paths=paths)
            if rep.changed:
                log.info(
                    "synced: +%d ~%d -%d (%d chunks, %.1fs)",
                    rep.added, rep.updated, rep.removed, rep.chunks, rep.seconds,
                )
            if on_sync:
                on_sync(rep)
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join()
