"""Lemory configuration.

Resolution order (later wins):
  1. Built-in defaults
  2. `lemory.toml` in the vault root or CWD
  3. Environment variables (prefix ``LEMORY_``), plus ``GEMINI_API_KEY`` /
     ``GOOGLE_API_KEY`` for the API key
  4. Keyword arguments to :func:`lemory.configure`

The design goal is cognee-style setup: with a ``GEMINI_API_KEY`` in the
environment and a vault path, everything else has working defaults.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _has_module(name: str) -> bool:
    """True if `name` is importable. Safe under the test pattern that sets
    sys.modules[name] = None to simulate an absent optional dependency
    (find_spec raises ValueError there rather than returning None)."""
    from importlib.util import find_spec

    try:
        return find_spec(name) is not None
    except (ImportError, ValueError):
        return False


class LemoryConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LEMORY_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- what to index ---
    vault: Optional[Path] = None
    include_globs: list[str] = Field(default_factory=lambda: ["**/*.md"])
    exclude_dirs: list[str] = Field(
        default_factory=lambda: [".obsidian", ".trash", ".git", ".lemory", "node_modules"]
    )

    # --- where state lives (defaults to <vault>/.lemory) ---
    data_dir: Optional[Path] = None

    # --- provider: "auto" picks gemini/openai from whichever key is set,
    # falling back to fully-local embeddings when no key exists ---
    provider: str = "auto"  # auto | gemini | openai | local
    # Korean-tuned multilingual-e5-small (dragonkue), 384d, via a community ONNX
    # export so fastembed runs it with no compiler and no torch. Measured dense
    # doc@8 0.86 vs the old MiniLM's 0.14 on KorMapleQA Korean retrieval.
    local_embed_model: str = "dragonkue/multilingual-e5-small-ko-v2"
    # which in-process local embedder: "auto" uses fastembed e5-small-ko-v2 (the
    # strongest local embedder measured, doc@8 0.879). "llamacpp" switches to the
    # 1024-d Harrier-OSS-0.6B GGUF (doc@8 0.853, heavier/slower) for those who
    # want it — it is no longer the default.
    local_embed_backend: str = "auto"  # auto | llamacpp | fastembed
    local_embed_gguf_repo: str = "mradermacher/harrier-oss-v1-0.6b-GGUF"
    local_embed_gguf_file: str = "harrier-oss-v1-0.6b.Q8_0.gguf"
    local_embed_gguf_dim: int = 1024

    # console "assistant mode": a grounded, streaming chat over the vault, à la
    # parlor. The brain is on-device Gemma 4 on llama.cpp (Q4_K_M GGUF) — the
    # same engine as the embedder and reranker, no daemon. E4B is Google's
    # recommended size (default); switch to the lighter E2B in the console.
    assistant_gguf_repo: str = "ggml-org/gemma-4-E4B-it-GGUF"
    assistant_gguf_file: str = "gemma-4-E4B-it-Q4_K_M.gguf"
    assistant_k: int = 6                      # notes retrieved as grounding per turn
    # the write half of the memory loop: every console-assistant conversation
    # is upserted into the vault as a dated session note (chats/ folder, the
    # same Markdown layout `lemory import-chats` produces), so what you tell
    # the assistant today is retrievable tomorrow — visible, editable,
    # deletable like any note (that transparency IS the undo story). Off =
    # conversations stay ephemeral.
    assistant_log_sessions: bool = True
    assistant_log_folder: str = "chats"
    assistant_tts_voice: str = "f4"          # Supertonic voice (f1-f5, m1-m5) for spoken answers
    assistant_tts_pitch: float = 3.0         # semitones up: +3 ≈ cute/bright tone (0 = natural)

    # --- Gemini ---
    gemini_api_key: str = ""
    llm_model: str = "gemini-2.5-flash"
    llm_fallback_model: str = "gemini-2.5-flash-lite"
    llm_rpm: int = 8  # free-tier safe
    llm_max_output_tokens: int = 2048
    embed_model: str = "gemini-embedding-001"
    embed_dim: int = 768
    embed_batch: int = 64
    embed_rpm: int = 90

    # --- OpenAI (used when provider is "openai", or "auto" with only an
    # OpenAI key present). Switching embed provider requires `index --full`.
    openai_api_key: str = ""
    openai_llm_model: str = "gpt-4o-mini"
    openai_embed_model: str = "text-embedding-3-small"
    openai_llm_rpm: int = 60
    openai_embed_rpm: int = 300

    # --- chunking ---
    # 882 chars ≈ 512 tokens of Korean (measured 1.70 char/tok), which is exactly
    # the e5-small-ko-v2 embedding window: the largest chunk the default embedder
    # encodes in full (no truncation) while keeping each chunk maximally coherent.
    # A full chunk-size sweep on KorMapleQA (700–2200) showed doc@8 is flat within
    # noise across the range, so we pick the principled point rather than the
    # nominal max.
    chunk_chars: int = 882
    chunk_overlap: int = 180
    min_chunk_chars: int = 120

    # --- vector index scale-out ---
    # below the threshold: exact float32 scan (zero accuracy loss). Above it:
    # int8 IVF index — 4× less RAM, sublinear query time. 0 disables ANN.
    # Threshold 60k (was 20k), measured on the 42k-chunk namuwiki corpus:
    # IVF@nprobe48 silently cost -4.5pt vector doc@8 vs exact (0.900 vs
    # 0.945) and its training varies between builds; exact is ~45ms p50 at
    # 42k — imperceptible for chat, and recall is what benchmarks (and
    # users) feel. Personal vaults rarely exceed 60k chunks; past it, IVF
    # at nprobe=256 (was 48) keeps most of the recall for ~1ms extra
    # (0.930 vs 0.900 measured at 42k).
    ann_threshold: int = 60_000
    ann_nprobe: int = 256

    # --- retrieval ---
    k_vector: int = 48
    k_bm25: int = 48
    rrf_k: int = 60
    w_vector: float = 1.0
    w_bm25: float = 0.8
    # lexical lean for keyword/verbatim queries. Swept on KorQuAD with
    # multihop + robustness guards (benchmarks/sweep_verbatim.py): 0.60/2.4
    # gains +1.2pt recall@1 on quote-the-document questions with zero guard
    # regression; pushing further (boost 3.0) starts costing paraphrase
    # robustness, so this is the knee of the curve.
    keyword_bm25_boost: float = 2.4  # lexical weight multiplier when verbatim/keyword detected
    # BM25 fusion damp when EVERY query content token is corpus-boilerplate
    # (occurrence rate > 1/20 chunks): the lexical ranking is then small-talk
    # noise (chat-log greetings/reactions gang up under RRF), so fusion leans
    # on the semantic leg. Fires only when a vector leg exists — keyless
    # BM25-only installs unaffected. Measured on RoleMemQA episodic-type.
    common_bm25_damp: float = 0.5
    verbatim_gate: float = 0.60  # query-token coverage in top BM25 chunks that flips to lexical lean
    # near-exact quoting tier: at this coverage the query is reciting the note
    # (reference-QA), where paraphrase risk is nil — lean harder on lexical.
    # The plain boost's own sweep showed 3.0 costs paraphrase robustness at
    # gate 0.60; gating the stronger lean at 0.85+ coverage avoids that regime.
    # reciting tier: at this coverage the query IS the note's text — BM25's
    # internal ordering is preserved outright (dense candidates fill in below).
    # Rank-only RRF can't honor a decisive lexical margin; this can. Weaker-
    # embedder regimes (the light local tier on Korean) are where it matters most.
    # Swept 0.60-0.90 on KorQuAD/SQuAD with multihop/robustness/law/maple/
    # kepano guards (local embedder): 0.65 is the knee — KorQuAD recall@1
    # 0.525→0.825, SQuAD 0.690→0.760, paraphrase +1.7pt, every guard flat;
    # 0.60 starts costing multihop (-1.8pt), korean (-2.5pt), keyword (-1.8pt).
    verbatim_pin_gate: float = 0.65
    # how many of BM25's top ranks the pin locks (0 = the whole candidate
    # list). Pinning everything freezes ranks 4-8 at a scale graph expansion
    # can't reach, silencing multi-hop link evidence on pinned queries.
    verbatim_pin_head: int = 3
    typo_correction: bool = True  # local did-you-mean repair of unknown query words
    # --- memory consolidation (second-brain behavior): every save_memory
    # looks up what the vault already knows. Related notes become `related:`
    # wikilinks in the new note's frontmatter; a near-duplicate (high cosine
    # AND high token overlap — two scales because embedder cosines vary,
    # Jaccard doesn't) additionally gets `possible_duplicate_of:`. Lemory
    # links instead of rewriting/deleting old facts (mem0-style LLM update
    # passes are destructive and wrong often enough to need an undo story;
    # a wikilink IS the undo story). Zero LLM, skipped in keyless mode.
    memory_relate: bool = True
    memory_related_sim: float = 0.60
    memory_dedup_sim: float = 0.80
    memory_dedup_overlap: float = 0.35
    # SwarmVault-style approval gate (opt-in): AI writes land in the vault as
    # PENDING notes — visible as files, but excluded from the index until a
    # human approves. Default off: the standing contract (visible feed +
    # one-click undo) is already stronger than silent ingestion, and an
    # approval queue only helps users who want a review ritual.
    memory_approval: bool = False
    recency_boost: float = 1.0    # multiplicative recency strength on temporal queries
    adaptive_list_k: float = 2.0  # ask() retrieval-depth multiplier for list/count questions
    context_style: str = "full"   # "full" chunks or "compact" fact-sheet context for ask()
    # "rank" (fusion order) or "curriculum" — CDS-inspired smooth ordering
    # (arXiv:2605.13511). Measured on KorQuAD e2e A/B: no gain over rank
    # (contain-EM tied, F1 -3pt), so it stays opt-in. See BENCHMARKS.md §13.
    context_order: str = "rank"
    recency_half_life_days: float = 21.0
    graph_expansion: bool = True
    graph_top_docs: int = 6
    graph_hops: int = 1  # link-propagation depth; 2 = HippoRAG-style A→B→C chains
    graph_expand_budget: int = 8  # max neighbor notes that may receive boosts per query

    # stub-note enrichment (real vaults are full of 3-line reference notes that
    # neither BM25 nor embeddings can see): short notes get one extra indexed
    # pseudo-chunk built from flattened frontmatter properties + the sentences
    # around inbound links in OTHER notes ("backlink context"). Deterministic,
    # index-time only, content chunks and their embed cache untouched.
    stub_enrichment: bool = True
    stub_chars: int = 400  # body length below which a note counts as a stub
    graph_alpha: float = 0.55  # neighbor score = alpha * src_score * edge_weight * sim
    graph_sim_floor: float = 0.25  # skip neighbors whose best chunk sim is below this
    mention_links: bool = True
    per_doc_cap: int = 3
    # Cerebras-style post-ranking context expansion: once ranking is final,
    # re-attach the tail/head of each winner's NEIGHBOR chunks so headings,
    # preconditions and caveats that chunking split apart aren't lost. Only
    # changes what the generator READS — retrieval metrics are untouched.
    # Opt-in for ask() so published e2e numbers stay exact; the console
    # assistant always uses it (its answers aren't benchmark rows).
    context_neighbors: bool = False
    context_neighbor_chars: int = 240
    title_boost: float = 0.12
    # cognee-"memify"-style usage prior: notes that keep getting retrieved in
    # real use rank slightly higher. Default OFF and it stays off until someone
    # can measure it on THEIR usage — there is no honest offline benchmark for
    # a signal that only exists after weeks of personal use, and it feeds back
    # into itself. Opt-in: 0.05-0.15 is a sane range.
    usage_prior: float = 0.0

    # --- attachments ---
    index_pdf: bool = False   # index PDF text too (pip install 'lemory[pdf]')
    index_docx: bool = False  # index Word text too (stdlib zip/XML, no deps)

    # --- middleware dashboard ---
    # local-only timeline of what passed through: queries (with top sources),
    # AI memory writes, per-client stats. Lives in the same SQLite file,
    # capped ring buffer, never transmitted. Set false to keep no logs.
    event_log: bool = True

    # --- remote access (the mobile story) ---
    # Serving beyond localhost (e.g. `lemory serve --host 0.0.0.0` so Obsidian
    # Mobile on the same Wi-Fi can search the desktop index) REQUIRES a token:
    # every request must carry `Authorization: Bearer <api_token>`. Localhost
    # clients are exempt so the desktop dashboard/plugin keep working without
    # setup. Extra hostnames for the DNS-rebinding allowlist (e.g. a Tailscale
    # MagicDNS name) go in allowed_hosts.
    api_token: str = ""
    allowed_hosts: list[str] = Field(default_factory=list)

    # --- semantic fallback links (measured: DON'T turn on blindly) ---
    # Hypothesis was: a vault with no [[wikilinks]] could recover multi-hop
    # via cosine-nearest 'sem' edges on linkless notes. The ablation
    # (benchmarks/run_linkless.py) REFUTED it on the multihop corpus: verbatim
    # title mentions alone fully recover (1.000), while sem edges alone score
    # BELOW no-graph (0.474/0.491 vs 0.491/0.544) — similarity neighbors are
    # not relational bridges, and the vector leg already carries similarity,
    # so sem edges only displace direct hits. Default OFF per the same
    # standard as usage_prior: a signal ships on only after it measurably
    # helps. Kept as opt-in for corpora where mentions can't fire AND
    # semantic neighborhoods happen to align with relations.
    semantic_links: bool = False
    semantic_links_k: int = 3
    semantic_links_floor: float = 0.55
    semantic_links_weight: float = 0.6

    # --- optional LLM retrieval stages (qmd-style; each costs LLM calls) ---
    query_expansion: bool = False   # rewrite the query into variants pre-search
    expansion_variants: int = 2
    rerank: bool = False            # LLM-score the top candidates post-fusion
    rerank_top: int = 12
    rerank_blend: float = 0.5       # 0=fusion score only, 1=LLM score only
    # dedicated cross-encoder reranker on the same llama.cpp engine as the
    # embedder: Qwen3-Reranker-0.6B (2025 SOTA small reranker), scored by its
    # official P("yes") method on GPU. A purpose-built reranker judges relevance
    # directly (unlike generic-LLM self-scoring); when on it supersedes `rerank`.
    reranker: bool = False
    reranker_gguf_repo: str = "dengcao/Qwen3-Reranker-0.6B-GGUF"
    reranker_gguf_file: str = "Qwen3-Reranker-0.6B-q8_0.gguf"

    # --- optional LLM graph enrichment (cognify-style) ---
    enrich_entities: bool = False

    def resolved_vault(self) -> Path:
        if self.vault is None:
            raise RuntimeError(
                "No vault configured. Call lemory.configure(vault=...), set LEMORY_VAULT, "
                "or add `vault = \"...\"` to lemory.toml"
            )
        return self.vault.expanduser().resolve()

    def resolved_data_dir(self) -> Path:
        if self.data_dir is not None:
            d = self.data_dir.expanduser().resolve()
        else:
            d = self.resolved_vault() / ".lemory"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def resolved_gemini_key(self) -> str:
        return (
            self.gemini_api_key
            or os.environ.get("GEMINI_API_KEY", "")
            or os.environ.get("GOOGLE_API_KEY", "")
            or _global_env().get("GEMINI_API_KEY", "")
        )

    def resolved_openai_key(self) -> str:
        return (
            self.openai_api_key
            or os.environ.get("OPENAI_API_KEY", "")
            or _global_env().get("OPENAI_API_KEY", "")
        )

    def resolved_provider(self) -> str:
        if self.provider in ("gemini", "openai", "local"):
            return self.provider
        if self.resolved_gemini_key():
            return "gemini"
        if self.resolved_openai_key():
            return "openai"
        if _has_module("llama_cpp") or _has_module("fastembed"):
            return "local"  # keyless but a local embed backend is installed
        raise RuntimeError(
            "No API key found. Set GEMINI_API_KEY (a free-tier key from "
            "https://aistudio.google.com works), OPENAI_API_KEY, or install "
            "local embeddings: pip install 'lemory[local]' "
            "(keyless e5-small-ko-v2; add 'lemory[llama]' for the 1024-d Harrier)"
        )

    def resolved_local_backend(self) -> str:
        """Which in-process local embedder to use: 'fastembed' (e5-small-ko-v2,
        the default) or 'llamacpp' (Harrier). 'auto' picks e5-small-ko-v2 — it
        measured higher hybrid doc@8 than Harrier (0.879 vs 0.853 on KorMapleQA)
        while being lighter, faster, and needing no native compile; set
        'llamacpp' explicitly to use the 1024-d Harrier instead."""
        if self.local_embed_backend in ("llamacpp", "fastembed"):
            return self.local_embed_backend
        return "fastembed"

    def active_embed_model(self) -> str:
        p = self.resolved_provider()
        if p == "openai":
            return self.openai_embed_model
        if p == "local":
            if self.resolved_local_backend() == "llamacpp":
                return f"llamacpp:{self.local_embed_gguf_repo}/{self.local_embed_gguf_file}"
            return self.local_embed_model
        return self.embed_model

    def active_embed_dim(self) -> int:
        p = self.resolved_provider()
        if p == "local":
            if self.resolved_local_backend() == "llamacpp":
                return self.local_embed_gguf_dim
            from .providers.local import LOCAL_EMBED_DIM

            return LOCAL_EMBED_DIM
        return self.embed_dim

    def active_llm_model(self) -> str:
        p = self.resolved_provider()
        if p == "openai":
            return self.openai_llm_model
        if p == "local":
            return (f"{self.llm_model} (answers)" if self.resolved_gemini_key()
                    else "none — local search-only")
        return self.llm_model

    def resolved_api_key(self) -> str:
        provider = self.resolved_provider()
        if provider == "local":
            return ""  # fully-local providers need no key
        key = self.resolved_gemini_key() if provider == "gemini" else self.resolved_openai_key()
        if not key:
            raise RuntimeError(f"provider is '{provider}' but no matching API key is set")
        return key


GLOBAL_ENV_FILE = Path.home() / ".lemory" / "env"


def _global_env() -> dict[str, str]:
    """Machine-global credentials written by `lemory setup` (~/.lemory/env,
    mode 0600) — so GUI apps like Obsidian, which don't inherit a shell
    environment, still find the key."""
    out: dict[str, str] = {}
    try:
        for line in GLOBAL_ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def save_global_env(values: dict[str, str]) -> Path:
    """Merge values into ~/.lemory/env with owner-only permissions."""
    merged = {**_global_env(), **values}
    GLOBAL_ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    GLOBAL_ENV_FILE.write_text("".join(f"{k}={v}\n" for k, v in merged.items()))
    GLOBAL_ENV_FILE.chmod(0o600)
    return GLOBAL_ENV_FILE


def _load_toml_overrides(start: Path) -> dict[str, Any]:
    """Find `lemory.toml` in `start` or its parents (nearest wins)."""
    for candidate_dir in [start, *start.parents]:
        f = candidate_dir / "lemory.toml"
        if f.is_file():
            with open(f, "rb") as fh:
                data = tomllib.load(fh)
            return data.get("lemory", data)
    return {}


def _drop_env_shadowed(toml_values: dict[str, Any]) -> dict[str, Any]:
    """Init kwargs outrank env vars in pydantic-settings, so a toml value fed
    as a kwarg would silently beat LEMORY_* env. Enforce the documented
    precedence (env beats toml) by dropping toml keys that env sets."""
    return {
        k: v for k, v in toml_values.items()
        if os.environ.get(f"LEMORY_{k.upper()}") is None
    }


def load_config(**overrides: Any) -> LemoryConfig:
    toml_overrides = _drop_env_shadowed(_load_toml_overrides(Path.cwd()))
    kwargs = {k: v for k, v in overrides.items() if v is not None}
    merged = {**toml_overrides, **kwargs}
    cfg = LemoryConfig(**merged)
    # if the vault has its own lemory.toml, honor it for anything not already
    # set by CWD toml / env / kwargs
    if cfg.vault:
        vault_toml = _drop_env_shadowed(_load_toml_overrides(cfg.vault.expanduser().resolve()))
        if vault_toml:
            merged = {**vault_toml, **merged}
            cfg = LemoryConfig(**merged)
    return cfg
