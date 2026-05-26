"""Testes do módulo search."""

from __future__ import annotations

from pathlib import Path

from recordo.search import SearchHit, search_notas


def _make_recording(notas_dir: Path, name: str, nota_text: str = "", trans_text: str = "") -> Path:
    d = notas_dir / name
    d.mkdir(parents=True)
    if nota_text:
        (d / "nota.md").write_text(nota_text, encoding="utf-8")
    if trans_text:
        (d / "transcricao.txt").write_text(trans_text, encoding="utf-8")
    return d


class TestSearchNotas:
    def test_returns_empty_when_dir_absent(self, tmp_path):
        results = search_notas("query", notas_dir=tmp_path / "nonexistent")
        assert results == []

    def test_finds_substring_in_nota(self, tmp_path):
        _make_recording(
            tmp_path,
            "2026-05-26_test",
            nota_text="# Reunião\n\nDiscussão sobre Datadog e Elasticsearch.",
        )
        results = search_notas("Datadog", notas_dir=tmp_path)
        assert len(results) == 1
        assert results[0].match_count >= 1
        assert "Datadog" in results[0].snippets[0] or "**Datadog**" in results[0].snippets[0]

    def test_case_insensitive_default(self, tmp_path):
        _make_recording(tmp_path, "2026-05-26_a", nota_text="Datadog é importante")
        results = search_notas("datadog", notas_dir=tmp_path)
        assert len(results) >= 1

    def test_case_sensitive_quando_pedido(self, tmp_path):
        _make_recording(tmp_path, "2026-05-26_a", nota_text="datadog em minúsculas")
        results = search_notas("DATADOG", notas_dir=tmp_path, case_sensitive=True)
        assert results == []
        results = search_notas("datadog", notas_dir=tmp_path, case_sensitive=True)
        assert len(results) >= 1

    def test_busca_em_transcricao_txt(self, tmp_path):
        _make_recording(
            tmp_path,
            "2026-05-26_meeting",
            nota_text="# Header",
            trans_text="[0.0 → 5.0] Vamos falar sobre Kubernetes hoje.",
        )
        results = search_notas("Kubernetes", notas_dir=tmp_path)
        assert any(r.file_relative == "transcricao.txt" for r in results)

    def test_multiple_matches_count(self, tmp_path):
        _make_recording(
            tmp_path,
            "2026-05-26_test",
            nota_text="Dashboard. Dashboard. Dashboard. Dashboard.",
        )
        results = search_notas("Dashboard", notas_dir=tmp_path)
        assert results[0].match_count == 4

    def test_resumo_md_tem_peso_maior(self, tmp_path):
        # Mesmo número de matches mas em resumo.md → score maior
        _make_recording(tmp_path, "2026-05-26_a", nota_text="Datadog em nota")
        d2 = _make_recording(tmp_path, "2026-05-26_b", nota_text="# Tit")
        (d2 / "resumo.md").write_text("Datadog em resumo", encoding="utf-8")

        results = search_notas("Datadog", notas_dir=tmp_path)
        # resumo.md vem primeiro porque weight=1.5 > nota.md weight=1.0
        first = results[0]
        assert first.file_relative == "resumo.md"

    def test_regex_pattern(self, tmp_path):
        _make_recording(
            tmp_path,
            "2026-05-26_a",
            nota_text="versão 1.2.3 e versão 2.0.0",
        )
        results = search_notas(r"versão \d+\.\d+\.\d+", notas_dir=tmp_path)
        assert len(results) == 1
        assert results[0].match_count == 2

    def test_invalid_regex_fallback_substring(self, tmp_path):
        _make_recording(tmp_path, "2026-05-26_a", nota_text="texto com [colchetes]")
        # Regex inválido → tratado como substring literal
        results = search_notas("[colchetes]", notas_dir=tmp_path)
        assert len(results) >= 1

    def test_file_filter(self, tmp_path):
        _make_recording(
            tmp_path,
            "2026-05-26_a",
            nota_text="Datadog em nota",
            trans_text="Datadog em transcricao",
        )
        # Filtra só nota.md
        results = search_notas("Datadog", notas_dir=tmp_path, file_filter=["nota.md"])
        assert all(r.file_relative == "nota.md" for r in results)


class TestSearchHitScore:
    def test_score_aumenta_com_matches(self, tmp_path):
        f1 = tmp_path / "x"
        f1.mkdir()
        (f1 / "nota.md").write_text("a")  # garantir que stat funciona
        h1 = SearchHit(recording_dir=f1, file_relative="nota.md", match_count=1, weight=1.0)
        h2 = SearchHit(recording_dir=f1, file_relative="nota.md", match_count=10, weight=1.0)
        assert h2.score > h1.score
