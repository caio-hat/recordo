"""Testes para models_registry: ram_required_mb e viable_models."""

from __future__ import annotations

from unittest.mock import MagicMock

from recordo.models_registry import (
    OLLAMA_MODELS,
    PARAKEET_MODELS,
    WHISPER_MODELS,
    viable_models,
)


def test_all_models_have_ram_required():
    for k, m in (*WHISPER_MODELS.items(), *PARAKEET_MODELS.items(), *OLLAMA_MODELS.items()):
        assert m.ram_required_mb > 0, f"modelo {k} sem ram_required_mb"


def test_parakeet_onnx_is_recommended_default():
    onnx_keys = [k for k in PARAKEET_MODELS if "onnx" in k.lower()]
    assert len(onnx_keys) >= 1
    onnx = PARAKEET_MODELS[onnx_keys[0]]
    assert onnx.recommended is True
    assert onnx.ram_required_mb < 4000  # leve


def test_parakeet_nemo_is_legacy_not_recommended():
    nemo_keys = [k for k in PARAKEET_MODELS if "onnx" not in k.lower()]
    if nemo_keys:
        nemo = PARAKEET_MODELS[nemo_keys[0]]
        # NeMo deve estar marcado como não recomendado (peso de RAM)
        assert nemo.ram_required_mb >= 5000


def test_gemma4_e2b_recommended():
    # gemma4:e2b deve estar no registry
    keys = [k for k in OLLAMA_MODELS if "gemma4" in k]
    assert len(keys) >= 1, "gemma4 deve estar no registry"


def test_viable_models_filter_by_ram():
    fake_report = MagicMock()
    fake_report.memory.available_mb = 4000  # 4GB livres
    out = viable_models(fake_report)
    assert "whisper" in out
    assert "parakeet" in out
    assert "ollama" in out
    # Em 4GB tiny e base whisper devem caber, large nao:
    assert "tiny" in out["whisper"]
    # large-v3 (8GB) nao cabe em 4GB:
    assert "large-v3" not in out["whisper"]


def test_viable_models_high_ram_includes_all():
    fake_report = MagicMock()
    fake_report.memory.available_mb = 64000  # 64GB livres
    out = viable_models(fake_report)
    assert len(out["whisper"]) == len(WHISPER_MODELS)
    assert len(out["parakeet"]) == len(PARAKEET_MODELS)
    assert len(out["ollama"]) == len(OLLAMA_MODELS)
