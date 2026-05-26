"""Anthropic Claude summarizer via Messages API.

POST https://api.anthropic.com/v1/messages
Headers:
  x-api-key: ...
  anthropic-version: 2023-06-01
  content-type: application/json

Não tem response_format JSON nativo. Confiamos no prompt + extract_json para
parsing robusto do output texto.
"""

from __future__ import annotations

from typing import Any

from .base import BaseHTTPLLMSummarizer

DEFAULT_BASE = "https://api.anthropic.com/v1"
DEFAULT_MODEL = "claude-3-5-haiku-20241022"
API_VERSION = "2023-06-01"


class AnthropicSummarizer(BaseHTTPLLMSummarizer):
    """Resume usando Anthropic Claude Messages API."""

    @property
    def model(self) -> str:
        return self.config.get("model", DEFAULT_MODEL)

    @property
    def name(self) -> str:
        return f"anthropic-{self.model}"

    @property
    def required_credential_label(self) -> str:
        return "API key (ANTHROPIC_API_KEY)"

    def _endpoint(self) -> str:
        base = self.config.get("api_base", DEFAULT_BASE).rstrip("/")
        return f"{base}/messages"

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": self.config.get("api_version", API_VERSION),
        }

    def _payload(self, prompt: str) -> dict[str, Any]:
        return {
            "model": self.model,
            "max_tokens": self.config.get("max_tokens", 4096),
            "temperature": self.temperature,
            "messages": [{"role": "user", "content": prompt}],
        }

    def _extract_text(self, response: dict[str, Any]) -> str:
        # Anthropic retorna {content: [{type: "text", text: "..."}]}
        content = response.get("content", [])
        if not content:
            return ""
        parts = []
        for block in content:
            if block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts).strip()
