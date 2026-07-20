"""Obsidian-flavored markdown parsing and heading-aware chunking."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import yaml

WIKILINK_RE = re.compile(r"\[\[([^\]\|#]+)(?:#[^\]\|]*)?(?:\|([^\]]*))?\]\]")
TAG_RE = re.compile(r"(?:^|\s)#([A-Za-z0-9_\-/]+)")
MDLINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
CODEBLOCK_RE = re.compile(r"```.*?```", re.S)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$", re.M)


@dataclass
class ParsedNote:
    title: str
    frontmatter: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    wikilinks: list[str] = field(default_factory=list)
    body: str = ""  # markdown body without frontmatter


def parse_note(raw: str, title: str) -> ParsedNote:
    frontmatter: dict = {}
    body = raw
    if raw.startswith("---"):
        end = raw.find("\n---", 3)
        if end != -1:
            try:
                fm = yaml.safe_load(raw[3:end])
            except yaml.YAMLError:
                fm = None
            # only treat it as frontmatter if it parses to a mapping —
            # otherwise it's content (e.g. a leading horizontal rule) and
            # stripping it would silently drop indexable text
            if isinstance(fm, dict):
                frontmatter = fm
                body = raw[end + 4 :].lstrip("\n")

    wikilinks = [m.group(1).strip() for m in WIKILINK_RE.finditer(body)]

    tags = set()
    for m in TAG_RE.finditer(CODEBLOCK_RE.sub("", body)):
        tags.add(m.group(1))
    fm_tags = frontmatter.get("tags") or []
    if isinstance(fm_tags, str):
        fm_tags = [t.strip() for t in re.split(r"[,\s]+", fm_tags) if t.strip()]
    for t in fm_tags:
        if isinstance(t, str):
            tags.add(t.lstrip("#"))

    return ParsedNote(
        title=title, frontmatter=frontmatter, tags=sorted(tags),
        wikilinks=wikilinks, body=body,
    )


def render_plain(md: str) -> str:
    """Light markdown -> plain text for indexing (keeps content, drops syntax)."""
    text = md
    text = WIKILINK_RE.sub(lambda m: (m.group(2) or m.group(1)).strip(), text)
    text = MDLINK_RE.sub(r"\1", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.M)
    text = re.sub(r"[*_`>]{1,3}", "", text)
    text = re.sub(r"^\s*[-+*]\s+", "- ", text, flags=re.M)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


@dataclass
class Section:
    heading: str  # breadcrumb like "H1 > H2"
    text: str


def split_sections(body: str) -> list[Section]:
    """Split a note body into heading-scoped sections with breadcrumbs."""
    matches = list(HEADING_RE.finditer(body))
    sections: list[Section] = []
    trail: list[tuple[int, str]] = []  # (level, heading text)

    def breadcrumb() -> str:
        return " > ".join(h for _, h in trail)

    if not matches:
        t = body.strip()
        return [Section("", t)] if t else []

    pre = body[: matches[0].start()].strip()
    if pre:
        sections.append(Section("", pre))
    for i, m in enumerate(matches):
        level = len(m.group(1))
        heading = m.group(2).strip()
        while trail and trail[-1][0] >= level:
            trail.pop()
        trail.append((level, heading))
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        content = body[m.end() : end].strip()
        if content:
            sections.append(Section(breadcrumb(), content))
    return sections


# chat-import layout: '**나**: ...' / '**아리**: ...' paragraphs. Matched on
# the PLAIN rendering (render_plain strips the **), so the name group must not
# cross a colon or newline and stays short — prose with a colon mid-sentence
# ("결론: ...") can match one line, which is why layout detection requires a
# MAJORITY of paragraphs to match, never a single one.
CHAT_SPEAKER_RE = re.compile(r"^([^:：\n]{1,24})\s*[:：]\s*\S")

# Quality gate for burst chunking: a burst this short and digit-free is chat
# filler ("헐 대박", "고마워!") — real facts are longer or carry a number.
# Filler is still indexed (packed together), it just never stands alone.
_BURST_MIN_CONTENT = 25

# Heading marker for focused burst chunks (mirrors Store.ENRICH_HEADING's
# role; Store.BURST_HEADING must stay equal — storage can't import ingestion
# without a cycle, a test pins the two literals together). Burst chunks are
# VECTOR-ONLY: lexically they add nothing (the packed sibling contains every
# token) and their short length distorts BM25 normalization — measured on
# clean RoleMemQA long-type, a focused template chunk flooded the lexical
# leg above the gold note.
BURST_HEADING = "↔ 발췌"


def _is_chat_section(paras: list[str]) -> bool:
    if len(paras) < 4:
        return False
    hits = sum(1 for p in paras if CHAT_SPEAKER_RE.match(p))
    return hits / len(paras) >= 0.6


def _chat_burst_chunks(
    paras: list[str], chunk_chars: int, overlap: int
) -> list[str]:
    """Focused burst chunks for a chat-layout section (Cerebras-style).

    Uniform packing dilutes a fact line's embedding with the filler around
    it · measured messy-chat doc@1 dropped 16pt vs clean notes. Consecutive
    same-speaker messages form a burst; a burst that carries signal (the
    quality gate: enough content or a number) becomes its own chunk,
    prefixed with the previous turn when that turn was weak (a question or
    reaction · the antecedent a reply needs; duplicating a STRONG previous
    burst instead double-counts it in rank fusion, which measurably let old
    values outrank newer ones on update questions).

    These are ADDITIONAL granularity: callers index them alongside the
    normal packed chunks, which keep doc-level keyword aggregation (two
    weak mentions in one note still add up) · dropping the packed layer
    measurably broke exactly that."""
    bursts: list[str] = []
    speaker = None
    for p in paras:
        m = CHAT_SPEAKER_RE.match(p)
        who = m.group(1).strip() if m else speaker
        if bursts and who == speaker:
            bursts[-1] += "\n" + p
        else:
            bursts.append(p)
        speaker = who

    def content_len(burst: str) -> int:
        # signal length = text minus the speaker tags
        return sum(
            len(CHAT_SPEAKER_RE.sub("", line, count=1).strip())
            for line in burst.splitlines()
        )

    chunks: list[str] = []
    prev_tail = ""
    prev_strong = False
    for b in bursts:
        strong = content_len(b) >= _BURST_MIN_CONTENT or any(
            c.isdigit() for c in b)
        if not strong:
            # filler never gets a focused chunk — it lives in the packed
            # layer the caller indexes anyway
            prev_tail, prev_strong = b, False
            continue
        carry = prev_tail if (prev_tail and not prev_strong) else ""
        text = f"{carry[-overlap:]}\n{b}" if carry and overlap > 0 else b
        # a single huge burst still respects the size cap via hard splits
        while len(text) > chunk_chars * 1.5:
            cut = text.rfind(" ", max(chunk_chars - 200, 1), chunk_chars)
            cut = cut if cut > 0 else chunk_chars
            chunks.append(text[:cut].strip())
            text = text[cut - min(overlap, cut // 2):]
        chunks.append(text.strip())
        prev_tail, prev_strong = b, True
    return [c for c in chunks if c]


def chunk_note(
    body: str, chunk_chars: int = 882, overlap: int = 180, min_chars: int = 120,
    chat_bursts: bool = True,
) -> list[tuple[str, str]]:
    """Heading-aware chunking. Returns [(heading_breadcrumb, chunk_text)].

    Each chunk stays within one section; long sections are split on paragraph
    boundaries with overlap. Tiny trailing pieces merge into the previous
    chunk. Title context is added later by embed_text_for_chunk, not here.
    Chat-layout sections (speaker-prefixed paragraphs, e.g. chat imports)
    additionally get focused speaker-burst chunks on top of the packed ones
    · multi-granularity, see _chat_burst_chunks.
    """
    chunks: list[tuple[str, str]] = []
    for sec in split_sections(body):
        plain = render_plain(sec.text)
        if not plain:
            continue
        sec_paras = re.split(r"\n\n+", plain)
        if chat_bursts and _is_chat_section(sec_paras):
            chunks.extend(
                (BURST_HEADING, t)
                for t in _chat_burst_chunks(sec_paras, chunk_chars, overlap))
            # fall through: the packed layer is still indexed below
        if len(plain) <= chunk_chars:
            chunks.append((sec.heading, plain))
            continue
        paras = sec_paras
        buf = ""
        for p in paras:
            if buf and len(buf) + len(p) + 2 > chunk_chars:
                chunks.append((sec.heading, buf.strip()))
                tail = buf[-overlap:] if overlap > 0 else ""
                buf = (tail + "\n" + p) if tail else p
            else:
                buf = f"{buf}\n\n{p}" if buf else p
            # a single paragraph can still exceed the limit: hard-split it
            while len(buf) > chunk_chars * 1.5:
                cut = buf.rfind(" ", max(chunk_chars - 200, 1), chunk_chars)
                cut = cut if cut > 0 else chunk_chars
                chunks.append((sec.heading, buf[:cut].strip()))
                # cap the carried overlap so the loop always makes progress,
                # even with pathological overlap >= chunk_chars configs
                back = min(overlap, cut // 2)
                buf = buf[cut - back:]
        if buf.strip():
            if chunks and chunks[-1][0] == sec.heading and len(buf.strip()) < min_chars:
                prev_h, prev_t = chunks[-1]
                chunks[-1] = (prev_h, prev_t + "\n\n" + buf.strip())
            else:
                chunks.append((sec.heading, buf.strip()))
    return chunks


def embed_text_for_chunk(title: str, heading: str, text: str) -> str:
    """Contextualized text sent to the embedder (title/heading breadcrumb)."""
    ctx = title if not heading else f"{title} > {heading}"
    return f"{ctx}\n\n{text}"
