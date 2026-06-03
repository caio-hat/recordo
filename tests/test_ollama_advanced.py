"""Testes para configuração avançada Ollama (v0.2.4)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from recordo.config import DEFAULTS
from recordo.summarizer.ollama import OllamaSummarizer


def test_config_has_advanced_keys():
    ol = DEFAULTS["summarizer"]["ollama"]
    for k in ("think_enabled", "temperature", "top_p", "top_k", "num_ctx", "repeat_penalty", "seed"):
        assert k in ol, f"config default missing: {k}"


def test_config_defaults_sane():
    ol = DEFAULTS["summarizer"]["ollama"]
    assert ol["think_enabled"] is True
    assert 0.0 <= ol["temperature"] <= 2.0
    assert 0.0 <= ol["top_p"] <= 1.0
    assert 1 <= ol["top_k"] <= 200
    assert 1024 <= ol["num_ctx"] <= 131072
    assert 1.0 <= ol["repeat_penalty"] <= 2.0
    assert ol["seed"] == 0


def test_payload_includes_options_and_think_for_gemma4():
    cfg = {
        "model": "gemma4:e2b",
        "host": "http://localhost:11434",
        "timeout_seconds": 10,
        "temperature": 0.4,
        "top_p": 0.9,
        "top_k": 40,
        "num_ctx": 8192,
        "repeat_penalty": 1.1,
        "seed": 42,
        "think_enabled": True,
    }
    summ = OllamaSummarizer(config=cfg)

    fake_resp = json.dumps({"response": '{"resumo":"test","topicos":[],"decisoes":[],"action_items":[]}'})
    with patch("recordo.summarizer.ollama.urlopen") as mock_urlopen:
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_ctx.read.return_value = fake_resp.encode()
        mock_urlopen.return_value = mock_ctx

        summ._call_ollama("test prompt")

        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        payload = json.loads(req.data.decode())

        assert payload["think"] is True
        assert payload["options"]["top_p"] == 0.9
        assert payload["options"]["top_k"] == 40
        assert payload["options"]["repeat_penalty"] == 1.1
        assert payload["options"]["seed"] == 42
        assert payload["options"]["num_ctx"] == 8192


def test_payload_no_think_for_unsupported_model():
    cfg = {"model": "llama3.1:8b", "host": "http://localhost:11434", "timeout_seconds": 10}
    summ = OllamaSummarizer(config=cfg)

    fake_resp = json.dumps({"response": '{"resumo":"x","topicos":[],"decisoes":[],"action_items":[]}'})
    with patch("recordo.summarizer.ollama.urlopen") as mock_urlopen:
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_ctx.read.return_value = fake_resp.encode()
        mock_urlopen.return_value = mock_ctx

        summ._call_ollama("test prompt")

        req = mock_urlopen.call_args[0][0]
        payload = json.loads(req.data.decode())
        assert "think" not in payload


def test_seed_zero_not_in_options():
    cfg = {"model": "gemma4:e2b", "host": "http://localhost:11434", "timeout_seconds": 10, "seed": 0}
    summ = OllamaSummarizer(config=cfg)

    fake_resp = json.dumps({"response": '{"resumo":"x","topicos":[],"decisoes":[],"action_items":[]}'})
    with patch("recordo.summarizer.ollama.urlopen") as mock_urlopen:
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_ctx.read.return_value = fake_resp.encode()
        mock_urlopen.return_value = mock_ctx

        summ._call_ollama("test prompt")

        req = mock_urlopen.call_args[0][0]
        payload = json.loads(req.data.decode())
        assert "seed" not in payload["options"]
