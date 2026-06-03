# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Caio Hat
"""RecordingDetailPage — visualização detalhada de 1 gravação.

Mostra nota.md, transcrição, resumo, tarefas e tópicos em tabs separadas
usando MarkdownView (WebKit). Links externos abrem no browser.
Ações: re-transcrever, resumir, extrair tarefas.
"""

from __future__ import annotations

import logging
import subprocess
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

from ..molecules import EmptyState
from ..organisms import MarkdownView

log = logging.getLogger(__name__)

# Tabs: (label, filename, fallback_message, icon_name)
# Ícones GNOME symbolic disponíveis em todos os temas (Adwaita stock).
TABS: list[tuple[str, str, str, str]] = [
    ("Nota", "nota.md", "Esta gravação ainda não tem nota.md", "document-edit-symbolic"),
    (
        "Transcrição",
        "transcricao.txt",
        'Transcrição ainda não foi gerada. Use "Transcrever" no topo.',
        "audio-input-microphone-symbolic",
    ),
    (
        "Resumo",
        "summary.md",
        'Resumo ainda não foi gerado. Use "Resumir" no topo.',
        "view-paged-symbolic",
    ),
    (
        "Tarefas",
        "tasks.md",
        'Tarefas ainda não foram extraídas. Use "Tarefas" no topo.',
        "checkbox-checked-symbolic",
    ),
    (
        "Tópicos",
        "topics.json",
        "Tópicos ainda não foram extraídos.",
        "view-grid-symbolic",
    ),
]


class RecordingDetailPage(Adw.NavigationPage):
    """NavigationPage com tabs renderizadas em MarkdownView."""

    def __init__(self, rec_dir: Path) -> None:
        super().__init__(
            title=rec_dir.name.replace("_", " "),
            tag=f"recording-{rec_dir.name}",
        )
        self._rec_dir = rec_dir

        toolbar = Adw.ToolbarView()
        self.set_child(toolbar)

        header = Adw.HeaderBar()
        toolbar.add_top_bar(header)

        # Botões de ação visíveis no header (substitui menu escondido)
        # v0.2.4: user reportou que botões de gerar/transcrever sumiram com redesign.
        self._btn_transcribe = Gtk.Button(label="✎ Transcrever")
        self._btn_transcribe.set_tooltip_text("Gerar transcrição (faster-whisper / parakeet)")
        self._btn_transcribe.add_css_class("flat")
        self._btn_transcribe.connect("clicked", lambda _b: self._run_pipeline_step("transcribe"))
        header.pack_start(self._btn_transcribe)

        self._btn_summarize = Gtk.Button(label="📝 Resumir")
        self._btn_summarize.set_tooltip_text("Gerar resumo via LLM (Ollama / Gemini)")
        self._btn_summarize.add_css_class("flat")
        self._btn_summarize.connect("clicked", lambda _b: self._run_pipeline_step("summarize"))
        header.pack_start(self._btn_summarize)

        self._btn_tasks = Gtk.Button(label="✅ Tarefas")
        self._btn_tasks.set_tooltip_text("Extrair tarefas via LLM")
        self._btn_tasks.add_css_class("flat")
        self._btn_tasks.connect("clicked", lambda _b: self._run_pipeline_step("tasks"))
        header.pack_start(self._btn_tasks)

        # Spinner pra mostrar pipeline rodando
        self._action_spinner = Gtk.Spinner()
        self._action_spinner.set_visible(False)
        header.pack_start(self._action_spinner)

        # Menu ⋮ (overflow: pasta, editor, etc)
        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic")
        menu_btn.set_tooltip_text("Mais ações")
        menu_btn.set_menu_model(self._build_menu_model())
        header.pack_end(menu_btn)

        # Title widget
        title_widget = Adw.WindowTitle.new(self.get_title(), str(rec_dir))
        header.set_title_widget(title_widget)

        # ViewStack + ViewSwitcherBar (bottom tabs)
        self._stack = Adw.ViewStack()
        switcher_bar = Adw.ViewSwitcherBar()
        switcher_bar.set_stack(self._stack)
        switcher_bar.set_reveal(True)
        toolbar.add_bottom_bar(switcher_bar)
        toolbar.set_content(self._stack)

        self._init_tabs()
        self._init_actions()

    # ------------------------------------------------------------------

    def _init_tabs(self) -> None:
        for label, filename, fallback, icon_name in TABS:
            view = self._build_tab(filename, fallback)
            page = self._stack.add(view)
            page.set_title(label)
            page.set_name(filename)
            # v0.2.4 fix: set icon_name explicitamente para Adw.ViewSwitcherBar
            # mostrar ícones reais (sem isso aparece símbolo "proibido")
            page.set_icon_name(icon_name)

    def _init_actions(self) -> None:
        group = Gio.SimpleActionGroup()
        for name, cb in [
            ("open-folder", self._on_open_folder),
            ("open-in-editor", self._on_open_in_editor),
            ("retranscribe", self._on_retranscribe),
            ("resummarize", self._on_resummarize),
            ("extract-tasks", self._on_extract_tasks),
        ]:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", cb)
            group.add_action(action)
        self.insert_action_group("rec", group)

    def _build_menu_model(self) -> Gio.Menu:
        menu = Gio.Menu.new()
        menu.append("Re-transcrever", "rec.retranscribe")
        menu.append("Resumir", "rec.resummarize")
        menu.append("Extrair tarefas", "rec.extract-tasks")
        section = Gio.Menu.new()
        section.append("Abrir pasta", "rec.open-folder")
        section.append("Editar nota.md no editor", "rec.open-in-editor")
        menu.append_section(None, section)
        return menu

    def _build_tab(self, filename: str, fallback: str) -> Gtk.Widget:
        target = self._rec_dir / filename
        if target.exists() and target.stat().st_size > 0:
            view = MarkdownView()
            view.load_file(target)
            return view
        return EmptyState(
            icon="document-symbolic",
            title=filename,
            description=fallback,
        )

    # ---------- Actions ----------

    def _on_open_folder(self, *_args) -> None:
        try:
            subprocess.Popen(
                ["xdg-open", str(self._rec_dir)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            log.warning("xdg-open ausente")

    def _on_open_in_editor(self, *_args) -> None:
        nota = self._rec_dir / "nota.md"
        if not nota.exists():
            return
        try:
            subprocess.Popen(
                ["xdg-open", str(nota)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            pass

    def _on_retranscribe(self, *_args) -> None:
        self._run_pipeline_step("transcribe")

    def _on_resummarize(self, *_args) -> None:
        self._run_pipeline_step("summarize")

    def _on_extract_tasks(self, *_args) -> None:
        self._run_pipeline_step("tasks")

    def _run_pipeline_step(self, step: str) -> None:
        """Roda step do pipeline em thread, recarrega tabs ao final.

        v0.2.4: feedback visual via spinner + botões desabilitados durante execução.
        """
        # Bloqueia botões e mostra spinner
        self._set_action_buttons_busy(True, step)

        def worker() -> None:
            error_msg = ""
            ok = False
            try:
                from ...config import load_config
                from ...pipeline import run_step  # type: ignore[attr-defined]

                cfg = load_config()
                result = run_step(self._rec_dir, step, config=cfg)
                ok = bool(result.get("ok"))
                if not ok:
                    error_msg = str(result.get("error", "erro desconhecido"))
            except Exception as e:
                log.exception("run_step %s falhou", step)
                error_msg = f"{type(e).__name__}: {e}"
            GLib.idle_add(self._on_pipeline_done, step, ok, error_msg)

        threading.Thread(target=worker, daemon=True, name=f"recordo-detail-{step}").start()

    def _set_action_buttons_busy(self, busy: bool, current_step: str = "") -> None:
        """Desabilita botões + mostra spinner durante operação longa."""
        for btn in (self._btn_transcribe, self._btn_summarize, self._btn_tasks):
            btn.set_sensitive(not busy)
        self._action_spinner.set_visible(busy)
        if busy:
            self._action_spinner.start()
        else:
            self._action_spinner.stop()

    def _on_pipeline_done(self, step: str, ok: bool, error_msg: str) -> bool:
        self._set_action_buttons_busy(False)
        self._reload_tabs()

        # Toast no parent window se disponível
        root = self.get_root()
        if root is not None and hasattr(root, "toast"):
            step_label = {"transcribe": "Transcrição", "summarize": "Resumo", "tasks": "Tarefas"}.get(
                step, step
            )
            if ok:
                root.toast(f"✓ {step_label} pronta")
            else:
                # Mostra dialog com erro real (não só toast)
                self._show_step_error_dialog(step_label, error_msg)
        return GLib.SOURCE_REMOVE

    def _show_step_error_dialog(self, step_label: str, err_msg: str) -> None:
        from html import escape

        title = f"❌ {step_label} falhou"
        body = (
            f"<b>Não foi possível concluir.</b>\n\n"
            f"<b>Erro:</b>\n<tt>{escape(err_msg[:600])}</tt>\n\n"
            "<b>Possíveis causas:</b>\n"
            "  • Modelo não baixado — abra Modelos no menu lateral\n"
            "  • Memória insuficiente — verifique Sistema no Dashboard\n"
            "  • Daemon offline — reinicie via menu superior"
        )
        dlg = Adw.MessageDialog.new(self.get_root(), title, body)
        dlg.set_body_use_markup(True)
        dlg.add_response("close", "Fechar")
        dlg.set_default_response("close")
        dlg.set_close_response("close")
        dlg.present()

    def _reload_tabs(self) -> bool:
        """Reconstrói tabs com conteúdo atualizado."""
        # Remove all children then re-add
        while child := self._stack.get_first_child():
            self._stack.remove(child)
        self._init_tabs()
        return GLib.SOURCE_REMOVE
