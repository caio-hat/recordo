"""Models registry with official endpoints (M2).

Mantém info canonical sobre modelos disponíveis para download via UI.
Endpoints atualizados conforme pesquisa 2026-06:
  - Whisper: Systran/faster-whisper-* no HuggingFace
  - Parakeet: nvidia/parakeet-tdt-* no HuggingFace
  - Ollama: nomes oficiais via 'ollama pull <name>'

Downloads SEMPRE manuais via Models Manager UI — nunca automáticos no setup.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelInfo:
    """Canonical info de um modelo disponível para download."""

    short_name: str  # ex: "large-v3-turbo"
    full_id: str  # ex: "Systran/faster-whisper-large-v3-turbo" ou "gemma2:2b"
    size_bytes: int  # tamanho aproximado para mostrar na UI
    languages: str  # descrição PT-BR de idiomas suportados
    description: str  # tagline UX
    recommended: bool = False  # mark visualmente como "recomendado"


# Whisper (faster-whisper) — endpoints HuggingFace via Systran
# Sizes: tiny=75MB, base=145MB, small=480MB, medium=1.5GB, large-v3=3GB, turbo=1.5GB
WHISPER_MODELS: dict[str, ModelInfo] = {
    "tiny": ModelInfo(
        short_name="tiny",
        full_id="Systran/faster-whisper-tiny",
        size_bytes=75 * 1024 * 1024,
        languages="99 idiomas (qualidade básica)",
        description="Mais leve, ideal para dispositivos com pouca RAM",
    ),
    "base": ModelInfo(
        short_name="base",
        full_id="Systran/faster-whisper-base",
        size_bytes=145 * 1024 * 1024,
        languages="99 idiomas",
        description="Equilíbrio velocidade/qualidade para áudios simples",
    ),
    "small": ModelInfo(
        short_name="small",
        full_id="Systran/faster-whisper-small",
        size_bytes=480 * 1024 * 1024,
        languages="99 idiomas",
        description="Boa qualidade para reuniões em CPU",
    ),
    "medium": ModelInfo(
        short_name="medium",
        full_id="Systran/faster-whisper-medium",
        size_bytes=1500 * 1024 * 1024,
        languages="99 idiomas",
        description="Qualidade alta, exige RAM/CPU dedicada",
    ),
    "large-v3": ModelInfo(
        short_name="large-v3",
        full_id="Systran/faster-whisper-large-v3",
        size_bytes=3000 * 1024 * 1024,
        languages="99 idiomas",
        description="Máxima qualidade, mais lento",
    ),
    "large-v3-turbo": ModelInfo(
        short_name="large-v3-turbo",
        full_id="Systran/faster-whisper-large-v3-turbo",
        size_bytes=1500 * 1024 * 1024,
        languages="99 idiomas",
        description="Recomendado: 3x mais rápido que large-v3 com qualidade próxima",
        recommended=True,
    ),
}


# Parakeet (NVIDIA NeMo) — endpoints HuggingFace
# v3: multilingual 25 EU langs (incl. PT). v2: English only. ctc-110m: small/fast English.
PARAKEET_MODELS: dict[str, ModelInfo] = {
    "tdt-0.6b-v3": ModelInfo(
        short_name="tdt-0.6b-v3",
        full_id="nvidia/parakeet-tdt-0.6b-v3",
        size_bytes=600 * 1024 * 1024,
        languages="25 idiomas EU (incl. pt-BR, WER 6.34%)",
        description="Recomendado: multilingual SOTA com pt-BR forte",
        recommended=True,
    ),
    "tdt-0.6b-v2": ModelInfo(
        short_name="tdt-0.6b-v2",
        full_id="nvidia/parakeet-tdt-0.6b-v2",
        size_bytes=600 * 1024 * 1024,
        languages="Inglês",
        description="Versão English-only, qualidade similar para EN",
    ),
    "tdt-ctc-110m": ModelInfo(
        short_name="tdt-ctc-110m",
        full_id="nvidia/parakeet-tdt_ctc-110m",
        size_bytes=110 * 1024 * 1024,
        languages="Inglês (rápido)",
        description="Variante rápida CTC, ~5300 RTFx em A100",
    ),
}


# Ollama models — nomes oficiais via 'ollama pull <name>'
# Sizes baseadas em ollama.com/library snapshots (2026-06)
OLLAMA_MODELS: dict[str, ModelInfo] = {
    "gemma2:2b": ModelInfo(
        short_name="gemma2:2b",
        full_id="gemma2:2b",
        size_bytes=int(1.6 * 1024**3),
        languages="pt-BR forte, multilingual",
        description="Recomendado: rápido em CPU, ótimo para resumos curtos",
        recommended=True,
    ),
    "gemma2:9b": ModelInfo(
        short_name="gemma2:9b",
        full_id="gemma2:9b",
        size_bytes=int(5.4 * 1024**3),
        languages="pt-BR excelente",
        description="Mais qualidade que 2b, exige 8GB+ RAM",
    ),
    "qwen2.5:3b": ModelInfo(
        short_name="qwen2.5:3b",
        full_id="qwen2.5:3b",
        size_bytes=int(2.0 * 1024**3),
        languages="pt-BR razoável, suporta tools",
        description="Suporta tool/function calling para automação",
    ),
    "llama3.2:3b": ModelInfo(
        short_name="llama3.2:3b",
        full_id="llama3.2:3b",
        size_bytes=int(2.0 * 1024**3),
        languages="Multilingual",
        description="Meta Llama 3.2 small, equilíbrio",
    ),
    "llama3.1:8b": ModelInfo(
        short_name="llama3.1:8b",
        full_id="llama3.1:8b",
        size_bytes=int(4.7 * 1024**3),
        languages="Multilingual",
        description="Llama 3.1 8B, qualidade alta",
    ),
    "phi3.5:3.8b": ModelInfo(
        short_name="phi3.5:3.8b",
        full_id="phi3.5:3.8b",
        size_bytes=int(2.2 * 1024**3),
        languages="Inglês forte, pt-BR ok",
        description="Microsoft Phi 3.5, eficiente",
    ),
}


def format_size(bytes_size: int) -> str:
    """Formata bytes em string legível (MB ou GB)."""
    if bytes_size < 1024 * 1024 * 1024:
        return f"{bytes_size / (1024 * 1024):.0f} MB"
    return f"{bytes_size / (1024 * 1024 * 1024):.1f} GB"
