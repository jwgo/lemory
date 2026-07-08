"""나무마크(NamuMark) → Obsidian markdown converter.

나무위키 문서 원문(나무마크)을 Lemory가 인덱싱하는 마크다운으로 변환한다.
[[내부링크]]는 옵시디언 위키링크로 그대로 보존되어 Lemory의 그래프 확장이
나무위키의 문서 간 연결을 그대로 활용한다.

Covers the constructs that dominate real 나무위키 documents:
  = 제목 =            -> # 제목  (level = number of '=')
  [[문서]] [[문서|표시]] -> [[문서]] / [[문서|표시]]  (외부/분류/파일 링크는 정리)
  '''굵게''' ''기울임'' -> **굵게** *기울임*
  {{{#!wiki ...}}} {{{#색 ...}}} -> 내용만 유지
  {{{+n 텍스트}}}      -> 텍스트
  [* 각주] [*A 각주]   -> (각주: ...)
  ||표|| 셀 ||         -> | 표 | 셀 |
  [include(...)], [목차], [각주], [youtube(...)] 등 매크로 제거
  ~~취소선~~ __밑줄__  -> 텍스트만 유지
"""

from __future__ import annotations

import re

_MACRO_RE = re.compile(
    r"\[(?:include|목차|tableofcontents|각주|footnote|youtube|nicovideo|kakaotv|"
    r"navertv|age|dday|pagecount|anchor|ruby)\([^)]*\)\]|\[(?:목차|각주|clearfix)\]",
    re.IGNORECASE,
)
_HEADING_RE = re.compile(r"^\s*(=+)#?\s*(.*?)\s*#?(=+)\s*$", re.M)
_FOOTNOTE_RE = re.compile(r"\[\*[^ \]]*\s*([^\[\]]*(?:\[[^\]]*\][^\[\]]*)*)\]")
_LINK_RE = re.compile(r"\[\[([^\]|]+?)(?:\|([^\]]*?))?\]\]")
_BRACE_OPEN_RE = re.compile(r"\{\{\{(?:#![a-z]+ ?[^\n ]*|#[0-9a-zA-Z,]+|\+[1-5]|-[1-5])?\s*", )
_TEXT_STYLES = [
    (re.compile(r"'''(.+?)'''", re.S), r"**\1**"),
    (re.compile(r"''(.+?)''", re.S), r"*\1*"),
    (re.compile(r"~~(.+?)~~", re.S), r"\1"),
    (re.compile(r"--(.+?)--", re.S), r"\1"),
    (re.compile(r"__(.+?)__", re.S), r"\1"),
    (re.compile(r"\^\^(.+?)\^\^", re.S), r"\1"),
    (re.compile(r",,(.+?),,", re.S), r"\1"),
]


def _convert_link(m: re.Match) -> str:
    target = m.group(1).strip()
    label = (m.group(2) or "").strip()
    if target.startswith(("http://", "https://", "//")):
        return label or target
    if target.startswith(("분류:", "파일:", "틀:")):
        return ""
    # drop anchors for the link target, keep display text
    clean = target.split("#")[0].strip()
    if not clean:
        return label
    if label and label != clean:
        return f"[[{clean}|{label}]]"
    return f"[[{clean}]]"


def extract_categories(namu: str) -> list[str]:
    return [m.group(1).split("#")[0].strip()
            for m in re.finditer(r"\[\[분류:([^\]|]+)(?:\|[^\]]*)?\]\]", namu)]


def extract_links(md: str) -> list[str]:
    return [m.group(1).strip() for m in re.finditer(r"\[\[([^\]|#]+)", md)]


def namu_to_markdown(namu: str, title: str) -> str:
    text = namu
    text = _MACRO_RE.sub("", text)
    # tables first (before pipes get mangled): "|| a || b ||" -> "| a | b |"
    lines = []
    for line in text.splitlines():
        if line.strip().startswith("||"):
            cells = [c.strip() for c in re.split(r"\|\|+", line) if c.strip()]
            line = "| " + " | ".join(cells) + " |" if cells else ""
        lines.append(line)
    text = "\n".join(lines)

    text = _HEADING_RE.sub(lambda m: "#" * min(len(m.group(1)), 6) + " " + m.group(2), text)
    text = _FOOTNOTE_RE.sub(lambda m: f" ({m.group(1).strip()})" if m.group(1).strip() else "", text)
    text = _LINK_RE.sub(_convert_link, text)
    # namu bullets need leading whitespace (' * item') — convert BEFORE bold
    # so '**bold**' at line start is never mistaken for a bullet
    text = re.sub(r"^[ \t]+\*\s+", "- ", text, flags=re.M)
    for pat, rep in _TEXT_STYLES:
        text = pat.sub(rep, text)
    # brace blocks: strip the wrappers, keep inner content
    text = _BRACE_OPEN_RE.sub("", text.replace("}}}", ""))
    text = re.sub(r"\[\[\]\]", "", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
