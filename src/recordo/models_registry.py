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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .hardware import HardwareReport


@dataclass(frozen=True)
class ModelInfo:
    """Canonical info de um modelo disponível para download."""

    short_name: str  # ex: "large-v3-turbo"
    full_id: str  # ex: "Systran/faster-whisper-large-v3-turbo" ou "gemma2:2b"
    size_bytes: int  # tamanho aproximado para mostrar na UI
    languages: str  # descrição PT-BR de idiomas suportados
    description: str  # tagline UX
    recommended: bool = False  # mark visualmente como "recomendado"
    ram_required_mb: int = 0  # RAM mínima para rodar (hardware preflight)


# Whisper (faster-whisper) — endpoints HuggingFace via Systran
# Sizes: tiny=75MB, base=145MB, small=480MB, medium=1.5GB, large-v3=3GB, turbo=1.5GB
WHISPER_MODELS: dict[str, ModelInfo] = {
    "tiny": ModelInfo(
        short_name="tiny",
        full_id="Systran/faster-whisper-tiny",
        size_bytes=75 * 1024 * 1024,
        languages="99 idiomas (qualidade básica)",
        description="Mais leve, ideal para dispositivos com pouca RAM",
        ram_required_mb=1500,
    ),
    "base": ModelInfo(
        short_name="base",
        full_id="Systran/faster-whisper-base",
        size_bytes=145 * 1024 * 1024,
        languages="99 idiomas",
        description="Equilíbrio velocidade/qualidade para áudios simples",
        ram_required_mb=2200,
    ),
    "small": ModelInfo(
        short_name="small",
        full_id="Systran/faster-whisper-small",
        size_bytes=480 * 1024 * 1024,
        languages="99 idiomas",
        description="Boa qualidade para reuniões em CPU",
        ram_required_mb=3500,
    ),
    "medium": ModelInfo(
        short_name="medium",
        full_id="Systran/faster-whisper-medium",
        size_bytes=1500 * 1024 * 1024,
        languages="99 idiomas",
        description="Qualidade alta, exige RAM/CPU dedicada",
        ram_required_mb=5500,
    ),
    "large-v3": ModelInfo(
        short_name="large-v3",
        full_id="Systran/faster-whisper-large-v3",
        size_bytes=3000 * 1024 * 1024,
        languages="99 idiomas",
        description="Máxima qualidade, mais lento",
        ram_required_mb=8000,
    ),
    "large-v3-turbo": ModelInfo(
        short_name="large-v3-turbo",
        # v0.2.4 fix: Systran/faster-whisper-large-v3-turbo NÃO existe no HF.
        # mobiuslabsgmbh/faster-whisper-large-v3-turbo é o canonical, ~1.6GB.
        full_id="mobiuslabsgmbh/faster-whisper-large-v3-turbo",
        size_bytes=1620 * 1024 * 1024,
        languages="99 idiomas",
        description="Recomendado: 3x mais rápido que large-v3 com qualidade próxima",
        recommended=True,
        ram_required_mb=4500,
    ),
}


# Parakeet (NVIDIA NeMo) — endpoints HuggingFace
# v3: multilingual 25 EU langs (incl. PT). v2: English only. ctc-110m: small/fast English.
PARAKEET_MODELS: dict[str, ModelInfo] = {
    "parakeet-tdt-0.6b-v3-onnx-int8": ModelInfo(
        short_name="Parakeet TDT 0.6B v3 ONNX int8",
        full_id="istupakov/parakeet-tdt-0.6b-v3-onnx",
        size_bytes=700 * 1024 * 1024,
        languages="25 idiomas EU (incl. pt-BR)",
        description="Recomendado: ONNX int8, leve e rápido sem NeMo",
        recommended=True,
        ram_required_mb=2500,
    ),
    "tdt-0.6b-v3": ModelInfo(
        short_name="tdt-0.6b-v3",
        full_id="nvidia/parakeet-tdt-0.6b-v3",
        size_bytes=600 * 1024 * 1024,
        languages="25 idiomas EU (incl. pt-BR, WER 6.34%)",
        description="NeMo nativo, exige nemo_toolkit (~6.5GB RAM)",
        recommended=False,
        ram_required_mb=6500,
    ),
    "tdt-0.6b-v2": ModelInfo(
        short_name="tdt-0.6b-v2",
        full_id="nvidia/parakeet-tdt-0.6b-v2",
        size_bytes=600 * 1024 * 1024,
        languages="Inglês",
        description="Versão English-only, qualidade similar para EN",
        ram_required_mb=6500,
    ),
    "tdt-ctc-110m": ModelInfo(
        short_name="tdt-ctc-110m",
        full_id="nvidia/parakeet-tdt_ctc-110m",
        size_bytes=110 * 1024 * 1024,
        languages="Inglês (rápido)",
        description="Variante rápida CTC, ~5300 RTFx em A100",
        ram_required_mb=1500,
    ),
}


# Ollama models — nomes oficiais via 'ollama pull <name>'
# Atualizado 2026-06: Gemma 4 (Apr/2026) é o atual; Gemma 3 (Mar/2025) ainda válido
# Sizes baseadas em ollama.com/library snapshots (2026-06)
OLLAMA_MODELS: dict[str, ModelInfo] = {
    # Gemma 4 (Google DeepMind, Apr 2026) — atual
    "gemma4:e2b": ModelInfo(
        short_name="gemma4:e2b",
        full_id="gemma4:e2b",
        size_bytes=int(1.5 * 1024**3),
        languages="pt-BR forte, multimodal, multilingual",
        description="Recomendado: Gemma 4 E2B (efficient, ~1.5GB), frontier-level perf",
        recommended=True,
        ram_required_mb=3500,
    ),
    "gemma4:e4b": ModelInfo(
        short_name="gemma4:e4b",
        full_id="gemma4:e4b",
        size_bytes=int(2.6 * 1024**3),
        languages="pt-BR excelente, multimodal",
        description="Gemma 4 E4B, melhor que E2B, ~3GB RAM",
        ram_required_mb=6500,
    ),
    "gemma4:31b": ModelInfo(
        short_name="gemma4:31b",
        full_id="gemma4:31b",
        size_bytes=(19 * 1024**3),
        languages="pt-BR SOTA, multimodal",
        description="Gemma 4 31B, exige 24GB+ RAM/VRAM, qualidade máxima",
        ram_required_mb=24000,
    ),
    # Gemma 3 (legacy mas ainda funcional)
    "gemma3:4b": ModelInfo(
        short_name="gemma3:4b",
        full_id="gemma3:4b",
        size_bytes=int(2.5 * 1024**3),
        languages="pt-BR forte, multimodal",
        description="Gemma 3 4B (mar/2025), equilíbrio razoável",
        ram_required_mb=6500,
    ),
    "gemma3:12b": ModelInfo(
        short_name="gemma3:12b",
        full_id="gemma3:12b",
        size_bytes=int(8.1 * 1024**3),
        languages="pt-BR excelente, multimodal",
        description="Gemma 3 12B, exige 12GB+ RAM",
        ram_required_mb=12000,
    ),
    # Qwen (Alibaba)
    "qwen2.5:3b": ModelInfo(
        short_name="qwen2.5:3b",
        full_id="qwen2.5:3b",
        size_bytes=int(2.0 * 1024**3),
        languages="pt-BR razoável, suporta tools",
        description="Suporta tool/function calling para automação",
        ram_required_mb=4500,
    ),
    "qwen3:4b": ModelInfo(
        short_name="qwen3:4b",
        full_id="qwen3:4b",
        size_bytes=int(2.6 * 1024**3),
        languages="pt-BR forte, suporta tools",
        description="Qwen 3 4B, thinking mode + tool calling",
        ram_required_mb=6500,
    ),
    # Llama 3.2 (Meta)
    "llama3.2:3b": ModelInfo(
        short_name="llama3.2:3b",
        full_id="llama3.2:3b",
        size_bytes=int(2.0 * 1024**3),
        languages="Multilingual",
        description="Meta Llama 3.2 small, equilíbrio",
        ram_required_mb=4500,
    ),
    "llama3.1:8b": ModelInfo(
        short_name="llama3.1:8b",
        full_id="llama3.1:8b",
        size_bytes=int(4.7 * 1024**3),
        languages="Multilingual",
        description="Llama 3.1 8B, qualidade alta",
        ram_required_mb=8000,
    ),
    # Phi 3.5 (Microsoft)
    "phi3.5:3.8b": ModelInfo(
        short_name="phi3.5:3.8b",
        full_id="phi3.5:3.8b",
        size_bytes=int(2.2 * 1024**3),
        languages="Inglês forte, pt-BR ok",
        description="Microsoft Phi 3.5, eficiente",
        ram_required_mb=4500,
    ),
}


def format_size(bytes_size: int) -> str:
    """Formata bytes em string legível (MB ou GB)."""
    if bytes_size < 1024 * 1024 * 1024:
        return f"{bytes_size / (1024 * 1024):.0f} MB"
    return f"{bytes_size / (1024 * 1024 * 1024):.1f} GB"


def viable_models(report: HardwareReport) -> dict[str, list[str]]:
    """Retorna quais modelos cabem no hardware atual.

    Returns:
        {'whisper': ['tiny', 'base', ...], 'parakeet': [...], 'ollama': [...]}
    """

    out: dict[str, list[str]] = {"whisper": [], "parakeet": [], "ollama": []}
    avail = report.memory.available_mb
    for k, info in WHISPER_MODELS.items():
        if info.ram_required_mb <= avail:
            out["whisper"].append(k)
    for k, info in PARAKEET_MODELS.items():
        if info.ram_required_mb <= avail:
            out["parakeet"].append(k)
    for k, info in OLLAMA_MODELS.items():
        if info.ram_required_mb <= avail:
            out["ollama"].append(k)
    return out
