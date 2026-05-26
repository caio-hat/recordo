"""Testes para summarizers (Heuristic + Ollama mock)."""

from __future__ import annotations

import json
from unittest.mock import patch

from recordo.summarizer import (
    SummaryResult,
    available_backends,
    get_summarizer,
)
from recordo.summarizer.base import NoOpSummarizer
from recordo.summarizer.heuristic import HeuristicSummarizer
from recordo.summarizer.ollama import OllamaSummarizer

SAMPLE_TRANSCRIPT = """
Vamos discutir as métricas do Elasticsearch hoje.
Decidimos que vamos usar o Dashboard novo para visualizar os dados.
A gente precisa filtrar por sites para identificar problemas.
Foi combinado que o João vai revisar a configuração até sexta.
A próxima reunião fica para terça-feira.
"""


class TestSummaryResult:
    def test_to_markdown_with_all_fields(self):
        r = SummaryResult(
            resumo="Discussão sobre métricas.",
            topicos=["dashboard", "elasticsearch"],
            decisoes=["Usar Dashboard novo"],
            action_items=["João: revisar config"],
            backend="ollama-test",
        )
        md = r.to_markdown()
        assert "**Resumo:**" in md
        assert "Discussão sobre métricas" in md
        assert "**Tópicos discutidos:**" in md
        assert "- dashboard" in md
        assert "**Decisões:**" in md
        assert "**Ações pendentes:**" in md
        assert "João: revisar config" in md
        assert "ollama-test" in md

    def test_to_markdown_empty(self):
        r = SummaryResult()
        assert "_(sem resumo gerado)_" in r.to_markdown()

    def test_to_markdown_with_error(self):
        r = SummaryResult(error="ollama timeout")
        assert "indisponível" in r.to_markdown()
        assert "ollama timeout" in r.to_markdown()

    def test_is_empty_logic(self):
        assert SummaryResult().is_empty
        assert not SummaryResult(resumo="x").is_empty
        assert not SummaryResult(decisoes=["x"]).is_empty


class TestHeuristicSummarizer:
    def test_basic_summary(self):
        s = HeuristicSummarizer()
        r = s.summarize(SAMPLE_TRANSCRIPT)
        assert r.backend == "heuristic-textrank"
        assert r.error is None
        assert r.resumo  # tem alguma frase
        assert isinstance(r.topicos, list)

    def test_extracts_decisoes(self):
        s = HeuristicSummarizer()
        r = s.summarize(SAMPLE_TRANSCRIPT)
        # Padrões: "Decidimos que" e "Foi combinado que"
        decisoes_lower = [d.lower() for d in r.decisoes]
        assert any("decidimos" in d or "combinado" in d or "vamos usar" in d for d in decisoes_lower), (
            f"esperava decisões em: {r.decisoes}"
        )

    def test_handles_empty_transcript(self):
        s = HeuristicSummarizer()
        r = s.summarize("")
        assert r.error == "transcript vazio"

    def test_strips_whisper_timestamps(self):
        s = HeuristicSummarizer()
        with_ts = "[   0.0 →    8.0] Olá. Tudo bem?\n[   8.0 →   12.5] Sim, e você?"
        r = s.summarize(with_ts)
        # timestamps não devem aparecer no resumo
        assert "→" not in r.resumo

    def test_top_n_sentences_config(self):
        s = HeuristicSummarizer({"top_n_sentences": 2})
        r = s.summarize(SAMPLE_TRANSCRIPT)
        # com 2 sentenças no top, resumo deve ser mais curto
        assert len(r.resumo) < 400


class TestOllamaSummarizer:
    def test_extract_json_direct(self):
        text = '{"resumo": "test", "topicos": ["a"]}'
        d = OllamaSummarizer._extract_json(text)
        assert d["resumo"] == "test"

    def test_extract_json_with_fences(self):
        text = '```json\n{"resumo": "fenced"}\n```'
        d = OllamaSummarizer._extract_json(text)
        assert d["resumo"] == "fenced"

    def test_extract_json_with_cruft(self):
        text = 'Aqui está o JSON: {"resumo": "x"} (fim da resposta)'
        d = OllamaSummarizer._extract_json(text)
        assert d["resumo"] == "x"

    def test_extract_json_invalid_raises(self):
        import pytest

        with pytest.raises(ValueError):
            OllamaSummarizer._extract_json("nada de json aqui")

    def test_summarize_with_mocked_http(self):
        """Mock urlopen para simular resposta do Ollama."""
        s = OllamaSummarizer({"model": "fake:test"})

        mock_response = json.dumps(
            {
                "response": json.dumps(
                    {
                        "resumo": "Mock summary",
                        "topicos": ["t1", "t2"],
                        "decisoes": ["d1"],
                        "action_items": ["a1"],
                    }
                )
            }
        ).encode()

        # Mock context manager para urlopen
        class FakeResp:
            def __init__(self, body):
                self._body = body

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with patch("recordo.summarizer.ollama.urlopen", return_value=FakeResp(mock_response)):
            r = s.summarize("texto", subject="Test")
        assert r.backend == "ollama-fake:test"
        assert r.resumo == "Mock summary"
        assert r.topicos == ["t1", "t2"]
        assert r.decisoes == ["d1"]
        assert r.action_items == ["a1"]
        assert r.error is None

    def test_summarize_empty_transcript(self):
        s = OllamaSummarizer()
        r = s.summarize("")
        assert r.error == "transcript vazio"

    def test_summarize_handles_http_error(self):
        s = OllamaSummarizer({"timeout_seconds": 1})
        from urllib.error import URLError

        with patch("recordo.summarizer.ollama.urlopen", side_effect=URLError("connection refused")):
            r = s.summarize("conteúdo qualquer")
        assert r.error is not None
        assert "indisponível" in r.error.lower()

    def test_truncates_long_transcript(self):
        s = OllamaSummarizer({"max_transcript_chars": 100})
        long_text = "a" * 200
        # Mock urlopen pra capturar o prompt enviado
        captured = {}

        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps(
                    {"response": '{"resumo": "ok", "topicos": [], "decisoes": [], "action_items": []}'}
                ).encode()

        def fake_urlopen(req, timeout=None):
            captured["data"] = req.data.decode("utf-8")
            return FakeResp()

        with patch("recordo.summarizer.ollama.urlopen", side_effect=fake_urlopen):
            s.summarize(long_text)

        # Extrai prompt do JSON enviado (json.dumps escapa unicode com \uXXXX)
        body = json.loads(captured["data"])
        prompt = body["prompt"]
        assert "[…transcrição truncada…]" in prompt


class TestFactory:
    def test_get_heuristic(self):
        s = get_summarizer("heuristic")
        assert isinstance(s, HeuristicSummarizer)

    def test_get_ollama(self):
        s = get_summarizer("ollama")
        assert isinstance(s, OllamaSummarizer)

    def test_get_none(self):
        s = get_summarizer("none")
        assert isinstance(s, NoOpSummarizer)

    def test_unknown_backend_raises(self):
        import pytest

        with pytest.raises(ValueError):
            get_summarizer("nonsense")

    def test_available_backends(self):
        backends = available_backends()
        assert "heuristic" in backends
        assert "none" in backends
        # ollama depende de httpx, mas usa urllib (stdlib), então deve estar lá
        # No nosso caso o test do `ollama` em available depende de httpx import
