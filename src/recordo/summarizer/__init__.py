"""Summarizers plugáveis: Ollama (local LLM) ou heurístico (fallback)."""

from __future__ import annotations

from typing import Any

from .base import Summarizer, SummaryResult

__all__ = ["Summarizer", "SummaryResult", "get_summarizer"]


def get_summarizer(backend: str, config: dict[str, Any] | None = None) -> Summarizer:
    """Factory: retorna Summarizer pra backend nomeado.

    Backends:
      - 'ollama': LLM local via Ollama HTTP (recomendado, local-first)
      - 'heuristic': TextRank-like simples, sem dependência externa
      - 'none': no-op (skip summarization)

    Imports são lazy para evitar carregar httpx quando não usado.
    """
    backend = backend.lower()
    cfg = config or {}
    if backend == "ollama":
        from .ollama import OllamaSummarizer

        return OllamaSummarizer(cfg.get("ollama", {}))
    if backend == "heuristic":
        from .heuristic import HeuristicSummarizer

        return HeuristicSummarizer(cfg.get("heuristic", {}))
    if backend in ("none", "off", "disabled"):
        from .base import NoOpSummarizer

        return NoOpSummarizer()
    raise ValueError(f"backend de summarizer desconhecido: {backend!r}")


def available_backends() -> list[str]:
    """Lista backends disponíveis no ambiente."""
    out = ["heuristic", "none"]  # sempre disponíveis
    try:
        import httpx  # noqa: F401

        out.append("ollama")
    except ImportError:
        pass
    return out
