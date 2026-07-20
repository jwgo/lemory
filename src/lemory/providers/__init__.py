"""LLM/embedding providers. `create_client(cfg)` is the single seam the
engine uses · provider choice lives in config, construction lives here."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import LLMClient, RateLimiter, parse_json_loose

if TYPE_CHECKING:
    from ..config import LemoryConfig

__all__ = ["LLMClient", "RateLimiter", "parse_json_loose", "create_client"]


def create_client(cfg: "LemoryConfig") -> LLMClient:
    provider = cfg.resolved_provider()
    if provider == "local":
        generator = None
        if cfg.resolved_gemini_key():
            from .gemini import GeminiClient

            generator = GeminiClient(
                api_key=cfg.resolved_gemini_key(), llm_model=cfg.llm_model,
                llm_fallback_model=cfg.llm_fallback_model, llm_rpm=cfg.llm_rpm,
                max_output_tokens=cfg.llm_max_output_tokens,
            )
        if cfg.resolved_local_backend() == "llamacpp":
            from .llamacpp import LlamaCppLocalClient

            return LlamaCppLocalClient(
                gguf_repo=cfg.local_embed_gguf_repo,
                gguf_file=cfg.local_embed_gguf_file,
                embed_dim=cfg.local_embed_gguf_dim, generator=generator,
                answer_repo=cfg.assistant_gguf_repo,
                answer_file=cfg.assistant_gguf_file,
                answer_n_ctx=cfg.answer_n_ctx, answer_gpu_layers=cfg.answer_gpu_layers)
        from .local import LocalClient

        return LocalClient(embed_model=cfg.local_embed_model, generator=generator,
                           answer_repo=cfg.assistant_gguf_repo,
                           answer_file=cfg.assistant_gguf_file,
                           answer_n_ctx=cfg.answer_n_ctx,
                           answer_gpu_layers=cfg.answer_gpu_layers)
    if provider == "openai":
        from .openai import OpenAIClient

        return OpenAIClient(
            api_key=cfg.resolved_openai_key(),
            llm_model=cfg.openai_llm_model,
            llm_rpm=cfg.openai_llm_rpm,
            embed_model=cfg.openai_embed_model,
            embed_dim=cfg.embed_dim,
            embed_rpm=cfg.openai_embed_rpm,
            max_output_tokens=cfg.llm_max_output_tokens,
        )
    from .gemini import GeminiClient

    return GeminiClient(
        api_key=cfg.resolved_gemini_key(),
        llm_model=cfg.llm_model,
        llm_fallback_model=cfg.llm_fallback_model,
        llm_rpm=cfg.llm_rpm,
        embed_model=cfg.embed_model,
        embed_dim=cfg.embed_dim,
        embed_rpm=cfg.embed_rpm,
        embed_batch=cfg.embed_batch,
        max_output_tokens=cfg.llm_max_output_tokens,
    )
