"""Tests para CohereTranscriber e WhisperTranscriber improvements."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from recordo.transcribers import available_backends, get_transcriber
from recordo.transcribers.cohere import (
    CohereTranscriber,
)


def _mock_resp(body: str | dict):
    if isinstance(body, dict):
        body = json.dumps(body)
    body_bytes = body.encode()

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return body_bytes

    return FakeResp()


class TestCohereTranscriber:
    def test_no_api_key_raises(self, tmp_path):
        s = CohereTranscriber({})
        audio = tmp_path / "fake.opus"
        audio.write_bytes(b"x")
        with pytest.raises(RuntimeError, match="API key"):
            s.transcribe(audio)

    def test_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("MY_COHERE_KEY", "secret-test-key")
        s = CohereTranscriber({"api_key_env": "MY_COHERE_KEY"})
        assert s.api_key == "secret-test-key"

    def test_api_key_from_config_overrides_env(self, monkeypatch):
        monkeypatch.setenv("COHERE_API_KEY", "from-env")
        s = CohereTranscriber({"api_key": "from-config"})
        assert s.api_key == "from-config"

    def test_name_includes_model(self):
        s = CohereTranscriber({"api_key": "x", "model": "cohere-transcribe-03-2026"})
        assert s.name == "cohere-cohere-transcribe-03-2026"

    def test_endpoint_default(self):
        s = CohereTranscriber({"api_key": "x"})
        assert "api.cohere.com" in s.endpoint
        assert "/v2/audio/transcriptions" in s.endpoint

    def test_endpoint_override(self):
        s = CohereTranscriber({"api_key": "x", "endpoint": "https://custom.host/v2/audio"})
        assert s.endpoint == "https://custom.host/v2/audio"

    def test_transcribe_single_with_mock(self, tmp_path, monkeypatch):
        # Mock conversão pra wav (pula ffmpeg real)
        wav_fake = tmp_path / "fake.wav"
        wav_fake.write_bytes(b"fake-wav-bytes" * 100)  # ~1.4KB

        s = CohereTranscriber({"api_key": "secret"})
        monkeypatch.setattr(s, "_convert_to_wav", lambda audio: wav_fake)
        monkeypatch.setattr(
            "recordo.transcribers.cohere._ffprobe_duration",
            lambda p: 30.0,
        )
        # Mock shutil.which → ffmpeg
        monkeypatch.setattr("recordo.transcribers.cohere.shutil.which", lambda x: "/usr/bin/ffmpeg")

        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["headers"] = dict(req.header_items())
            captured["body_size"] = len(req.data)
            return _mock_resp({"text": "Olá mundo, esta é uma transcrição mock."})

        with patch("recordo.transcribers.cohere.urlopen", side_effect=fake_urlopen):
            result = s.transcribe(tmp_path / "audio.opus", language="pt")

        assert result.error is None if hasattr(result, "error") else True
        assert len(result.segments) == 1
        assert result.segments[0].text == "Olá mundo, esta é uma transcrição mock."
        assert result.segments[0].start == 0.0
        assert result.segments[0].end == 30.0
        assert result.backend == "cohere-cohere-transcribe-03-2026"

        # Validar payload
        assert "Bearer secret" in captured["headers"]["Authorization"]
        assert (
            "multipart/form-data" in captured["headers"]["Content-type"].lower()
            or "multipart/form-data" in captured["headers"]["Content-Type"].lower()
        )

    def test_transcribe_chunking_for_large_audio(self, tmp_path, monkeypatch):
        """Áudio grande (>20MB) deve ser chunkado."""
        wav_fake = tmp_path / "big.wav"
        wav_fake.write_bytes(b"x" * (25 * 1024 * 1024))  # 25MB

        s = CohereTranscriber({"api_key": "x", "chunk_seconds": 600})
        monkeypatch.setattr(s, "_convert_to_wav", lambda audio: wav_fake)
        monkeypatch.setattr("recordo.transcribers.cohere.shutil.which", lambda x: "/usr/bin/ffmpeg")

        # Mock duration pra forçar chunking (1800s = 30min, >chunk_seconds=600)
        monkeypatch.setattr(
            "recordo.transcribers.cohere._ffprobe_duration",
            lambda p: 1800.0,  # 30min total
        )

        chunks_processed = []

        # Mock subprocess ffmpeg para chunking — cria arquivos fake pequenos
        def fake_run(cmd, **kwargs):
            # Detecta se é o split do chunk (-ss + -t presentes)
            if "-ss" in cmd and "-t" in cmd:
                # Cria arquivo de output (último arg) pequeno
                out_path = Path(cmd[-1])
                out_path.write_bytes(b"fake-chunk-bytes" * 100)
                chunks_processed.append(out_path)
            from unittest.mock import MagicMock

            r = MagicMock()
            r.returncode = 0
            r.stdout = ""
            r.stderr = ""
            return r

        monkeypatch.setattr("recordo.transcribers.cohere.subprocess.run", fake_run)

        # Mock urlopen retorna texto por chunk
        chunk_idx = {"i": 0}

        def fake_urlopen(req, timeout=None):
            chunk_idx["i"] += 1
            return _mock_resp({"text": f"Chunk {chunk_idx['i']} text"})

        with patch("recordo.transcribers.cohere.urlopen", side_effect=fake_urlopen):
            result = s.transcribe(tmp_path / "audio.opus", language="pt")

        assert len(result.segments) >= 2, f"expected ≥2 chunks, got {len(result.segments)}"
        # Cada chunk deve ter offset crescente
        assert result.segments[0].start == 0.0
        assert result.segments[1].start == 600.0  # chunk 2 começa em 10min

    def test_http_error_raises_runtimeerror(self, tmp_path, monkeypatch):
        from urllib.error import HTTPError

        wav_fake = tmp_path / "fake.wav"
        wav_fake.write_bytes(b"x" * 100)

        s = CohereTranscriber({"api_key": "x"})
        monkeypatch.setattr(s, "_convert_to_wav", lambda audio: wav_fake)
        monkeypatch.setattr("recordo.transcribers.cohere.shutil.which", lambda x: "/usr/bin/ffmpeg")
        monkeypatch.setattr("recordo.transcribers.cohere._ffprobe_duration", lambda p: 10.0)

        def fake_urlopen(req, timeout=None):
            raise HTTPError(req.full_url, 401, "Unauthorized", {}, None)

        with patch("recordo.transcribers.cohere.urlopen", side_effect=fake_urlopen):
            with pytest.raises(RuntimeError, match="HTTP 401"):
                s.transcribe(tmp_path / "audio.opus")


class TestFactory:
    def test_get_cohere_backend(self):
        s = get_transcriber("cohere", {"cohere": {"api_key": "x"}})
        assert isinstance(s, CohereTranscriber)
        assert "cohere" in s.name

    def test_unknown_backend_raises(self):
        with pytest.raises(ValueError, match="desconhecido"):
            get_transcriber("nonsense", {})

    def test_available_backends_includes_cohere(self):
        # Cohere é HTTP-only (urllib stdlib), sempre disponível tecnicamente
        backends = available_backends()
        assert "cohere" in backends


class TestWhisperImprovements:
    """Smoke tests dos parâmetros novos do Whisper (sem rodar modelo real)."""

    def test_initial_prompt_in_config(self):
        from recordo.transcribers.whisper import WhisperTranscriber

        prompt = "Reunião sobre Datadog e Kubernetes."
        s = WhisperTranscriber({"initial_prompt": prompt})
        assert s.initial_prompt == prompt

    def test_no_initial_prompt_default(self):
        from recordo.transcribers.whisper import WhisperTranscriber

        s = WhisperTranscriber({})
        # Pode ser None ou string vazia, ambos OK
        assert s.initial_prompt in (None, "")

    def test_anti_hallucination_guards_default(self):
        from recordo.transcribers.whisper import WhisperTranscriber

        s = WhisperTranscriber({})
        assert s.condition_on_previous_text is False
        assert s.compression_ratio_threshold == 2.4
        assert s.log_prob_threshold == -1.0
        assert s.no_speech_threshold == 0.6

    def test_guards_overridable(self):
        from recordo.transcribers.whisper import WhisperTranscriber

        s = WhisperTranscriber(
            {
                "condition_on_previous_text": True,
                "no_speech_threshold": 0.3,
            }
        )
        assert s.condition_on_previous_text is True
        assert s.no_speech_threshold == 0.3


class TestCohereLocalBlocked:
    """B7 regression: cohere_local must raise NotImplementedError."""

    def test_transcribe_raises_not_implemented(self, tmp_path):
        from recordo.transcribers.cohere_local import CohereLocalTranscriber

        s = CohereLocalTranscriber({})
        audio = tmp_path / "fake.opus"
        audio.write_bytes(b"x")
        with pytest.raises(NotImplementedError, match="não está totalmente implementado"):
            s.transcribe(audio)

    def test_error_mentions_alternatives(self, tmp_path):
        from recordo.transcribers.cohere_local import CohereLocalTranscriber

        s = CohereLocalTranscriber({})
        audio = tmp_path / "fake.opus"
        audio.write_bytes(b"x")
        try:
            s.transcribe(audio)
        except NotImplementedError as e:
            msg = str(e)
            assert "cohere" in msg.lower()
            assert "whisper" in msg.lower()
            assert "parakeet" in msg.lower()

    def test_via_factory_also_raises(self, tmp_path):
        from recordo.transcribers import get_transcriber

        s = get_transcriber("cohere_local", {})
        audio = tmp_path / "fake.opus"
        audio.write_bytes(b"x")
        with pytest.raises(NotImplementedError):
            s.transcribe(audio)

    def test_incomplete_method_preserved_as_reference(self):
        """The original stub should still be available as _transcribe_incomplete."""
        from recordo.transcribers.cohere_local import CohereLocalTranscriber

        s = CohereLocalTranscriber({})
        # Method exists (preserved for future implementation reference)
        assert hasattr(s, "_transcribe_incomplete")
