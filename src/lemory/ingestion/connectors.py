"""Connector SDK: pull external sources into the vault as plain notes.

Cerebras' knowledge base feeds on connectors (Slack, Drive, e-mail …); the
Lemory equivalent keeps the local-first invariant: a connector is just a
Python file the USER owns, and its output is ordinary markdown notes in the
vault — searchable, editable, deletable, diffable like everything else. No
second store, no daemon, no credentials held by Lemory.

Contract (either entry point):

    # incremental — state round-trips between runs (cursor, etag, seen ids…)
    def pull(state: dict) -> tuple[Iterable[dict], dict]: ...

    # simple — stateless full fetch (idempotent by note path)
    def fetch() -> Iterable[dict]: ...

Each item is a dict:
    {"title": str,                # required
     "body": str,                 # required, markdown
     "id": str,                   # optional stable id — becomes the filename,
                                  #   so retitled items update in place
     "date": "YYYY-MM-DD",        # optional, frontmatter date
     "tags": ["a", "b"],          # optional
     "folder": "서브폴더"}         # optional override under the base folder

Runs are idempotent: an item writes to a deterministic path and overwrites
what's there (source notes are the connector's derived data — the external
system stays the source of truth). Nothing is ever deleted.

    lemory connect ./my_rss.py             # writes to 가져옴/my_rss/
    lemory connect ./slack_dump.py --folder 슬랙
"""

from __future__ import annotations

import importlib.util
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from ..engine import Engine

_STATE_KEY = "connector_state:{name}"
# forbid path tricks in filenames; keep Hangul/word chars, collapse the rest
_UNSAFE_RE = re.compile(r"[^\w가-힣 .()\[\]-]+")


@dataclass
class ConnectorReport:
    name: str
    written: list[str] = field(default_factory=list)  # vault-relative paths
    skipped: int = 0  # items missing required fields


def _load_module(source: Path):
    spec = importlib.util.spec_from_file_location(f"lemory_connector_{source.stem}", source)
    if spec is None or spec.loader is None:
        raise ValueError(f"connector를 불러올 수 없습니다: {source}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _safe_name(raw: str) -> str:
    name = _UNSAFE_RE.sub(" ", raw).strip()
    name = re.sub(r"\s+", " ", name)
    return name[:120] or "untitled"


def run_connector(engine: "Engine", source: Path, folder: str = "") -> ConnectorReport:
    """Execute a connector file and write its items as vault notes.

    The connector is user-supplied code and runs with the user's own
    privileges — the same trust level as running the script directly."""
    source = Path(source)
    mod = _load_module(source)
    name = source.stem
    rep = ConnectorReport(name=name)
    store = engine.store

    state_raw = store.get_meta(_STATE_KEY.format(name=name))
    state = json.loads(state_raw) if state_raw else {}

    if hasattr(mod, "pull"):
        items, new_state = mod.pull(dict(state))
    elif hasattr(mod, "fetch"):
        items, new_state = mod.fetch(), state
    else:
        raise ValueError(
            f"{source.name}: connector는 pull(state) 또는 fetch()를 정의해야 합니다")

    vault = engine.cfg.resolved_vault()
    base_rel = folder or f"가져옴/{name}"

    for item in items:
        title = str(item.get("title") or "").strip()
        body = str(item.get("body") or "").strip()
        if not title or not body:
            rep.skipped += 1
            continue
        raw_sub = str(item.get("folder") or "").strip()
        sub = _safe_name(raw_sub) if raw_sub else ""
        rel_dir = f"{base_rel}/{sub}" if sub else base_rel
        fname = _safe_name(str(item.get("id") or title))
        rel = f"{rel_dir}/{fname}.md"
        target = (vault / rel).resolve()
        if not target.is_relative_to(vault.resolve()):
            rep.skipped += 1
            continue
        tags = [str(t).strip().lstrip("#") for t in (item.get("tags") or []) if str(t).strip()]
        fm = ["---", f"source: connector:{name}"]
        date = str(item.get("date") or "").strip()
        if date:
            fm.append(f"date: {date}")
        fm.append("tags: [" + ", ".join(["connector"] + tags) + "]")
        fm.append("---")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "\n".join(fm) + f"\n\n# {title}\n\n{body}\n", encoding="utf-8")
        rep.written.append(rel)

    if new_state != state:
        store.set_meta(_STATE_KEY.format(name=name), json.dumps(new_state, ensure_ascii=False))
    if rep.written:
        engine.index(paths=set(rep.written))
    return rep
