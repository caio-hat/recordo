"""Tests for Phase M: models registry + download backends."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from recordo import models as models_mod
from recordo.models import (
    download_ollama,
    is_ollama_installed,
    is_parakeet_installed,
    is_whisper_installed,
)
from recordo.models_registry import (
    OLLAMA_MODELS,
    PARAKEET_MODELS,
    WHISPER_MODELS,
    ModelInfo,
    format_size,
)


class TestModelsRegistry:
    """Validar estrutura do registry."""

    def test_whisper_models_have_required_fields(self):
        for info in WHISPER_MODELS.values():
            assert isinstance(info, ModelInfo)
            assert info.short_name
            assert info.full_id.startswith("Systran/")
            assert info.size_bytes > 0
            assert info.languages
            assert info.description

    def test_parakeet_models_use_nvidia_repo(self):
        for info in PARAKEET_MODELS.values():
            assert info.full_id.startswith("nvidia/parakeet")

    def test_ollama_models_use_canonical_names(self):
        for info in OLLAMA_MODELS.values():
            assert ":" in info.full_id  # ollama format: name:tag

    def test_at_least_one_recommended_per_backend(self):
        wh_recs = [v for v in WHISPER_MODELS.values() if v.recommended]
        pk_recs = [v for v in PARAKEET_MODELS.values() if v.recommended]
        ol_recs = [v for v in OLLAMA_MODELS.values() if v.recommended]
        assert len(wh_recs) >= 1
        assert len(pk_recs) >= 1
        assert len(ol_recs) >= 1


class TestFormatSize:
    def test_mb(self):
        assert format_size(500 * 1024 * 1024) == "500 MB"

    def test_gb_decimal(self):
        assert format_size(int(1.5 * 1024**3)) == "1.5 GB"

    def test_small_bytes(self):
        # < 1MB pinned to 0 MB string acceptably
        result = format_size(500)
        assert "MB" in result


class TestIsInstalled:
    """Detection of installed models."""

    def test_whisper_not_installed_for_unknown(self):
        assert is_whisper_installed("Systran/faster-whisper-NONEXISTENT") is False

    def test_parakeet_not_installed_for_unknown(self):
        assert is_parakeet_installed("nvidia/parakeet-NONEXISTENT") is False

    def test_ollama_no_cli_returns_false(self, monkeypatch):
        """Sem `ollama` CLI no PATH, sempre retorna False."""
        with patch("recordo.models.subprocess.run", side_effect=FileNotFoundError):
            assert is_ollama_installed("anything:test") is False


class TestDownloadOllama:
    """Test ollama pull subprocess parsing."""

    def test_no_ollama_cli_returns_false(self, monkeypatch):
        monkeypatch.setattr(models_mod.shutil, "which", lambda _x: None)
        ok = download_ollama("test:model")
        assert ok is False

    def test_progress_parsing(self, monkeypatch):
        """Mock subprocess.Popen returning lines com porcentagem."""
        monkeypatch.setattr(models_mod.shutil, "which", lambda _x: "/usr/bin/ollama")

        progress_calls = []

        def cb(pct: float, msg: str):
            progress_calls.append((pct, msg))

        # Mock Popen
        fake_proc = MagicMock()
        fake_proc.stdout = iter(
            [
                "pulling manifest\n",
                "pulling 8db5a7faaab1: 25% ...\n",
                "pulling 8db5a7faaab1: 50% ...\n",
                "pulling 8db5a7faaab1: 100% ...\n",
                "success\n",
            ]
        )
        fake_proc.returncode = 0
        fake_proc.wait.return_value = 0

        with patch.object(models_mod.subprocess, "Popen", return_value=fake_proc):
            ok = download_ollama("test:model", on_progress=cb)
        assert ok is True
        # Deve ter chamado progress com 0% (start) + 25 + 50 + 100
        pcts = [p for p, _ in progress_calls]
        assert 0 in pcts or 0.0 in pcts
        assert any(p == 25.0 for p in pcts)
        assert any(p == 50.0 for p in pcts)
        assert any(p == 100.0 for p in pcts)
