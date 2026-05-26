"""Testes do módulo rename: rename_recording + find_recording."""

from __future__ import annotations

from pathlib import Path

from recordo.rename import find_recording, rename_recording


def _make_recording(tmp_path: Path, name: str = "2026-05-26_call_xyz") -> Path:
    """Cria diretório fake com nota.md/resumo.md/audio.opus."""
    d = tmp_path / name
    d.mkdir()
    (d / "audio.opus").write_bytes(b"fake")
    (d / "nota.md").write_text(
        """---
subject: Subject Antigo
date: 2026-05-26T10:00:00
audio: ./audio.opus
---

# Subject Antigo

## Notas


""",
        encoding="utf-8",
    )
    (d / "resumo.md").write_text(f"# Resumo — {name}\n\nResumo aqui.", encoding="utf-8")
    return d


class TestRenameRecording:
    def test_basic_rename(self, tmp_path):
        rec = _make_recording(tmp_path)
        result = rename_recording(rec, "Reunião Product Review", notas_dir=tmp_path)

        assert result.ok
        assert result.new_dir is not None
        assert result.new_dir.exists()
        assert not rec.exists()
        # Nome novo deve ter prefixo de data preservado
        assert result.new_dir.name.startswith("2026-05-26_")
        assert "Reunião_Product_Review" in result.new_dir.name

    def test_updates_frontmatter(self, tmp_path):
        rec = _make_recording(tmp_path)
        result = rename_recording(rec, "Novo Subject", notas_dir=tmp_path)

        assert "nota.md" in result.files_updated
        nota = (result.new_dir / "nota.md").read_text(encoding="utf-8")
        assert "subject: Novo Subject" in nota
        assert "# Novo Subject" in nota

    def test_updates_resumo(self, tmp_path):
        rec = _make_recording(tmp_path)
        result = rename_recording(rec, "Outro Subject", notas_dir=tmp_path)

        assert "resumo.md" in result.files_updated
        resumo = (result.new_dir / "resumo.md").read_text(encoding="utf-8")
        # Header deve ter o novo nome do diretório
        assert result.new_dir.name in resumo

    def test_idempotente_quando_subject_igual(self, tmp_path):
        # Cria com nome simulando "Subject Antigo" sanitizado
        rec = tmp_path / "2026-05-26_Subject_Antigo"
        rec.mkdir()
        (rec / "nota.md").write_text(
            "---\nsubject: Subject Antigo\n---\n# Subject Antigo\n", encoding="utf-8"
        )

        result = rename_recording(rec, "Subject Antigo", notas_dir=tmp_path)
        assert result.ok
        assert result.new_dir == rec  # mesmo path
        assert result.files_updated == []

    def test_falha_em_destino_existente(self, tmp_path):
        rec1 = _make_recording(tmp_path, "2026-05-26_call_a")
        # rec2 com nome que vai ser exatamente o resultado de safe_subject("Existente")
        rec2 = _make_recording(tmp_path, "2026-05-26_Existente")

        result = rename_recording(rec1, "Existente", notas_dir=tmp_path)
        assert not result.ok, f"esperava falha mas foi ok: {result}"
        assert "destino já existe" in result.error
        # rec1 não foi tocado
        assert rec1.exists()
        assert rec2.exists()

    def test_falha_diretorio_inexistente(self, tmp_path):
        result = rename_recording(tmp_path / "nope", "Qualquer", notas_dir=tmp_path)
        assert not result.ok
        assert "não existe" in result.error

    def test_falha_subject_invalido(self, tmp_path):
        rec = _make_recording(tmp_path)
        result = rename_recording(rec, "   ", notas_dir=tmp_path)
        assert not result.ok
        assert "inválido" in result.error.lower() or "vazio" in result.error.lower()
        # rec não foi tocado
        assert rec.exists()

    def test_preserva_data_no_prefixo(self, tmp_path):
        rec = _make_recording(tmp_path, "2026-05-19_old_name")
        result = rename_recording(rec, "Nome Novo", notas_dir=tmp_path)
        assert result.ok
        assert result.new_dir.name.startswith("2026-05-19_")


class TestFindRecording:
    def test_find_by_name(self, tmp_path):
        rec = _make_recording(tmp_path, "2026-05-26_call_test")
        found = find_recording("2026-05-26_call_test", notas_dir=tmp_path)
        assert found == rec

    def test_find_by_substring(self, tmp_path):
        rec = _make_recording(tmp_path, "2026-05-26_call_unique_xyz")
        found = find_recording("unique", notas_dir=tmp_path)
        assert found == rec

    def test_returns_none_quando_ambiguo(self, tmp_path):
        _make_recording(tmp_path, "2026-05-26_call_a")
        _make_recording(tmp_path, "2026-05-27_call_b")
        # "call_" matches both
        found = find_recording("call_", notas_dir=tmp_path)
        assert found is None

    def test_returns_none_quando_nao_existe(self, tmp_path):
        found = find_recording("nada", notas_dir=tmp_path)
        assert found is None

    def test_aceita_path_absoluto(self, tmp_path):
        rec = _make_recording(tmp_path, "2026-05-26_test")
        found = find_recording(str(rec), notas_dir=tmp_path)
        assert found == rec
