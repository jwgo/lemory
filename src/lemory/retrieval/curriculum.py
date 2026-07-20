"""Curriculum ordering of retrieved evidence · CDS-inspired.

"Many-Shot CoT-ICL: Making In-Context Learning Truly Learn"
(Chung, Liu, Yu, Yeung · ICML 2026, arXiv:2605.13511) shows that long
contexts work better as a *structured curriculum* than as a relevance-sorted
buffer, and that orderings forming a smooth trajectory in embedding space
(low total curvature between successive items) measurably improve reasoning.

Lemory's analog: the evidence chunks fed to ask(). Fusion rank is the right
*selection* order but a poor *presentation* order · rank-adjacent chunks are
often topically unrelated, so the context zig-zags. This module reorders the
selected chunks (selection unchanged) into a smooth path:

  1. anchor: start at the chunk most similar to the question · the natural
     on-topic entry point (in multi-hop cases this is the bridge note, so the
     answer note it links to follows it, reading in dependency order);
  2. greedy TSP-style walk: repeatedly step to the unvisited chunk with the
     lowest transition cost = embedding distance + a curvature penalty for
     sharp turns relative to the previous step (the paper's Eq. 4 proxy).

Cost: O(k²) dot products over vectors already in memory. No LLM, no API.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from ..storage import ChunkHit

if TYPE_CHECKING:
    from ..engine import Engine

# weight of the curvature (turn) penalty vs plain embedding distance; the
# paper's TSP heuristic likewise mixes spatial proximity with a local
# curvature proxy rather than optimizing angles alone
CURVATURE_WEIGHT = 0.5


def curriculum_order(engine: "Engine", query_vec: np.ndarray | None,
                     hits: list[ChunkHit]) -> list[ChunkHit]:
    """Reorder hits for presentation. Returns a permutation of `hits`;
    citation numbers are assigned after reordering, so [n] stays consistent."""
    if len(hits) <= 2:
        return hits
    vecs = engine.store.chunk_vectors([h.chunk_id for h in hits])
    with_vec = [h for h in hits if h.chunk_id in vecs]
    without_vec = [h for h in hits if h.chunk_id not in vecs]
    if len(with_vec) <= 2:
        return hits

    e = np.stack([vecs[h.chunk_id] for h in with_vec])  # unit-norm rows

    # anchor: most query-similar chunk; fall back to fusion rank 1
    if query_vec is not None:
        start = int(np.argmax(e @ query_vec.astype(np.float32)))
    else:
        start = 0

    n = len(with_vec)
    sim = e @ e.T  # cosine, since rows are unit-norm
    visited = [start]
    remaining = set(range(n)) - {start}
    prev_dir: np.ndarray | None = None
    while remaining:
        cur = visited[-1]
        best, best_cost = None, None
        for cand in remaining:
            cost = 1.0 - float(sim[cur, cand])
            if prev_dir is not None:
                step = e[cand] - e[cur]
                norm = float(np.linalg.norm(step))
                if norm > 1e-9:
                    turn = 1.0 - float(step @ prev_dir) / norm  # 0 straight, 2 reversal
                    cost += CURVATURE_WEIGHT * 0.5 * turn
            if best_cost is None or cost < best_cost:
                best, best_cost = cand, cost
        visited.append(best)
        remaining.discard(best)
        step = e[best] - e[visited[-2]]
        norm = float(np.linalg.norm(step))
        prev_dir = step / norm if norm > 1e-9 else prev_dir

    ordered = [with_vec[i] for i in visited]
    return ordered + without_vec  # vectorless chunks keep their rank order, last


def path_smoothness(engine: "Engine", hits: list[ChunkHit]) -> float:
    """Mean cosine between successive chunks · diagnostic/testing metric."""
    vecs = engine.store.chunk_vectors([h.chunk_id for h in hits])
    pairs = [
        (vecs[a.chunk_id], vecs[b.chunk_id])
        for a, b in zip(hits, hits[1:])
        if a.chunk_id in vecs and b.chunk_id in vecs
    ]
    if not pairs:
        return 0.0
    return float(np.mean([float(u @ v) for u, v in pairs]))
