"""Linkless-vault ablation: does the semantic-fallback graph recover multihop?

The honest weak spot: Lemory's multihop 1.000 reads the user's [[wikilinks]].
A user who never links gets none of that. This measures exactly that regime —
the committed multihop vault with EVERY [[wikilink]] stripped to plain text —
across four configs, keyless local, full-support@8:

    bare        graph signals all off (mentions off, sem off)
    mentions    unlinked title mentions only (previous default behavior)
    sem         semantic fallback links only
    default     mentions + sem (the shipped default after the sem-links change)

    python benchmarks/run_linkless.py
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from common import WORK, full_support_metrics, save_json  # noqa: E402

from lemory.config import LemoryConfig  # noqa: E402
from lemory.engine import Engine  # noqa: E402

DATA = Path(__file__).parent / "data" / "multihop"
K = 8
_WIKI = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")


def delink_vault(obfuscate_titles: bool = False) -> Path:
    """Copy of the multihop vault with [[links]] flattened to plain text.
    obfuscate_titles additionally removes verbatim title mentions from OTHER
    notes' bodies — the regime where mention-links can't fire either (a user
    who writes 'the author', not the exact note title)."""
    out = Path(tempfile.mkdtemp()) / "vault"
    shutil.copytree(DATA / "vault", out)
    titles = [f.stem for f in out.rglob("*.md")]
    for f in out.rglob("*.md"):
        text = _WIKI.sub(r"\1", f.read_text(encoding="utf-8"))
        if obfuscate_titles:
            for t in titles:
                if t != f.stem:
                    text = text.replace(t, "the aforementioned")
        f.write_text(text, encoding="utf-8")
    return out


CONFIGS = {
    "bare": dict(mention_links=False, semantic_links=False),
    "mentions": dict(mention_links=True, semantic_links=False),
    "sem": dict(mention_links=False, semantic_links=True),
    "default": dict(mention_links=True, semantic_links=True),
}


def main() -> None:
    questions = json.loads((DATA / "questions.json").read_text())
    vault = delink_vault()
    n_links = sum(len(_WIKI.findall(f.read_text())) for f in vault.rglob("*.md"))
    print(f"delinked vault: {len(list(vault.rglob('*.md')))} notes, "
          f"{n_links} wikilinks remaining (must be 0)")
    results = {}
    for name, overrides in CONFIGS.items():
        eng = Engine(LemoryConfig(vault=vault, data_dir=WORK / f"linkless-{name}",
                                  provider="local", **overrides))
        eng.index()
        per_q = []
        for q in questions:
            hits = eng.search(q["q"], k=K)
            titles = {h.title for h in hits}
            per_q.append((sum(1 for g in q["gold_notes"] if g in titles),
                          len(q["gold_notes"])))
        links = eng.store.link_count()
        eng.close()
        m = full_support_metrics(per_q, "@8")
        results[name] = {**{k: round(v, 4) for k, v in m.items()}, "edges": links}
        print(f"{name:9} full-support@8={m['full_support@8']:.3f} "
              f"support-recall@8={m['support_recall@8']:.3f} edges={links}")
    # regime 2: titles obfuscated too — mention-links CANNOT fire, the only
    # possible graph signal is semantic similarity
    vault2 = delink_vault(obfuscate_titles=True)
    for name, overrides in (("obfusc-bare", CONFIGS["bare"]),
                            ("obfusc-sem", CONFIGS["sem"])):
        eng = Engine(LemoryConfig(vault=vault2, data_dir=WORK / f"linkless-{name}",
                                  provider="local", **overrides))
        eng.index()
        per_q = []
        for q in questions:
            hits = eng.search(q["q"], k=K)
            titles = {h.title for h in hits}
            per_q.append((sum(1 for g in q["gold_notes"] if g in titles),
                          len(q["gold_notes"])))
        links = eng.store.link_count()
        eng.close()
        m = full_support_metrics(per_q, "@8")
        results[name] = {**{k: round(v, 4) for k, v in m.items()}, "edges": links}
        print(f"{name:12} full-support@8={m['full_support@8']:.3f} "
              f"support-recall@8={m['support_recall@8']:.3f} edges={links}")
    save_json(WORK / "results_linkless.json", results)


if __name__ == "__main__":
    main()
