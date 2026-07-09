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
    local_embed_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

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
    chunk_chars: int = 1400
    chunk_overlap: int = 180
    min_chunk_chars: int = 120

    # --- retrieval ---
    k_vector: int = 48
    k_bm25: int = 48
    rrf_k: int = 60
    w_vector: float = 1.0
    w_bm25: float = 0.8
    keyword_bm25_boost: float = 1.8  # lexical weight multiplier for short keyword queries
    typo_correction: bool = True  # local did-you-mean repair of unknown query words
    recency_boost: float = 1.0    # multiplicative recency strength on temporal queries
    adaptive_list_k: float = 2.0  # ask() retrieval-depth multiplier for list/count questions
    recency_half_life_days: float = 21.0
    graph_expansion: bool = True
    graph_top_docs: int = 6
    graph_alpha: float = 0.55  # neighbor score = alpha * src_score * edge_weight * sim
    graph_sim_floor: float = 0.25  # skip neighbors whose best chunk sim is below this
    mention_links: bool = True
    per_doc_cap: int = 3
    title_boost: float = 0.12

    # --- optional LLM retrieval stages (qmd-style; each costs LLM calls) ---
    query_expansion: bool = False   # rewrite the query into variants pre-search
    expansion_variants: int = 2
    rerank: bool = False            # LLM-score the top candidates post-fusion
    rerank_top: int = 12
    rerank_blend: float = 0.5       # 0=fusion score only, 1=LLM score only

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
        try:
            import fastembed  # noqa: F401  — keyless but local extra installed

            return "local"
        except ImportError:
            pass
        raise RuntimeError(
            "No API key found. Set GEMINI_API_KEY (a free-tier key from "
            "https://aistudio.google.com works), OPENAI_API_KEY, or install "
            "local embeddings: pip install 'lemory[local]'"
        )

    def active_embed_model(self) -> str:
        p = self.resolved_provider()
        if p == "openai":
            return self.openai_embed_model
        if p == "local":
            return self.local_embed_model
        return self.embed_model

    def active_embed_dim(self) -> int:
        if self.resolved_provider() == "local":
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
            return ""  # local embeddings need no key
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
