"""Testes para summarizers cloud (Gemini, OpenAI, Anthropic, OpenAI-compatible, Azure)."""

from __future__ import annotations

import json
from unittest.mock import patch

from recordo.summarizer import get_summarizer
from recordo.summarizer.cloud.anthropic import AnthropicSummarizer
from recordo.summarizer.cloud.gemini import GeminiSummarizer
from recordo.summarizer.cloud.openai import (
    AzureOpenAISummarizer,
    OpenAICompatibleSummarizer,
    OpenAISummarizer,
)


def _mock_resp(body: str | dict):
    """Helper: cria FakeResp pra urlopen mock."""
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


def _capture_post(captured: dict):
    """Helper: factory de fake_urlopen que captura request."""

    def fake(req, timeout=None):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        captured["body"] = json.loads(req.data.decode())
        return _mock_resp(captured.get("response", {"text": "{}"}))

    return fake


class TestGeminiSummarizer:
    def test_no_api_key_returns_error(self):
        s = GeminiSummarizer({"model": "gemini-2.5-flash"})
        r = s.summarize("texto")
        assert r.error is not None
        assert "GEMINI_API_KEY" in r.error or "API key" in r.error

    def test_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("MY_GEMINI_KEY", "test-key-123")
        s = GeminiSummarizer({"model": "gemini-2.5-flash", "api_key_env": "MY_GEMINI_KEY"})
        assert s.api_key == "test-key-123"

    def test_endpoint_includes_api_key(self, monkeypatch):
        s = GeminiSummarizer({"model": "gemini-2.5-flash", "api_key": "secret"})
        assert "key=secret" in s._endpoint()
        assert "gemini-2.5-flash:generateContent" in s._endpoint()

    def test_summarize_with_mocked_http(self):
        captured = {
            "response": {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "resumo": "Mock Gemini",
                                            "topicos": ["t1"],
                                            "decisoes": [],
                                            "action_items": [],
                                        }
                                    )
                                }
                            ]
                        }
                    }
                ]
            },
        }
        s = GeminiSummarizer({"model": "gemini-2.5-flash", "api_key": "secret"})

        with patch("recordo.summarizer.cloud.base.urlopen", side_effect=_capture_post(captured)):
            r = s.summarize("texto qualquer", subject="X")

        assert r.error is None
        assert r.resumo == "Mock Gemini"
        assert r.backend == "gemini-gemini-2.5-flash"
        # Validar payload Gemini
        body = captured["body"]
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        assert body["contents"][0]["parts"][0]["text"]


class TestOpenAISummarizer:
    def test_endpoint_default(self):
        s = OpenAISummarizer({"api_key": "k"})
        assert s._endpoint() == "https://api.openai.com/v1/chat/completions"

    def test_headers_bearer(self):
        s = OpenAISummarizer({"api_key": "secret"})
        h = s._headers()
        assert h["Authorization"] == "Bearer secret"
        assert h["Content-Type"] == "application/json"

    def test_payload_has_response_format_json(self):
        s = OpenAISummarizer({"api_key": "k"})
        p = s._payload("prompt")
        assert p["response_format"] == {"type": "json_object"}
        assert p["model"] == "gpt-4o-mini"

    def test_summarize_with_mocked_http(self):
        captured = {
            "response": {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"resumo": "OpenAI mock", "topicos": [], "decisoes": [], "action_items": []}
                            )
                        }
                    }
                ]
            },
        }
        s = OpenAISummarizer({"api_key": "k", "model": "gpt-test"})

        with patch("recordo.summarizer.cloud.base.urlopen", side_effect=_capture_post(captured)):
            r = s.summarize("texto")

        assert r.error is None
        assert r.resumo == "OpenAI mock"


class TestOpenAICompatibleSummarizer:
    def test_groq_inferred(self):
        s = OpenAICompatibleSummarizer(
            {"api_key": "k", "base_url": "https://api.groq.com/openai/v1", "model": "llama-3.3"}
        )
        assert s.name == "groq-llama-3.3"

    def test_lm_studio_inferred(self):
        s = OpenAICompatibleSummarizer(
            {"api_key": "k", "base_url": "http://localhost:1234/v1", "model": "qwen"}
        )
        assert s.name == "local-qwen"

    def test_payload_skips_response_format_when_unsupported(self):
        s = OpenAICompatibleSummarizer(
            {"api_key": "k", "base_url": "https://api.x.com/v1", "supports_json_object": False}
        )
        p = s._payload("prompt")
        assert "response_format" not in p


class TestAnthropicSummarizer:
    def test_endpoint(self):
        s = AnthropicSummarizer({"api_key": "k"})
        assert s._endpoint() == "https://api.anthropic.com/v1/messages"

    def test_headers_have_api_key_and_version(self):
        s = AnthropicSummarizer({"api_key": "secret"})
        h = s._headers()
        assert h["x-api-key"] == "secret"
        assert h["anthropic-version"] == "2023-06-01"

    def test_summarize_with_mocked_http(self):
        captured = {
            "response": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "resumo": "Claude mock",
                                "topicos": ["x"],
                                "decisoes": [],
                                "action_items": [],
                            }
                        ),
                    }
                ]
            },
        }
        s = AnthropicSummarizer({"api_key": "k"})

        with patch("recordo.summarizer.cloud.base.urlopen", side_effect=_capture_post(captured)):
            r = s.summarize("texto")

        assert r.error is None
        assert r.resumo == "Claude mock"
        assert r.topicos == ["x"]


class TestAzureOpenAISummarizer:
    def test_endpoint_azure_format(self):
        s = AzureOpenAISummarizer(
            {
                "api_key": "k",
                "endpoint": "https://my.openai.azure.com",
                "deployment": "gpt-prod",
                "api_version": "2024-08-01-preview",
            }
        )
        url = s._endpoint()
        assert "openai/deployments/gpt-prod/chat/completions" in url
        assert "api-version=2024-08-01-preview" in url

    def test_headers_use_api_key_not_bearer(self):
        s = AzureOpenAISummarizer(
            {"api_key": "secret", "endpoint": "https://x.openai.azure.com", "deployment": "d"}
        )
        h = s._headers()
        assert h["api-key"] == "secret"
        assert "Authorization" not in h


class TestFactoryFromConfig:
    def test_get_each_cloud_backend(self):
        for be in ["gemini", "openai", "openai_compat", "anthropic", "azure_openai"]:
            s = get_summarizer(be, {be: {"api_key": "test"}})
            assert s is not None
            # Sem fazer call, só checa que instanciou e tem nome válido
            assert s.name


class TestRetryLogic:
    def test_retries_on_429(self):
        from urllib.error import HTTPError

        s = OpenAISummarizer({"api_key": "k", "max_retries": 2, "retry_backoff_seconds": 0.01})

        call_count = {"n": 0}

        def fake(req, timeout=None):
            call_count["n"] += 1
            if call_count["n"] < 3:
                # Simula 429 nas 2 primeiras
                raise HTTPError(req.full_url, 429, "Too Many Requests", {}, None)
            # 3a vez retorna sucesso
            return _mock_resp(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "resumo": "OK após retry",
                                        "topicos": [],
                                        "decisoes": [],
                                        "action_items": [],
                                    }
                                )
                            }
                        }
                    ]
                }
            )

        with patch("recordo.summarizer.cloud.base.urlopen", side_effect=fake):
            r = s.summarize("texto")

        assert call_count["n"] == 3  # 2 falhas + 1 sucesso
        assert r.error is None
        assert r.resumo == "OK após retry"

    def test_no_retry_on_400(self):
        from urllib.error import HTTPError

        s = OpenAISummarizer({"api_key": "k", "max_retries": 3, "retry_backoff_seconds": 0.01})
        call_count = {"n": 0}

        def fake(req, timeout=None):
            call_count["n"] += 1
            raise HTTPError(req.full_url, 400, "Bad Request", {}, None)

        with patch("recordo.summarizer.cloud.base.urlopen", side_effect=fake):
            r = s.summarize("texto")

        assert call_count["n"] == 1  # Sem retry em 400
        assert r.error is not None
