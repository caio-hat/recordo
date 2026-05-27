"""OllamaSummarizer — LLM local via Ollama HTTP (default backend).

Por que Ollama:
  - Local-first: zero data leak, alinhado com privacy do projeto.
  - Setup simples: `curl https://ollama.com/install.sh | sh`.
  - Suporta modelos pequenos rápidos: gemma2:2b, qwen2.5:3b, llama3.2:3b
    rodam confortavelmente em CPU (4-8 GB RAM).
  - HTTP API JSON simples — sem precisar de SDK pesado.

Modelo recomendado:
  - gemma2:2b ou qwen2.5:3b — bons em pt-BR, rápidos em CPU
  - llama3.1:8b — qualidade superior se tiver GPU/RAM suficiente

Uso:
  ollama serve  # se não estiver rodando
  ollama pull gemma2:2b
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .base import Summarizer, SummaryResult

log = logging.getLogger(__name__)

DEFAULT_MODEL = "gemma2:2b"
DEFAULT_HOST = "http://localhost:11434"
DEFAULT_TIMEOUT = 120  # segundos — modelos pequenos respondem em <30s

# Prompt em pt-BR estruturado pra extrair seções confiáveis. Pedimos JSON
# pra parsing robusto (Ollama suporta `format: "json"` que força JSON válido).
_PROMPT_TEMPLATE = """Você é um assistente que resume reuniões e conversas em português do Brasil.

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


class OllamaSummarizer(Summarizer):
    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config or {}
        self.model: str = cfg.get("model", DEFAULT_MODEL)
        self.host: str = cfg.get("host", DEFAULT_HOST).rstrip("/")
        self.timeout: int = cfg.get("timeout_seconds", DEFAULT_TIMEOUT)
        # Quando o transcript é gigante (>100k chars), truncamos na frente
        # pra não estourar contexto do modelo. Modelos pequenos costumam
        # aguentar 8k-32k tokens.
        self.max_chars: int = cfg.get("max_transcript_chars", 30000)
        # Context window do modelo (tokens). Default 8192 é seguro mas
        # apertado pra reuniões longas. gemma2:7b/llama3.1:8b/gemma4:e2b
        # suportam 32768-128000. Configure conforme a hardware/modelo.
        self.num_ctx: int = cfg.get("num_ctx", 8192)
        self.temperature: float = cfg.get("temperature", 0.3)

    @property
    def name(self) -> str:
        return f"ollama-{self.model}"

    def summarize(self, transcript: str, *, language: str = "pt", subject: str = "") -> SummaryResult:
        if not transcript.strip():
            return SummaryResult(backend=self.name, error="transcript vazio")

        truncated = transcript
        if len(truncated) > self.max_chars:
            log.info("transcript longo (%d chars), truncando para %d", len(truncated), self.max_chars)
            truncated = truncated[: self.max_chars] + "\n[…transcrição truncada…]"

        subject_line = f"ASSUNTO: {subject}\n\n" if subject else ""
        prompt = _PROMPT_TEMPLATE.format(transcript=truncated, subject_line=subject_line)

        try:
            response_text = self._call_ollama(prompt)
        except (HTTPError, URLError, OSError) as e:
            log.error("ollama indisponível: %s", e)
            return SummaryResult(backend=self.name, error=f"ollama indisponível ({e})")
        except TimeoutError as e:
            log.error("ollama timeout: %s", e)
            return SummaryResult(backend=self.name, error="ollama timeout")

        # Parse JSON robusto
        try:
            data = self._extract_json(response_text)
        except (ValueError, json.JSONDecodeError) as e:
            log.error("ollama retornou JSON inválido: %s\nResposta: %s", e, response_text[:500])
            return SummaryResult(
                backend=self.name,
                resumo=response_text.strip()[:1000],  # fallback: bota tudo no resumo
                error="JSON inválido (resposta bruta no resumo)",
            )

        return SummaryResult(
            resumo=str(data.get("resumo", "")).strip(),
            topicos=[str(x).strip() for x in data.get("topicos", []) if str(x).strip()],
            decisoes=[str(x).strip() for x in data.get("decisoes", []) if str(x).strip()],
            action_items=[str(x).strip() for x in data.get("action_items", []) if str(x).strip()],
            backend=self.name,
        )

    def _call_ollama(self, prompt: str) -> str:
        """POST /api/generate com format=json. Retorna o campo `response`."""
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",  # força JSON válido (feature do Ollama)
            "options": {
                "temperature": self.temperature,  # baixa pra consistência (default 0.3)
                "num_ctx": self.num_ctx,  # configurável: default 8192, gemma4 aguenta 32k+
            },
        }
        req = Request(
            f"{self.host}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=self.timeout) as resp:
            body = resp.read().decode("utf-8")
        data = json.loads(body)
        return str(data.get("response", "")).strip()

    def _list_available_models(self) -> list[str]:
        """GET /api/tags — lista modelos instalados. Best-effort, retorna [] se falhar."""
        try:
            req = Request(f"{self.host}/api/tags", method="GET")
            with urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return [m["name"] for m in data.get("models", []) if "name" in m]
        except (HTTPError, URLError, OSError, json.JSONDecodeError):
            return []

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any]:
        """Extrai dict JSON do texto. Lida com fences ```json...``` e cruft."""
        text = text.strip()
        # tenta direto
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # tenta extrair entre primeiro { e último }
        first = text.find("{")
        last = text.rfind("}")
        if first >= 0 and last > first:
            try:
                return json.loads(text[first : last + 1])
            except json.JSONDecodeError:
                pass
        # tenta remover fences markdown
        m = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
        if m:
            return json.loads(m.group(1))
        raise ValueError("nenhum JSON encontrado na resposta")
