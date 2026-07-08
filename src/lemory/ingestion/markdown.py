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


def chunk_note(
    body: str, chunk_chars: int = 1400, overlap: int = 180, min_chars: int = 120
) -> list[tuple[str, str]]:
    """Heading-aware chunking. Returns [(heading_breadcrumb, chunk_text)].

    Each chunk stays within one section; long sections are split on paragraph
    boundaries with overlap. Tiny trailing pieces merge into the previous
    chunk. Title context is added later by embed_text_for_chunk, not here.
    """
    chunks: list[tuple[str, str]] = []
    for sec in split_sections(body):
        plain = render_plain(sec.text)
        if not plain:
            continue
        if len(plain) <= chunk_chars:
            chunks.append((sec.heading, plain))
            continue
        paras = re.split(r"\n\n+", plain)
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
