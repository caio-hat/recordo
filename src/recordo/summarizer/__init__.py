"""Summarizers plugáveis: Ollama (local) + cloud (Gemini/OpenAI/Anthropic/Groq) + heurístico."""

from __future__ import annotations

from typing import Any

from .base import Summarizer, SummaryResult

__all__ = ["Summarizer", "SummaryResult", "available_backends", "get_summarizer"]


# Lista de backends suportados — ordem importa no available_backends
_KNOWN_BACKENDS = (
    "ollama",
    "gemini",
    "openai",
    "openai_compat",  # Para Groq, Together, Fireworks, OpenRouter, LM Studio etc
    "anthropic",
    "azure_openai",
    "heuristic",
    "none",
)


def get_summarizer(backend: str, config: dict[str, Any] | None = None) -> Summarizer:
    """Factory: retorna Summarizer pra backend nomeado.

    Backends disponíveis:
      Locais:
        - 'ollama': LLM local via Ollama HTTP (recomendado para privacy)
        - 'heuristic': TextRank-like sem deps externas
        - 'none': no-op
      Cloud:
        - 'gemini': Google Gemini (requer api_key)
        - 'openai': OpenAI GPT (requer api_key)
        - 'openai_compat': API OpenAI-compatível (Groq/Together/Fireworks/etc) com base_url custom
        - 'anthropic': Claude (requer api_key)
        - 'azure_openai': Azure OpenAI deployments

    Imports são lazy pra evitar carregar deps de providers não usados.
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
    if backend == "gemini":
        from .cloud.gemini import GeminiSummarizer

        return GeminiSummarizer(cfg.get("gemini", {}))
    if backend == "openai":
        from .cloud.openai import OpenAISummarizer

        return OpenAISummarizer(cfg.get("openai", {}))
    if backend == "openai_compat":
        from .cloud.openai import OpenAICompatibleSummarizer

        return OpenAICompatibleSummarizer(cfg.get("openai_compat", {}))
    if backend == "anthropic":
        from .cloud.anthropic import AnthropicSummarizer

        return AnthropicSummarizer(cfg.get("anthropic", {}))
    if backend == "azure_openai":
        from .cloud.openai import AzureOpenAISummarizer

        return AzureOpenAISummarizer(cfg.get("azure_openai", {}))

    raise ValueError(f"backend de summarizer desconhecido: {backend!r}. Opções: {', '.join(_KNOWN_BACKENDS)}")


def available_backends() -> list[str]:
    """Lista backends técnicamente disponíveis no ambiente.

    Heurístico e none sempre estão. Ollama: probe HTTP best-effort.
    Cloud providers: existem se o módulo carrega (no caso, sempre — usam urllib).
    """
    out = ["heuristic", "none"]
    # Cloud sempre disponíveis (urllib stdlib)
    out.extend(["gemini", "openai", "openai_compat", "anthropic", "azure_openai"])
    # Ollama: probe rápido pra detectar se está rodando
    try:
        from urllib.request import Request, urlopen

        req = Request("http://localhost:11434/api/tags")
        with urlopen(req, timeout=1):
            out.insert(0, "ollama")
    except Exception:
        pass
    return out
