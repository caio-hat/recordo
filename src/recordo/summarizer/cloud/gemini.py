"""Gemini summarizer via Google Generative Language API.

REST endpoint:
  POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key=KEY

Suporta `responseMimeType: application/json` para forçar JSON estruturado.
"""

from __future__ import annotations

from typing import Any

from .base import BaseHTTPLLMSummarizer

DEFAULT_MODEL = "gemini-2.5-flash"
API_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiSummarizer(BaseHTTPLLMSummarizer):
    """Resume usando Google Gemini API."""

    @property
    def model(self) -> str:
        return self.config.get("model", DEFAULT_MODEL)

    @property
    def name(self) -> str:
        return f"gemini-{self.model}"

    @property
    def required_credential_label(self) -> str:
        return "API key (GEMINI_API_KEY)"

    def _endpoint(self) -> str:
        # API key é query param em Gemini (não header)
        base = self.config.get("api_base", API_BASE).rstrip("/")
        return f"{base}/models/{self.model}:generateContent?key={self.api_key}"

    def _headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json"}

    def _payload(self, prompt: str) -> dict[str, Any]:
        return {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": self.temperature,
                "responseMimeType": "application/json",
            },
            "safetySettings": [
                {"category": cat, "threshold": "BLOCK_ONLY_HIGH"}
                for cat in (
                    "HARM_CATEGORY_HATE_SPEECH",
                    "HARM_CATEGORY_HARASSMENT",
                    "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                    "HARM_CATEGORY_DANGEROUS_CONTENT",
                )
            ],
        }

    def _extract_text(self, response: dict[str, Any]) -> str:
        candidates = response.get("candidates", [])
        if not candidates:
            return ""
        parts = candidates[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts).strip()
