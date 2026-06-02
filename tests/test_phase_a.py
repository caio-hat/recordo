"""Tests for Phase A: tasks extractor + ollama unload + run_step dispatcher."""

from __future__ import annotations

import time
from unittest.mock import patch

from recordo.pipeline import get_recording_status, run_step
from recordo.summarizer import ollama as ollama_mod
from recordo.summarizer.ollama import (
    get_ollama_last_used,
    mark_ollama_in_use,
    unload_ollama_idle_models,
    unload_ollama_model,
)
from recordo.summarizer.tasks import (
    TaskItem,
    TasksResult,
    _parse_tasks_json,
    extract_tasks,
)


class TestTasksParser:
    """A4: parse JSON robusto da resposta LLM."""

    def test_parse_valid_json(self):
        raw = '{"tarefas": [{"descricao": "Deploy staging", "responsavel": "Joao", "prazo": "sexta", "tipo": "task"}]}'
        items = _parse_tasks_json(raw)
        assert len(items) == 1
        assert items[0].descricao == "Deploy staging"
        assert items[0].responsavel == "Joao"
        assert items[0].prazo == "sexta"
        assert items[0].tipo == "task"

    def test_parse_with_markdown_fence(self):
        raw = '```json\n{"tarefas": [{"descricao": "X", "tipo": "decisao"}]}\n```'
        items = _parse_tasks_json(raw)
        assert len(items) == 1
        assert items[0].tipo == "decisao"

    def test_parse_with_text_around(self):
        raw = 'Aqui está o JSON solicitado:\n\n{"tarefas": [{"descricao": "A"}]}\n\nFim.'
        items = _parse_tasks_json(raw)
        assert len(items) == 1

    def test_parse_invalid_json_returns_empty(self):
        items = _parse_tasks_json("não é JSON")
        assert items == []

    def test_parse_empty_tarefas(self):
        items = _parse_tasks_json('{"tarefas": []}')
        assert items == []

    def test_parse_skips_empty_descricao(self):
        raw = '{"tarefas": [{"descricao": "", "tipo": "task"}, {"descricao": "Real", "tipo": "task"}]}'
        items = _parse_tasks_json(raw)
        assert len(items) == 1
        assert items[0].descricao == "Real"


class TestTaskItem:
    """A4: TaskItem markdown rendering."""

    def test_task_with_responsavel_and_prazo(self):
        t = TaskItem(descricao="Deploy", responsavel="Maria", prazo="sexta", tipo="task")
        line = t.to_markdown_line()
        assert "@Maria" in line
        assert "Deploy" in line
        assert "sexta" in line
        assert line.startswith("- [ ]")

    def test_decisao_rendered_as_checked(self):
        t = TaskItem(descricao="Adotar K8s", tipo="decisao")
        line = t.to_markdown_line()
        assert line.startswith("- [x]")
        assert "✅" in line

    def test_followup_emoji(self):
        t = TaskItem(descricao="Confirmar prazo", tipo="followup")
        line = t.to_markdown_line()
        assert "🔄" in line


class TestTasksResult:
    """A4: TasksResult markdown grouping."""

    def test_empty_renders_placeholder(self):
        r = TasksResult()
        md = r.to_markdown()
        assert "nenhuma tarefa identificada" in md

    def test_groups_by_type(self):
        r = TasksResult(
            tasks=[
                TaskItem("Task A", tipo="task"),
                TaskItem("Decisao B", tipo="decisao"),
                TaskItem("Followup C", tipo="followup"),
                TaskItem("Task D", tipo="task"),
            ],
            backend="ollama-test",
        )
        md = r.to_markdown()
        assert "## 🔧 Action Items" in md
        assert "## ✅ Decisões" in md
        assert "## 🔄 Follow-ups" in md
        # Action items section deve ter 2 tasks
        ai_section = md.split("## 🔧 Action Items")[1].split("##")[0]
        assert "Task A" in ai_section
        assert "Task D" in ai_section
        assert "ollama-test" in md

    def test_error_takes_precedence(self):
        r = TasksResult(error="LLM offline")
        md = r.to_markdown()
        assert "LLM offline" in md
        assert "extração falhou" in md


class TestExtractTasks:
    """A4: extract_tasks integration."""

    def test_empty_transcript_returns_error(self):
        r = extract_tasks("", summarizer_cfg={"backend": "ollama"})
        assert r.error == "transcrição vazia"

    def test_heuristic_backend_returns_error(self):
        """Heuristic não suporta JSON estruturado de tasks."""
        r = extract_tasks("texto", summarizer_cfg={"backend": "heuristic"})
        assert "não suporta" in r.error.lower() or "heuristic" in r.error.lower()

    def test_none_backend_returns_error(self):
        r = extract_tasks("texto", summarizer_cfg={"backend": "none"})
        assert r.error is not None


class TestOllamaUnload:
    """A5: Ollama unload tracking + API call."""

    def setup_method(self):
        # Limpa state global entre tests
        with ollama_mod._OLLAMA_LOCK:
            ollama_mod._OLLAMA_LAST_USED_AT.clear()
        ollama_mod._OLLAMA_PIPELINE_ACTIVE.clear()

    def test_mark_records_timestamp(self):
        mark_ollama_in_use("gemma:2b", host="http://localhost:11434")
        last = get_ollama_last_used()
        assert "http://localhost:11434|gemma:2b" in last
        assert last["http://localhost:11434|gemma:2b"] > 0

    def test_unload_idle_skipped_during_pipeline(self):
        """Se _OLLAMA_PIPELINE_ACTIVE set, unload não age."""
        mark_ollama_in_use("gemma:2b")
        # Forçar idle: subtrair 1h do timestamp
        with ollama_mod._OLLAMA_LOCK:
            for k in ollama_mod._OLLAMA_LAST_USED_AT:
                ollama_mod._OLLAMA_LAST_USED_AT[k] = time.monotonic() - 3600
        ollama_mod._OLLAMA_PIPELINE_ACTIVE.set()
        n = unload_ollama_idle_models(idle_threshold_sec=300)
        assert n == 0  # nada descarregado

    def test_unload_idle_calls_api_and_removes_tracking(self):
        """Modelo idle > threshold deve ser descarregado e removido do tracking."""
        mark_ollama_in_use("gemma:2b", host="http://localhost:11434")
        with ollama_mod._OLLAMA_LOCK:
            for k in ollama_mod._OLLAMA_LAST_USED_AT:
                ollama_mod._OLLAMA_LAST_USED_AT[k] = time.monotonic() - 3600

        # Mock unload_ollama_model para simular sucesso
        with patch.object(ollama_mod, "unload_ollama_model", return_value=True) as mock_unload:
            n = unload_ollama_idle_models(idle_threshold_sec=300)
            assert n == 1
            mock_unload.assert_called_once_with("gemma:2b", host="http://localhost:11434")
        # tracking foi limpo
        assert get_ollama_last_used() == {}

    def test_unload_idle_keeps_recent(self):
        mark_ollama_in_use("recent:model")
        n = unload_ollama_idle_models(idle_threshold_sec=300)
        assert n == 0
        assert "http://localhost:11434|recent:model" in get_ollama_last_used()

    def test_unload_model_handles_network_error(self):
        """Se urlopen falha, retorna False sem levantar."""
        with patch.object(ollama_mod, "urlopen", side_effect=OSError("connection refused")):
            ok = unload_ollama_model("gemma:2b")
            assert ok is False


class TestRunStep:
    """A3: run_step dispatcher."""

    def test_invalid_step_returns_error(self, tmp_path):
        target = tmp_path / "session"
        target.mkdir()
        (target / "audio.opus").write_bytes(b"x")
        (target / "nota.md").write_text("# x")
        r = run_step(target, "invalid")
        assert r["ok"] is False
        assert "step inválido" in r["error"]

    def test_missing_audio_returns_error(self, tmp_path):
        target = tmp_path / "empty"
        target.mkdir()
        r = run_step(target, "transcribe")
        assert r["ok"] is False
        assert "audio.opus ausente" in r["error"]

    def test_summarize_without_transcript_returns_error(self, tmp_path):
        target = tmp_path / "session"
        target.mkdir()
        (target / "audio.opus").write_bytes(b"x")
        (target / "nota.md").write_text("# x")
        r = run_step(target, "summarize")
        assert r["ok"] is False
        assert "transcrição" in r["error"].lower()


class TestGetRecordingStatus:
    """A3: get_recording_status detection."""

    def test_empty_dir_all_false(self, tmp_path):
        s = get_recording_status(tmp_path)
        assert s["has_audio"] is False
        assert s["has_transcript"] is False
        assert s["has_summary"] is False
        assert s["has_tasks"] is False

    def test_only_audio(self, tmp_path):
        target = tmp_path / "rec"
        target.mkdir()
        (target / "audio.opus").write_bytes(b"x")
        s = get_recording_status(target)
        assert s["has_audio"] is True
        assert s["has_transcript"] is False

    def test_with_transcript_file(self, tmp_path):
        target = tmp_path / "rec"
        target.mkdir()
        (target / "audio.opus").write_bytes(b"x")
        (target / "transcricao.txt").write_text("texto da transcrição")
        s = get_recording_status(target)
        assert s["has_transcript"] is True

    def test_with_resumo_md(self, tmp_path):
        target = tmp_path / "rec"
        target.mkdir()
        (target / "audio.opus").write_bytes(b"x")
        (target / "resumo.md").write_text("# Resumo\n\nTexto")
        (target / "nota.md").write_text("# x")
        s = get_recording_status(target)
        assert s["has_summary"] is True

    def test_with_tasks_md(self, tmp_path):
        target = tmp_path / "rec"
        target.mkdir()
        (target / "audio.opus").write_bytes(b"x")
        (target / "tasks.md").write_text("# Tarefas\n\n- [ ] X")
        (target / "nota.md").write_text("# x")
        s = get_recording_status(target)
        assert s["has_tasks"] is True

    def test_placeholder_does_not_count_as_done(self, tmp_path):
        from recordo.pipeline import SUMMARY_PLACEHOLDER

        target = tmp_path / "rec"
        target.mkdir()
        (target / "audio.opus").write_bytes(b"x")
        (target / "nota.md").write_text(f"# x\n\n## Resumo\n\n{SUMMARY_PLACEHOLDER}\n")
        s = get_recording_status(target)
        assert s["has_summary"] is False
