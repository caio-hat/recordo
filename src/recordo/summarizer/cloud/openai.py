"""OpenAI-style summarizers — cobre OpenAI, OpenAI-compatible APIs e Azure OpenAI.

OpenAI: chat/completions endpoint padrão.
OpenAI-compatible: Groq, Together, Fireworks, OpenRouter, LM Studio, vLLM, etc.
  Mesmo formato JSON do OpenAI, só muda base_url e modelo.
Azure OpenAI: difere no path (deployment-based) e auth header (api-key).
"""

from __future__ import annotations

from typing import Any

from .base import BaseHTTPLLMSummarizer

DEFAULT_OPENAI_BASE = "https://api.openai.com/v1"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


class OpenAISummarizer(BaseHTTPLLMSummarizer):
    """Resume usando OpenAI Chat Completions API."""

    @property
    def model(self) -> str:
        return self.config.get("model", DEFAULT_OPENAI_MODEL)

    @property
    def name(self) -> str:
        return f"openai-{self.model}"

    @property
    def required_credential_label(self) -> str:
        return "API key (OPENAI_API_KEY)"

    @property
    def base_url(self) -> str:
        return self.config.get("base_url", DEFAULT_OPENAI_BASE).rstrip("/")

    def _endpoint(self) -> str:
        return f"{self.base_url}/chat/completions"

    def _headers(self) -> dict[str, str]:
        h = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        if org := self.config.get("organization"):
            h["OpenAI-Organization"] = str(org)
        return h

    def _payload(self, prompt: str) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "response_format": {"type": "json_object"},
        }

    def _extract_text(self, response: dict[str, Any]) -> str:
        choices = response.get("choices", [])
        if not choices:
            return ""
        return choices[0].get("message", {}).get("content", "").strip()


class OpenAICompatibleSummarizer(OpenAISummarizer):
    """OpenAI-compatible APIs: Groq, Together, Fireworks, OpenRouter, LM Studio, vLLM.

    Difere de OpenAI no:
      - base_url custom (sempre necessário)
      - alguns providers não suportam response_format=json_object → fallback string
      - modelo é livre (provider-specific)

    Exemplo Groq:
      [summarizer.openai_compat]
      base_url = "https://api.groq.com/openai/v1"
      api_key_env = "GROQ_API_KEY"
      model = "llama-3.3-70b-versatile"
      supports_json_object = true
    """

    @property
    def name(self) -> str:
        # Inferir provider pelo base_url (puramente para logging)
        host = self.base_url.split("//", 1)[-1].split("/", 1)[0].lower()
        provider = "compat"
        if "groq" in host:
            provider = "groq"
        elif "together" in host:
            provider = "together"
        elif "fireworks" in host:
            provider = "fireworks"
        elif "openrouter" in host:
            provider = "openrouter"
        elif "lmstudio" in host or "localhost" in host or "127.0.0.1" in host:
            provider = "local"
        return f"{provider}-{self.model}"

    def _payload(self, prompt: str) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
        }
        # response_format=json_object só funciona em alguns providers (OpenAI, Groq, OpenRouter)
        if self.config.get("supports_json_object", True):
            body["response_format"] = {"type": "json_object"}
        return body


class AzureOpenAISummarizer(OpenAISummarizer):
    """Azure OpenAI Service — auth via header `api-key` + endpoint deployment-based.

    Config esperada:
      [summarizer.azure_openai]
      endpoint = "https://YOUR.openai.azure.com"
      deployment = "gpt-4o-mini-deploy"
      api_version = "2024-08-01-preview"
      api_key_env = "AZURE_OPENAI_API_KEY"
    """

    @property
    def model(self) -> str:
        # Em Azure usamos deployment ao invés de model
        return self.config.get("deployment", DEFAULT_OPENAI_MODEL)

    @property
    def name(self) -> str:
        return f"azure-{self.model}"

    @property
    def required_credential_label(self) -> str:
        return "API key (AZURE_OPENAI_API_KEY) + endpoint + deployment"

    def _endpoint(self) -> str:
        endpoint = self.config.get("endpoint", "").rstrip("/")
        if not endpoint:
            return ""
        deployment = self.model
        api_version = self.config.get("api_version", "2024-08-01-preview")
        return f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "api-key": self.api_key,  # Azure usa api-key, não Bearer
        }
