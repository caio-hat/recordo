"""Testes do módulo topics."""

from __future__ import annotations

from unittest.mock import patch

from recordo.topics import (
    Topic,
    TopicsResult,
    _fmt_ts,
    _heuristic_extract_topics,
    extract_topics,
)
from recordo.transcribers.base import TranscriptionResult, TranscriptionSegment


def _make_segments(*pairs: tuple[float, float, str]) -> list[TranscriptionSegment]:
    return [TranscriptionSegment(start=s, end=e, text=t) for s, e, t in pairs]


class TestFormatTs:
    def test_seconds_only(self):
        assert _fmt_ts(0) == "00:00"
        assert _fmt_ts(45) == "00:45"

    def test_minutes(self):
        assert _fmt_ts(125) == "02:05"

    def test_hours(self):
        assert _fmt_ts(3725) == "01:02:05"


class TestTopic:
    def test_inicio_str_formats(self):
        t = Topic(titulo="X", inicio_seconds=125, fim_seconds=300)
        assert t.inicio_str == "02:05"
        assert t.fim_str == "05:00"
        assert t.duration_seconds == 175


class TestTopicsResult:
    def test_to_markdown_simples(self):
        r = TopicsResult(
            topics=[
                Topic(titulo="Tópico A", inicio_seconds=0, fim_seconds=300),
                Topic(titulo="Tópico B", inicio_seconds=300, fim_seconds=600),
            ],
            backend="test-backend",
        )
        md = r.to_markdown()
        assert "00:00 — 05:00" in md
        assert "Tópico A" in md
        assert "test-backend" in md

    def test_to_markdown_marca_retorno(self):
        r = TopicsResult(
            topics=[
                Topic(titulo="A", inicio_seconds=0, fim_seconds=100),
                Topic(
                    titulo="A novamente",
                    inicio_seconds=200,
                    fim_seconds=250,
                    retorno_de_topico_anterior=True,
                ),
            ],
            backend="ollama",
        )
        md = r.to_markdown()
        assert "↻" in md
        assert "retoma" in md

    def test_to_markdown_vazio(self):
        r = TopicsResult()
        assert "_(sem tópicos identificados)_" in r.to_markdown()

    def test_to_markdown_com_erro(self):
        r = TopicsResult(error="ollama timeout")
        assert "indisponíveis" in r.to_markdown()

    def test_to_json(self):
        r = TopicsResult(
            topics=[Topic(titulo="X", inicio_seconds=0, fim_seconds=10)],
            backend="b",
        )
        import json as _json

        data = _json.loads(r.to_json())
        assert data["backend"] == "b"
        assert len(data["topics"]) == 1
        assert data["topics"][0]["titulo"] == "X"


class TestHeuristicExtract:
    def test_short_recording_single_topic(self):
        segs = _make_segments(
            (0, 10, "Olá pessoal vamos discutir métricas hoje."),
            (10, 30, "O dashboard mostra os custos do mês."),
            (30, 50, "Precisamos otimizar isso urgente."),
        )
        result = TranscriptionResult(segments=segs, language="pt")
        r = _heuristic_extract_topics(result)
        assert r.error is None
        assert len(r.topics) == 1  # < 60s = tópico único
        assert r.backend == "heuristic-keywords"

    def test_long_recording_multiple_topics(self):
        # 1200s (20min) → deve gerar ~3 tópicos
        segs = []
        for i in range(60):
            segs.append(
                TranscriptionSegment(
                    start=i * 20,
                    end=(i + 1) * 20,
                    text=f"Trecho {i} sobre dashboard métricas custos elasticsearch.",
                )
            )
        result = TranscriptionResult(segments=segs, language="pt")
        r = _heuristic_extract_topics(result)
        assert r.error is None
        assert len(r.topics) >= 2
        # Tópicos cobrem toda duração
        assert r.topics[0].inicio_seconds == 0
        assert r.topics[-1].fim_seconds >= 1100

    def test_empty_transcription(self):
        result = TranscriptionResult(segments=[], language="pt")
        r = _heuristic_extract_topics(result)
        assert r.error is not None


class TestExtractTopicsRouter:
    def test_backend_heuristic_diretamente(self):
        segs = _make_segments(
            (0, 30, "Discussão sobre dashboard."),
            (30, 60, "Configuração de alertas."),
        )
        result = TranscriptionResult(segments=segs, language="pt")
        r = extract_topics(result, summarizer_cfg={"backend": "heuristic"})
        assert "heuristic" in r.backend

    def test_backend_none_usa_heuristic(self):
        segs = _make_segments((0, 30, "x"), (30, 60, "y"))
        result = TranscriptionResult(segments=segs, language="pt")
        r = extract_topics(result, summarizer_cfg={"backend": "none"})
        assert "heuristic" in r.backend

    def test_llm_falha_fallback_heuristic(self):
        """Se Ollama 404, deve cair pra heuristic."""
        segs = _make_segments((0, 30, "Discussão sobre dashboard."))
        result = TranscriptionResult(segments=segs, language="pt")

        # Mock urlopen pra simular Ollama indisponível
        from urllib.error import URLError

        with patch(
            "recordo.summarizer.ollama.urlopen",
            side_effect=URLError("connection refused"),
        ):
            r = extract_topics(result, summarizer_cfg={"backend": "ollama"})

        # Fallback deve ter ocorrido
        assert "heuristic" in r.backend
        assert "fallback" in r.backend
