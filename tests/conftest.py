from __future__ import annotations

import hashlib
import re

import numpy as np
import pytest

from lemory.config import LemoryConfig
from lemory.engine import Engine

DIM = 64
_WORD = re.compile(r"[a-z0-9]+|[가-힣]+")


@pytest.fixture(autouse=True)
def _isolate_global_env(tmp_path, monkeypatch):
    """Tests must never see the developer's real ~/.lemory/env credentials."""
    import lemory.config as config_mod

    monkeypatch.setattr(config_mod, "GLOBAL_ENV_FILE", tmp_path / "no-global-env")


@pytest.fixture(autouse=True)
def _no_local_brain(monkeypatch):
    """Tests never load the multi-GB Gemma GGUF. Stub the on-device brain as
    unavailable so the keyless local generate() takes its documented raise
    path; a test that wants it overrides this explicitly."""
    import lemory.providers.gemma as gm
    monkeypatch.setattr(gm, "available", lambda: (False, "brain stubbed in tests"))


@pytest.fixture(autouse=True)
def _default_local_fastembed(monkeypatch):
    """Keep the 'auto' local embed backend = fastembed in tests even when
    llama-cpp-python happens to be installed in the dev env. Tests that want
    the llama.cpp/Harrier path set local_embed_backend='llamacpp' explicitly,
    which this still honors."""
    from lemory.config import LemoryConfig

    def resolve(self):
        return self.local_embed_backend if self.local_embed_backend in (
            "llamacpp", "fastembed") else "fastembed"

    monkeypatch.setattr(LemoryConfig, "resolved_local_backend", resolve)


def _subtokens(text: str) -> list[str]:
    """Words plus Hangul bigrams, so the fake embedder gives Korean text
    meaningful subword similarity (mirrors real multilingual embedders)."""
    toks = []
    for t in _WORD.findall(text.lower()):
        toks.append(t)
        if "가" <= t[0] <= "힣" and len(t) > 1:
            toks.extend(t)  # unigrams, mirroring the FTS CJK analyzer
            toks.extend(t[i : i + 2] for i in range(len(t) - 1))
    return toks


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
        toks = _subtokens(text)
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
        self.calls["generate"] += 1
        if '"queries"' in prompt:
            return {"queries": ["pricing decision details", "usage based billing plan"]}
        if '"scores"' in prompt:
            # rank passages by naive token overlap with the query line
            import re as _re
            qline = next((l for l in prompt.splitlines() if l.startswith("QUERY:")), "")
            q_toks = set(_re.findall(r"[a-z0-9]+", qline.lower()))
            scores = {}
            for m in _re.finditer(r"\[(\d+)\] ([^\n]+)", prompt):
                toks = set(_re.findall(r"[a-z0-9]+", m.group(2).lower()))
                scores[m.group(1)] = min(10, len(q_toks & toks))
            return {"scores": scores}
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


@pytest.fixture
def client(engine):
    """Server test client whose Host header is a real localhost value, so the
    DNS-rebinding Host guard (http.py) lets it through."""
    from fastapi.testclient import TestClient

    from lemory.interfaces.http import build_app

    with TestClient(build_app(engine, watch=False), base_url="http://127.0.0.1") as c:
        yield c


@pytest.fixture
def fakes():
    """(DIM, FakeGemini) for tests that build their own Engine. A fixture,
    not `from tests.conftest import ...`: bare `pytest` (CI) has no repo
    root on sys.path, so the module import only worked with `python -m`."""
    return DIM, FakeGemini
