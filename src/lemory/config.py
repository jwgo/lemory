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
    graph_expansion: bool = True
    graph_top_docs: int = 6
    graph_alpha: float = 0.55  # neighbor score = alpha * src_score * edge_weight * sim
    mention_links: bool = True
    per_doc_cap: int = 3
    title_boost: float = 0.12

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

    def resolved_api_key(self) -> str:
        key = self.gemini_api_key or os.environ.get("GEMINI_API_KEY", "") or os.environ.get(
            "GOOGLE_API_KEY", ""
        )
        if not key:
            raise RuntimeError(
                "No Gemini API key found. Set GEMINI_API_KEY (a free-tier key from "
                "https://aistudio.google.com works)."
            )
        return key


def _load_toml_overrides(start: Path) -> dict[str, Any]:
    """Find `lemory.toml` in `start` or its parents (nearest wins)."""
    for candidate_dir in [start, *start.parents]:
        f = candidate_dir / "lemory.toml"
        if f.is_file():
            with open(f, "rb") as fh:
                data = tomllib.load(fh)
            return data.get("lemory", data)
    return {}


def load_config(**overrides: Any) -> LemoryConfig:
    toml_overrides = _load_toml_overrides(Path.cwd())
    # env beats toml: BaseSettings already applies env, so feed toml values only
    # for fields that are not set via env/kwargs.
    merged = {**toml_overrides, **{k: v for k, v in overrides.items() if v is not None}}
    cfg = LemoryConfig(**merged)
    # if vault has its own lemory.toml, honor it for anything still default
    if cfg.vault:
        vault_toml = _load_toml_overrides(cfg.vault.expanduser().resolve())
        if vault_toml:
            merged = {**vault_toml, **merged}
            cfg = LemoryConfig(**merged)
    return cfg
