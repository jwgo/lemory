"""Temporal awareness: note dates + recency intent in queries (KR/EN).

Everything here is rule-based and local · no LLM, no API. Two jobs:

1. `doc_date(...)` · when was a note "about"? Priority: frontmatter date
   (date/created/day/updated) > a date in the filename/title (daily notes:
   `2026-07-08.md`, `2026.07.08`, `20260708`) > file mtime.

2. `parse_temporal(query, now)` · does the query care about time?
   * vague recency: 요새/요즘/최근/얼마 전/recently/lately/these days …
     → exponential recency boost, no hard range
   * explicit ranges: 오늘/어제/그저께/이번 주/지난주/이번 달/지난달/N일 전/
     today/yesterday/this week/last week/this month/last month/N days ago
     → boost notes dated inside the range
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

_FILENAME_DATE_RES = [
    re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)"),
    re.compile(r"(?<!\d)(\d{4})\.(\d{2})\.(\d{2})(?!\d)"),
    re.compile(r"(?<!\d)(\d{4})(\d{2})(\d{2})(?!\d)"),
]

_FM_DATE_KEYS = ("date", "created", "day", "updated", "modified")

_FM_VALUE_RES = [
    re.compile(r"(\d{4})-(\d{2})-(\d{2})"),
    re.compile(r"(\d{4})\.(\d{2})\.(\d{2})"),
    re.compile(r"(\d{4})/(\d{2})/(\d{2})"),
]


def _to_epoch(y: int, m: int, d: int) -> Optional[float]:
    try:
        return datetime(y, m, d, 12).timestamp()  # noon: stable across TZ math
    except ValueError:
        return None


def _parse_date_value(value) -> Optional[float]:
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, 12).timestamp()
    if isinstance(value, (int, float)) and value > 1e9:
        return float(value)
    if isinstance(value, str):
        for pat in _FM_VALUE_RES:
            m = pat.search(value)
            if m:
                return _to_epoch(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def doc_date(title: str, path: str, frontmatter_json: str, mtime: float) -> float:
    """Best-effort 'when is this note about' timestamp (epoch seconds)."""
    try:
        fm = json.loads(frontmatter_json) if frontmatter_json else {}
    except json.JSONDecodeError:
        fm = {}
    if isinstance(fm, dict):
        for key in _FM_DATE_KEYS:
            if key in fm:
                ts = _parse_date_value(fm[key])
                if ts:
                    return ts
    for source in (title, path):
        for pat in _FILENAME_DATE_RES:
            m = pat.search(source)
            if m:
                ts = _to_epoch(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                if ts:
                    return ts
    return mtime


# --------------------------------------------------------------- query intent
@dataclass
class TemporalIntent:
    recent: bool = False                      # vague "recent" prior
    range_start: Optional[float] = None       # explicit window (epoch)
    range_end: Optional[float] = None

    @property
    def active(self) -> bool:
        return self.recent or self.range_start is not None


_RECENT_RE = re.compile(
    # 최종/결국: 결정-회상의 최신성 표지 ("최종적으로 뭐 쓰기로 했지?" =
    # 가장 나중의 결정) — 에이전트 세션 기억에서 번복된 결정의 옛 세션이
    # 이기는 실패를 AgentMemQA가 잡아서 추가 (decision trap 0.5 → 0)
    r"요새|요즘|최근|얼마\s*전|근래|이즈음|지금|현재|이제|최종|결국|"
    r"\brecently\b|\blately\b|\bthese\s+days\b|\bnowadays\b|\bcurrently\b|"
    r"\bright\s+now\b|\bcurrent\b",
    re.IGNORECASE,
)

_N_DAYS_RE = re.compile(r"(\d+)\s*(일|날)\s*전|\b(\d+)\s*days?\s+ago\b", re.IGNORECASE)
_N_WEEKS_RE = re.compile(r"(\d+)\s*주\s*전|\b(\d+)\s*weeks?\s+ago\b", re.IGNORECASE)
_LAST_N_DAYS_RE = re.compile(r"지난\s*(\d+)\s*일|\blast\s+(\d+)\s+days\b", re.IGNORECASE)


def _day_bounds(d: date) -> tuple[float, float]:
    start = datetime(d.year, d.month, d.day)
    return start.timestamp(), (start + timedelta(days=1)).timestamp()


def parse_temporal(query: str, now: Optional[float] = None) -> TemporalIntent:
    now = now or time.time()
    today = datetime.fromtimestamp(now).date()
    q = query.lower()

    def window(days_back_start: int, days_back_end: int = 0) -> TemporalIntent:
        s, _ = _day_bounds(today - timedelta(days=days_back_start))
        _, e = _day_bounds(today - timedelta(days=days_back_end))
        return TemporalIntent(recent=True, range_start=s, range_end=e)

    if re.search(r"그저께|그제|\bday\s+before\s+yesterday\b", q):
        return window(2, 2)
    if re.search(r"어제|\byesterday\b", q):
        return window(1, 1)
    if re.search(r"오늘|\btoday\b", q):
        return window(0, 0)
    if re.search(r"지난\s*주|지난주|\blast\s+week\b", q):
        monday = today - timedelta(days=today.weekday())
        return TemporalIntent(
            recent=True,
            range_start=_day_bounds(monday - timedelta(days=7))[0],
            range_end=_day_bounds(monday - timedelta(days=1))[1],
        )
    if re.search(r"이번\s*주|금주|\bthis\s+week\b", q):
        monday = today - timedelta(days=today.weekday())
        return TemporalIntent(recent=True, range_start=_day_bounds(monday)[0],
                              range_end=_day_bounds(today)[1])
    if re.search(r"지난\s*달|지난달|\blast\s+month\b", q):
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        first_prev = last_prev.replace(day=1)
        return TemporalIntent(recent=True, range_start=_day_bounds(first_prev)[0],
                              range_end=_day_bounds(last_prev)[1])
    if re.search(r"이번\s*달|이달|\bthis\s+month\b", q):
        return TemporalIntent(recent=True,
                              range_start=_day_bounds(today.replace(day=1))[0],
                              range_end=_day_bounds(today)[1])
    m = re.search(r"(?<!\d)(\d{1,2})\s*월(?!\d)", q) or re.search(
        r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\b",
        q,
    )
    if m:
        month_names = ["january", "february", "march", "april", "may", "june", "july",
                       "august", "september", "october", "november", "december"]
        raw = m.group(1)
        month = int(raw) if raw.isdigit() else month_names.index(raw) + 1
        if 1 <= month <= 12:
            year = today.year if month <= today.month else today.year - 1
            first = date(year, month, 1)
            last = (date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)) - timedelta(days=1)
            return TemporalIntent(recent=True, range_start=_day_bounds(first)[0],
                                  range_end=_day_bounds(min(last, today))[1])

    m = _N_DAYS_RE.search(q)
    if m:
        n = int(next(g for g in m.groups() if g))
        return window(n + 1, max(0, n - 1))  # ±1 day slack around "N days ago"
    m = _N_WEEKS_RE.search(q)
    if m:
        n = int(next(g for g in m.groups() if g))
        return window(n * 7 + 3, max(0, n * 7 - 3))
    m = _LAST_N_DAYS_RE.search(q)
    if m:
        n = int(next(g for g in m.groups() if g))
        return window(n, 0)

    if _RECENT_RE.search(q):
        return TemporalIntent(recent=True)
    return TemporalIntent()


def recency_weight(doc_ts: float, now: float, half_life_days: float) -> float:
    """Exponential decay in [0, 1]: 1.0 for 'right now', 0.5 at one half-life.

    Age is quantized to week bands: to a person, "요새/최근" doesn't
    distinguish today from five days ago · within a band, relevance must
    decide the order; across bands, recency does.
    """
    age_days = max(0.0, (now - doc_ts) / 86400.0)
    banded = (age_days // 7.0) * 7.0
    return 0.5 ** (banded / max(half_life_days, 0.1))
