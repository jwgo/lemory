from __future__ import annotations

import hashlib
import re

import numpy as np
import pytest

from lemory.config import LemoryConfig
from lemory.engine import Engine

DIM = 64
_WORD = re.compile(r"[a-z0-9]+")


def _token_vec(tok: str) -> np.ndarray:
    seed = int.from_bytes(hashlib.sha256(tok.encode()).digest()[:8], "little")
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(DIM).astype(np.float32)
    return v / np.linalg.norm(v)


class FakeGemini:
    """Deterministic bag-of-words embedder + canned LLM. No network."""

    def __init__(self):
        self.calls = {"embed": 0, "generate": 0}

    def _embed_one(self, text: str) -> np.ndarray:
        toks = _WORD.findall(text.lower())
        if not toks:
            return np.zeros(DIM, dtype=np.float32)
        v = np.sum([_token_vec(t) for t in toks], axis=0)
        n = np.linalg.norm(v)
        return (v / n).astype(np.float32) if n else v.astype(np.float32)

    def embed(self, texts, task_type="RETRIEVAL_DOCUMENT"):
        self.calls["embed"] += len(texts)
        return np.vstack([self._embed_one(t) for t in texts])

    def embed_query(self, text):
        return self.embed([text], "RETRIEVAL_QUERY")[0]

    def generate(self, prompt, system=None, **kw):
        self.calls["generate"] += 1
        return "fake answer [1]"

    def generate_json(self, prompt, system=None, **kw):
        return {"entities": ["alpha", "beta"]}

    def close(self):
        pass


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "vault"
    v.mkdir()
    (v / "Projects").mkdir()
    (v / "Mercury Initiative.md").write_text(
        "---\ntags: [project, priority]\naliases: [Project Mercury]\n---\n"
        "# Overview\nThe Mercury Initiative is our plan to migrate billing to usage-based pricing. "
        "It is led by [[Dana Petrov]] and kicked off in March 2024.\n\n"
        "## Decisions\nWe decided to price at $0.04 per compute-minute after the pilot.\n",
        encoding="utf-8",
    )
    (v / "Dana Petrov.md").write_text(
        "Dana Petrov is our head of platform engineering. "
        "Dana previously worked at Weyland Corp on distributed tracing. "
        "Dana's favorite database is FoundationDB.\n",
        encoding="utf-8",
    )
    (v / "Projects" / "Atlas Notes.md").write_text(
        "# Atlas\nAtlas is the internal analytics dashboard. "
        "The Mercury Initiative dashboard panels live inside Atlas.\n",
        encoding="utf-8",
    )
    (v / "Weekly Log.md").write_text(
        "#log\n- Met about pricing pilot results\n- Reviewed FoundationDB benchmarks\n",
        encoding="utf-8",
    )
    return v


@pytest.fixture
def engine(vault, tmp_path):
    cfg = LemoryConfig(
        vault=vault,
        data_dir=tmp_path / "data",
        embed_dim=DIM,
        gemini_api_key="test",
        chunk_chars=400,
        chunk_overlap=60,
    )
    eng = Engine(cfg, llm=FakeGemini())
    yield eng
    eng.close()
