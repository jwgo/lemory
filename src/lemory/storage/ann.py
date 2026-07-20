"""IVF-flat ANN index over int8-quantized unit vectors · numpy only.

Why this exists: the exact path (`matrix @ q` over float32) is perfect up to
tens of thousands of chunks, but it is memory-bandwidth bound · at 1M chunks
every query streams ~3 GB. This index keeps vectors int8 at rest (4× smaller)
and only scans the clusters nearest the query (IVF), so latency stays in the
tens of milliseconds while recall vs exact search stays high at sane nprobe
(measured in benchmarks/bench_scale.py; numbers in BENCHMARKS.md).

Design constraints, in order:
  1. zero new dependencies (numpy only, like the rest of Lemory)
  2. exact-search behaviour below the threshold · small vaults never pay
     any accuracy tax; the store switches to IVF only above ann_threshold
  3. deterministic builds (seeded k-means) so benchmarks are reproducible

Layout: vectors are stored grouped by cluster (one contiguous int8 block per
cluster) so a probe is a slice, not a gather. Quantization is symmetric with
one global scale · quantized dot products are proportional to true dots, so
ranking survives; residual error only reorders near-ties.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

import numpy as np

log = logging.getLogger("lemory.ann")

_KMEANS_SAMPLE = 25_600   # training subsample; assignment still covers all rows
_KMEANS_ITERS = 8
_SEED = 1337


def _kmeans(sample: np.ndarray, nlist: int, iters: int = _KMEANS_ITERS) -> np.ndarray:
    """Plain Lloyd on a subsample. Unit-vector data → spherical k-means
    (centroids re-normalized each iteration, similarity = dot)."""
    rng = np.random.default_rng(_SEED)
    n = sample.shape[0]
    nlist = min(nlist, n)
    centroids = sample[rng.choice(n, size=nlist, replace=False)].copy()
    for _ in range(iters):
        assign = np.argmax(sample @ centroids.T, axis=1)
        for j in range(nlist):
            members = sample[assign == j]
            if len(members):
                c = members.mean(axis=0)
                norm = np.linalg.norm(c)
                if norm > 1e-9:
                    centroids[j] = c / norm
            else:  # dead centroid: respawn on a random point
                centroids[j] = sample[rng.integers(n)]
    return centroids.astype(np.float32)


def _auto_nlist(n: int) -> int:
    # ~4·sqrt(n): keeps the probed fraction small while the centroid scan
    # itself stays negligible (measured at 1M: nlist 4000 → 3.9ms/query
    # vs nlist 2000 → 15.9ms at identical recall)
    return int(np.clip(4 * np.sqrt(n), 64, 4096))


@dataclass
class IVFFlatIndex:
    centroids: np.ndarray      # [nlist, d] float32, unit rows
    offsets: np.ndarray        # [nlist+1] int64 — cluster j occupies rows offsets[j]:offsets[j+1]
    vectors: np.ndarray        # [n, d] int8, grouped by cluster
    ids: np.ndarray            # [n] int64 chunk ids, aligned with `vectors`
    scale: float               # int8 = round(float32 * scale)
    _pos: Optional[dict[int, int]] = field(default=None, repr=False)
    _fingerprint: str = field(default="", repr=False)

    @property
    def size(self) -> int:
        return int(self.vectors.shape[0])

    # ------------------------------------------------------------------ build
    @classmethod
    def build(
        cls,
        blocks: Iterable[tuple[np.ndarray, np.ndarray]],
        total: int,
        dim: int,
        nlist: Optional[int] = None,
        centroids: Optional[np.ndarray] = None,
        scale: Optional[float] = None,
    ) -> "IVFFlatIndex":
        """Build from (float32_block, id_block) chunks streamed out of SQLite ·
        the full n×d float matrix is never materialized (that's the whole point
        of switching to ANN at scale).

        `blocks` may be an iterable OR a zero-arg factory returning a fresh
        iterable. When training needs two passes, a factory streams each pass
        independently; a plain iterable is materialized once (fine for the
        small in-memory callers · tests, benchmarks). The store passes its
        cursor factory, so the 1M-chunk build peaks at one block, not 3 GB.

        Pass `centroids` (+ its `scale`) from a previous build for an
        assignment-only rebuild · the cheap path when the vault grew a bit."""
        if total <= 0:
            return cls(centroids=np.zeros((0, dim), dtype=np.float32),
                       offsets=np.zeros(1, dtype=np.int64),
                       vectors=np.zeros((0, dim), dtype=np.int8),
                       ids=np.zeros(0, dtype=np.int64), scale=127.0)
        nlist = nlist or _auto_nlist(total)
        rng = np.random.default_rng(_SEED)

        if callable(blocks):
            iter_blocks = blocks                       # re-iterable: true streaming
        else:
            _materialized = list(blocks)               # single-use: hold once
            iter_blocks = lambda: iter(_materialized)  # noqa: E731

        i8 = np.empty((total, dim), dtype=np.int8)
        ids = np.empty(total, dtype=np.int64)
        assign = np.empty(total, dtype=np.int32)

        if centroids is None or scale is None:
            n_sample = min(_KMEANS_SAMPLE, total)
            sample_idx = np.sort(rng.choice(total, size=n_sample, replace=False))
            parts = []
            pos = 0
            max_abs = 1e-6
            for blk, _bid in iter_blocks():            # pass 1: sample + scale
                b = np.asarray(blk, dtype=np.float32)
                max_abs = max(max_abs, float(np.abs(b).max(initial=0.0)))
                lo, hi = np.searchsorted(sample_idx, [pos, pos + len(b)])
                if hi > lo:
                    parts.append(b[sample_idx[lo:hi] - pos])
                pos += len(b)
            centroids = _kmeans(np.vstack(parts), nlist)
            scale = 127.0 / max_abs

        pos = 0
        for blk, bid in iter_blocks():                 # pass 2: assign + quantize
            b = np.asarray(blk, dtype=np.float32)
            span = slice(pos, pos + len(b))
            ids[span] = bid
            assign[span] = np.argmax(b @ centroids.T, axis=1)
            i8[span] = np.clip(np.rint(b * scale), -127, 127).astype(np.int8)
            pos += len(b)
        if pos != total:  # caller lied about `total`; trim defensively
            i8, ids, assign = i8[:pos], ids[:pos], assign[:pos]

        # group rows by cluster (stable sort keeps builds deterministic)
        order = np.argsort(assign, kind="stable")
        i8, ids, assign = i8[order], ids[order], assign[order]
        counts = np.bincount(assign, minlength=centroids.shape[0])
        offsets = np.zeros(centroids.shape[0] + 1, dtype=np.int64)
        np.cumsum(counts, out=offsets[1:])
        return cls(centroids=centroids, offsets=offsets, vectors=i8, ids=ids,
                   scale=float(scale))

    # ----------------------------------------------------------------- search
    def search(self, query: np.ndarray, k: int, nprobe: int = 32) -> list[tuple[int, float]]:
        if self.size == 0 or query.shape[0] != self.vectors.shape[1]:
            return []
        q = query.astype(np.float32)
        nprobe = min(nprobe, self.centroids.shape[0])
        probes = np.argpartition(-(self.centroids @ q), nprobe - 1)[:nprobe]

        spans = [(int(self.offsets[j]), int(self.offsets[j + 1])) for j in probes]
        spans = [s for s in spans if s[1] > s[0]]
        if not spans:
            return []
        # score each probed cluster: contiguous int8 slice → float32 matvec.
        # The astype is the cost, and it is bounded by ~nprobe/nlist of the corpus.
        sims = np.concatenate([self.vectors[a:b].astype(np.float32) @ q for a, b in spans])
        rows = np.concatenate([np.arange(a, b, dtype=np.int64) for a, b in spans])
        sims /= self.scale
        k = min(k, len(sims))
        top = np.argpartition(-sims, k - 1)[:k]
        top = top[np.argsort(-sims[top])]
        return [(int(self.ids[rows[i]]), float(sims[i])) for i in top]

    # ------------------------------------------------------------ row lookups
    def _positions(self) -> dict[int, int]:
        if self._pos is None:
            self._pos = {int(cid): i for i, cid in enumerate(self.ids)}
        return self._pos

    def rows_for(self, chunk_ids: list[int]) -> dict[int, np.ndarray]:
        """Dequantized float32 vectors for specific chunks (error ≤ 0.5/scale
        per component; used only for small candidate sets like graph gating)."""
        pos = self._positions()
        return {
            cid: self.vectors[pos[cid]].astype(np.float32) / self.scale
            for cid in chunk_ids if cid in pos
        }

    # ------------------------------------------------------------ persistence
    def save(self, path: Path, fingerprint: str) -> None:
        tmp = path.with_suffix(".tmp.npz")
        np.savez(
            tmp, centroids=self.centroids, offsets=self.offsets,
            vectors=self.vectors, ids=self.ids,
            scale=np.float64(self.scale),
            fingerprint=np.frombuffer(fingerprint.encode(), dtype=np.uint8),
        )
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path, fingerprint: str) -> Optional["IVFFlatIndex"]:
        idx = cls.load_any(path)
        if idx is None or idx._fingerprint != fingerprint:
            return None
        return idx

    @classmethod
    def load_any(cls, path: Path) -> Optional["IVFFlatIndex"]:
        """Load ignoring the fingerprint · used to salvage trained centroids
        for an assignment-only rebuild after the corpus drifted."""
        try:
            with np.load(path) as z:
                idx = cls(centroids=z["centroids"], offsets=z["offsets"],
                          vectors=z["vectors"], ids=z["ids"],
                          scale=float(z["scale"]))
                idx._fingerprint = bytes(z["fingerprint"].tobytes()).decode()
                return idx
        except (OSError, KeyError, ValueError):
            return None
