"""Query-intent heuristics (rule-based, KR/EN, zero API).

`is_enumeration_query` detects questions whose answer is a LIST or COUNT
scattered across notes ("What books has Melanie read?", "어떤 활동들을 했지?",
"How many times..."). Such questions need wider retrieval than a single-fact
lookup: the evidence is several separate mentions, each individually a weak
match. ask() doubles its retrieval depth for them.
"""

from __future__ import annotations

import re

_EN_LIST_RE = re.compile(
    r"\b(all|every|each|list|besides|apart from|other than|how many|how often|"
    r"how much|what (?:are|were)|which (?:are|were))\b",
    re.IGNORECASE,
)
# "What books has ...", "Which cities does ..." — interrogative + plural noun
# (auxiliaries like does/has/is are excluded so "What does X mean?" stays single)
_EN_PLURAL_RE = re.compile(
    r"^\s*(what|which)\s+"
    r"(?:(?!does\b|has\b|is\b|was\b|kind\b|sort\b)\w+\s+){0,2}"
    r"(?!does\b|has\b|is\b|was\b|kind\b|sort\b)(\w{3,}(?<!s)(?<!')s)\b",
    re.IGNORECASE,
)
_KR_LIST_RE = re.compile(
    r"모두|전부|몇\s*(개|번|명|권|가지)|얼마나\s*(자주|많이)|어떤\s*것들|뭐들|"
    r"들(?:을|이|은|도)?\s*(있|했|말했|언급|뭐|무엇)"
)


def is_enumeration_query(query: str) -> bool:
    q = query.strip()
    return bool(_EN_LIST_RE.search(q) or _EN_PLURAL_RE.match(q) or _KR_LIST_RE.search(q))


def adaptive_k(query: str, k: int, multiplier: float = 2.0, cap: int = 24) -> int:
    """Retrieval depth for a query: widened for enumeration/count questions."""
    if multiplier > 1.0 and is_enumeration_query(query):
        return min(cap, max(k, int(round(k * multiplier))))
    return k
