"""Shared benchmark utilities: metrics, engine construction, query prewarm."""

from __future__ import annotations

import collections
import json
import os
import re
import string
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from lemory.config import LemoryConfig
from lemory.engine import Engine
from lemory.store import Store

BENCH_DIR = Path(__file__).parent
WORK = BENCH_DIR / "work"
DATA = BENCH_DIR / "data"

# THE system definitions used by every benchmark table. One source of truth:
# a row labeled 'lemory' must mean the same configuration in every report.
SYSTEMS = {
    "lemory": dict(mode="hybrid", graph=True),
    "lemory-nograph": dict(mode="hybrid", graph=False),
    "vector": dict(mode="vector", graph=False),
    "bm25": dict(mode="bm25", graph=False),
}


# ------------------------------------------------------- SQuAD-style scoring
def normalize_answer(s: str) -> str:
    s = s.lower()
    s = "".join(ch for ch in s if ch not in set(string.punctuation))
    s = re.sub(r"\b(a|an|the)\b", " ", s)
    return " ".join(s.split())


def f1_score(prediction: str, gold: str) -> float:
    p = normalize_answer(prediction).split()
    g = normalize_answer(gold).split()
    if not p or not g:
        return float(p == g)
    common = collections.Counter(p) & collections.Counter(g)
    num_same = sum(common.values())
    if num_same == 0:
        return 0.0
    precision = num_same / len(p)
    recall = num_same / len(g)
    return 2 * precision * recall / (precision + recall)


def best_f1(prediction: str, golds: list[str]) -> float:
    return max(f1_score(prediction, g) for g in golds)


def exact_match(prediction: str, golds: list[str]) -> float:
    np_ = normalize_answer(prediction)
    return float(any(np_ == normalize_answer(g) for g in golds))


def answer_in_text(text: str, golds: list[str]) -> bool:
    nt = normalize_answer(text)
    return any(normalize_answer(g) in nt for g in golds if normalize_answer(g))


# ------------------------------------------------------------------- engines
def make_engine(vault: Path, tag: str, **cfg_overrides) -> Engine:
    cfg = LemoryConfig(
        vault=vault,
        data_dir=WORK / f"index-{tag}",
        **cfg_overrides,
    )
    return Engine(cfg)


def prewarm_queries(engine: Engine, queries: list[str]) -> None:
    """Batch-embed all benchmark queries into the cache (saves per-query calls)."""
    keys = [Store.cache_key(engine.cfg.active_embed_model(), engine.cfg.embed_dim, "query", q) for q in queries]
    cached = engine.store.cache_get_many(keys)
    missing = [(k, q) for k, q in zip(keys, queries) if k not in cached]
    if not missing:
        return
    vecs = engine.llm.embed([q for _, q in missing], task_type="RETRIEVAL_QUERY")
    engine.store.cache_put_many({k: vecs[i] for i, (k, _) in enumerate(missing)})


# ------------------------------------------------------------------- ranking
def rank_metrics(ranked_hit_flags: list[list[bool]], ks=(1, 3, 5, 8)) -> dict:
    """ranked_hit_flags[i][r] — whether result r for question i is a gold hit."""
    out = {}
    n = len(ranked_hit_flags)
    for k in ks:
        out[f"recall@{k}"] = sum(any(flags[:k]) for flags in ranked_hit_flags) / n
    rr = 0.0
    for flags in ranked_hit_flags:
        for r, f in enumerate(flags[:10]):
            if f:
                rr += 1.0 / (r + 1)
                break
    out["mrr@10"] = rr / n
    return out


def full_support_metrics(per_q_found: list[tuple[int, int]], ks_label: str = "") -> dict:
    """For multi-hop: per_q_found[i] = (#gold notes found in top-k, #gold notes)."""
    n = len(per_q_found)
    full = sum(1 for f, g in per_q_found if f >= g) / n
    partial = sum(f / g for f, g in per_q_found) / n
    return {f"full_support{ks_label}": full, f"support_recall{ks_label}": partial}


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False))


def load_env() -> None:
    env = Path(__file__).parent.parent / ".env"
    if env.is_file():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k, v)
