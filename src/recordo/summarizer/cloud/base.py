"""Base abstrato para summarizers cloud via HTTP.

Centraliza:
- Build do prompt pt-BR estruturado pedindo JSON
- Truncamento de transcript longo
- HTTP POST com retry/timeout
- Parsing de JSON robusto (fences, cruft)
- Extração comum de erro

Subclasses só implementam:
- _endpoint() -> URL completa
- _headers() -> dict de headers (api key, content-type)
- _payload(prompt) -> dict do body do POST
- _extract_text(response_dict) -> str do conteúdo gerado
- name (property)
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from abc import abstractmethod
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..base import Summarizer, SummaryResult

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 90  # segundos
MAX_TRANSCRIPT_CHARS = 30000  # truncamento default

# Prompt unificado pra todos os providers — esperamos JSON estruturado
PROMPT_TEMPLATE = """Você é um assistente que resume reuniões e conversas em português do Brasil.

Analise a transcrição abaixo e gere um resumo estruturado em JSON com as chaves:

- "resumo": string com 3 a 5 frases concisas descrevendo do que se tratou
- "topicos": array de strings com tópicos principais discutidos (máx 6)
- "decisoes": array de strings com decisões tomadas (vazio se nenhuma)
- "action_items": array de strings com ações a serem feitas, no formato "QUEM: O QUÊ"
  (vazio se nenhuma)

Responda APENAS o JSON, sem comentários extras nem texto fora dele.

{subject_line}TRANSCRIÇÃO:
\"\"\"
{transcript}
\"\"\"
"""


class BaseHTTPLLMSummarizer(Summarizer):
    """Base abstrato para summarizers que usam HTTP REST APIs."""

    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config or {}
        self.config = cfg
        self.api_key = self._resolve_api_key(cfg)
        self.timeout: int = cfg.get("timeout_seconds", DEFAULT_TIMEOUT)
        self.max_chars: int = cfg.get("max_transcript_chars", MAX_TRANSCRIPT_CHARS)
        self.temperature: float = cfg.get("temperature", 0.3)
        self.max_retries: int = cfg.get("max_retries", 2)
        self.retry_backoff_seconds: float = cfg.get("retry_backoff_seconds", 1.5)

    @staticmethod
    def _resolve_api_key(cfg: dict[str, Any]) -> str:
        """Lê api_key de config OU env var (api_key_env)."""
        if direct := cfg.get("api_key"):
            return str(direct).strip()
        if env_var := cfg.get("api_key_env"):
            value = os.environ.get(env_var, "").strip()
            if value:
                return value
        return ""

    # ── Hooks que subclasses implementam ────────────────────────────────────
    @property
    @abstractmethod
    def model(self) -> str:
        """Nome do modelo (ex: 'gemini-2.5-flash', 'gpt-4o-mini')."""

    @abstractmethod
    def _endpoint(self) -> str:
        """URL completa do endpoint chat/generate."""

    @abstractmethod
    def _headers(self) -> dict[str, str]:
        """Headers HTTP (sempre Content-Type: application/json + auth)."""

    @abstractmethod
    def _payload(self, prompt: str) -> dict[str, Any]:
        """Body JSON do POST. Inclui modelo, mensagens, params."""

    @abstractmethod
    def _extract_text(self, response: dict[str, Any]) -> str:
        """Extrai o texto gerado da resposta JSON do provider."""

    @property
    def required_credential_label(self) -> str:
        """Qual credential é necessária pra mostrar erro útil."""
        return "API key"

    # ── Implementação comum ─────────────────────────────────────────────────
    def summarize(self, transcript: str, *, language: str = "pt", subject: str = "") -> SummaryResult:
        if not transcript.strip():
            return SummaryResult(backend=self.name, error="transcript vazio")

        if not self.api_key:
            return SummaryResult(
                backend=self.name,
                error=f"{self.required_credential_label} não configurada para {self.name}",
            )

        truncated = transcript
        if len(truncated) > self.max_chars:
            log.info(
                "[%s] transcript longo (%d chars), truncando para %d",
                self.name,
                len(truncated),
                self.max_chars,
            )
            truncated = truncated[: self.max_chars] + "\n[…transcrição truncada…]"

        subject_line = f"ASSUNTO: {subject}\n\n" if subject else ""
        prompt = PROMPT_TEMPLATE.format(transcript=truncated, subject_line=subject_line)

        try:
            response_text = self._call_with_retry(prompt)
        except HTTPError as e:
            err = self._format_http_error(e)
            log.error("[%s] HTTP error: %s", self.name, err)
            return SummaryResult(backend=self.name, error=err)
        except (URLError, OSError, TimeoutError) as e:
            log.error("[%s] erro de rede: %s", self.name, e)
            return SummaryResult(backend=self.name, error=f"erro de rede: {e}")

        try:
            data = self._extract_json(response_text)
        except (ValueError, json.JSONDecodeError) as e:
            log.error(
                "[%s] resposta JSON inválida: %s\nResposta: %s",
                self.name,
                e,
                response_text[:500],
            )
            return SummaryResult(
                backend=self.name,
                resumo=response_text.strip()[:1500],
                error="JSON inválido (resposta bruta no resumo)",
            )

        return SummaryResult(
            resumo=str(data.get("resumo", "")).strip(),
            topicos=[str(x).strip() for x in data.get("topicos", []) if str(x).strip()],
            decisoes=[str(x).strip() for x in data.get("decisoes", []) if str(x).strip()],
            action_items=[str(x).strip() for x in data.get("action_items", []) if str(x).strip()],
            backend=self.name,
        )

    def _call_with_retry(self, prompt: str) -> str:
        """POST com retry exponencial em 429/503."""
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return self._call_http(prompt)
            except HTTPError as e:
                last_error = e
                # 429 = rate limit; 5xx = transient. Vale retry.
                if e.code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                    wait = self.retry_backoff_seconds * (2**attempt)
                    log.warning(
                        "[%s] HTTP %s — retry em %.1fs (tentativa %d/%d)",
                        self.name,
                        e.code,
                        wait,
                        attempt + 1,
                        self.max_retries + 1,
                    )
                    time.sleep(wait)
                    continue
                raise
            except (URLError, OSError, TimeoutError) as e:
                last_error = e
                if attempt < self.max_retries:
                    wait = self.retry_backoff_seconds * (2**attempt)
                    log.warning(
                        "[%s] erro de rede (%s) — retry em %.1fs",
                        self.name,
                        type(e).__name__,
                        wait,
                    )
                    time.sleep(wait)
                    continue
                raise
        # Inalcançável (loop sempre retorna ou raise), mas mypy exige
        if last_error:
            raise last_error
        return ""

    def _call_http(self, prompt: str) -> str:
        """POST único — sem retry."""
        body = json.dumps(self._payload(prompt)).encode("utf-8")
        req = Request(self._endpoint(), data=body, headers=self._headers(), method="POST")
        with urlopen(req, timeout=self.timeout) as resp:
            response_body = resp.read().decode("utf-8")
        response_data = json.loads(response_body)
        return self._extract_text(response_data)

    def _format_http_error(self, e: HTTPError) -> str:
        """Mensagem útil de erro HTTP."""
        try:
            body = e.read().decode("utf-8", errors="ignore")
            # Tentar extrair mensagem de erro do JSON do provider
            err_data = json.loads(body)
            for key in ("error", "message", "detail"):
                v = err_data.get(key)
                if isinstance(v, dict):
                    return f"HTTP {e.code}: {v.get('message') or v}"
                if v:
                    return f"HTTP {e.code}: {v}"
            return f"HTTP {e.code}: {body[:200]}"
        except (json.JSONDecodeError, AttributeError):
            return f"HTTP {e.code}: {e.reason}"

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any]:
        """Extrai dict JSON do texto. Lida com fences ```json...``` e cruft."""
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Tentar extrair entre primeiro { e último }
        first = text.find("{")
        last = text.rfind("}")
        if first >= 0 and last > first:
            try:
                return json.loads(text[first : last + 1])
            except json.JSONDecodeError:
                pass
        # Markdown code fences
        m = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
        if m:
            return json.loads(m.group(1))
        raise ValueError("nenhum JSON encontrado na resposta")
