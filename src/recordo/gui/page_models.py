"""Models Manager page (M1) — 5ª aba na sidebar.

Cards por backend (Whisper, Parakeet, Ollama) com:
  - Status: ✓ Instalado · ⬇ Baixar · ⏳ Baixando X% · ✕ Falha
  - Botão Baixar/Remover
  - Espaço em disco usado (footer)

Downloads SEMPRE manuais, em background thread com progress bar.
"""

from __future__ import annotations

import logging
import shutil
import threading
from pathlib import Path
from typing import Any

from gi.repository import Adw, GLib, Gtk

from ..models import (
    download_ollama,
    download_parakeet,
    download_whisper,
    get_ollama_size_on_disk,
    get_whisper_size_on_disk,
    is_ollama_installed,
    is_parakeet_installed,
    is_whisper_installed,
    remove_ollama,
    remove_parakeet,
    remove_whisper,
)
from ..models_registry import (
    OLLAMA_MODELS,
    PARAKEET_MODELS,
    WHISPER_MODELS,
    ModelInfo,
    format_size,
)

log = logging.getLogger(__name__)


class ModelsPage(Gtk.Box):
    """Models Manager — download/install/remove de Whisper/Parakeet/Ollama."""

    def __init__(self, window):
        super().__init__(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=24,
            margin_bottom=24,
            margin_start=24,
            margin_end=24,
        )
        self.window = window
        # Tracking state por modelo: model_id -> dict com row, btn_action, progress, status_label
        self._cards: dict[str, dict[str, Any]] = {}
        # Cancellation events por modelo em download
        self._cancel_events: dict[str, threading.Event] = {}

        # Header explicativo
        header = Gtk.Label(xalign=0)
        header.set_markup(
            "<b>Gerenciador de Modelos</b>\n"
            "<small>Downloads são manuais — baixe apenas o que vai usar para economizar disco.</small>"
        )
        header.add_css_class("title-2")
        self.append(header)

        prefs = Adw.PreferencesPage()
        self.append(prefs)

        # Whisper group
        wp_group = Adw.PreferencesGroup(
            title="🎙️ Whisper (faster-whisper)",
            description="Transcrição local · 99 idiomas · CPU/GPU",
        )
        prefs.add(wp_group)
        for info in WHISPER_MODELS.values():
            self._add_card(wp_group, info, backend="whisper")

        # Parakeet group
        pk_group = Adw.PreferencesGroup(
            title="🦜 Parakeet (NVIDIA NeMo)",
            description="Transcrição local · multilingual · requer nemo_toolkit",
        )
        prefs.add(pk_group)
        for info in PARAKEET_MODELS.values():
            self._add_card(pk_group, info, backend="parakeet")

        # Ollama group
        ol_group = Adw.PreferencesGroup(
            title="🤖 Ollama (LLM local para resumos)",
            description="Resumo + tarefas · requer ollama instalado (https://ollama.com)",
        )
        prefs.add(ol_group)
        for info in OLLAMA_MODELS.values():
            self._add_card(ol_group, info, backend="ollama")

        # Footer: espaço total usado
        self.footer_label = Gtk.Label(xalign=0)
        self.footer_label.add_css_class("dim-label")
        self.append(self.footer_label)

        self._refresh_all()

    def _add_card(self, group: Adw.PreferencesGroup, info: ModelInfo, *, backend: str) -> None:
        """Cria Adw.ActionRow para um modelo."""
        title = info.short_name
        if info.recommended:
            title = f"⭐ {title}"
        subtitle = f"{info.description} · {format_size(info.size_bytes)} · {info.languages}"

        row = Adw.ActionRow(title=title, subtitle=subtitle)

        # Suffix: status label + progress bar (oculta) + botão action
        suffix_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8,
            valign=Gtk.Align.CENTER,
        )

        progress = Gtk.ProgressBar()
        progress.set_visible(False)
        progress.set_size_request(120, -1)
        progress.set_show_text(True)
        suffix_box.append(progress)

        status_label = Gtk.Label(label="…")
        status_label.add_css_class("dim-label")
        suffix_box.append(status_label)

        btn_action = Gtk.Button(label="⬇ Baixar")
        btn_action.add_css_class("suggested-action")
        btn_action.connect("clicked", self._on_action_clicked, info, backend)
        suffix_box.append(btn_action)

        row.add_suffix(suffix_box)
        group.add(row)

        self._cards[info.full_id] = {
            "row": row,
            "btn_action": btn_action,
            "progress": progress,
            "status_label": status_label,
            "info": info,
            "backend": backend,
            "downloading": False,
        }

    def _refresh_all(self) -> None:
        """Detecta state instalado/disponível para todos os models + atualiza UI."""
        total_used = 0
        for full_id, card in self._cards.items():
            backend = card["backend"]
            if card["downloading"]:
                continue  # não mexer enquanto download ativo

            installed = self._is_installed(full_id, backend)
            size_used = self._get_size_used(full_id, backend) if installed else 0
            total_used += size_used

            self._update_card_state(card, installed=installed, size_used=size_used)

        if total_used > 0:
            disk_free = self._get_disk_free()
            self.footer_label.set_markup(
                f"<small>Espaço usado pelos modelos: <b>{format_size(total_used)}</b> · "
                f"Livre em disco: {format_size(disk_free)}</small>"
            )
        else:
            self.footer_label.set_markup(
                "<small>Nenhum modelo instalado ainda. Baixe pelo menos 1 transcriber para começar.</small>"
            )

    @staticmethod
    def _get_disk_free() -> int:
        """Retorna bytes livres no disco do home (~/.cache)."""
        try:
            usage = shutil.disk_usage(Path.home())
            return usage.free
        except OSError:
            return 0

    @staticmethod
    def _is_installed(full_id: str, backend: str) -> bool:
        if backend == "whisper":
            return is_whisper_installed(full_id)
        if backend == "parakeet":
            return is_parakeet_installed(full_id)
        if backend == "ollama":
            return is_ollama_installed(full_id)
        return False

    @staticmethod
    def _get_size_used(full_id: str, backend: str) -> int:
        if backend == "whisper" or backend == "parakeet":
            return get_whisper_size_on_disk(full_id)  # mesmo cache HF
        if backend == "ollama":
            return get_ollama_size_on_disk(full_id)
        return 0

    def _update_card_state(self, card: dict, *, installed: bool, size_used: int) -> None:
        btn = card["btn_action"]
        status = card["status_label"]
        progress = card["progress"]
        info = card["info"]

        progress.set_visible(False)

        if installed:
            size_str = format_size(size_used) if size_used > 0 else format_size(info.size_bytes)
            status.set_markup(f"<small>✓ Instalado · {size_str}</small>")
            status.remove_css_class("dim-label")
            status.add_css_class("success")
            btn.set_label("✕ Remover")
            btn.remove_css_class("suggested-action")
            btn.add_css_class("destructive-action")
        else:
            status.set_markup(f"<small>{format_size(info.size_bytes)}</small>")
            status.add_css_class("dim-label")
            status.remove_css_class("success")
            btn.set_label("⬇ Baixar")
            btn.add_css_class("suggested-action")
            btn.remove_css_class("destructive-action")

    def _on_action_clicked(self, btn: Gtk.Button, info: ModelInfo, backend: str) -> None:
        installed = self._is_installed(info.full_id, backend)

        if installed:
            self._confirm_remove(info, backend)
        else:
            self._start_download(info, backend)

    def _confirm_remove(self, info: ModelInfo, backend: str) -> None:
        dlg = Adw.MessageDialog.new(
            self.window,
            f"Remover {info.short_name}?",
            f"O modelo será apagado do disco. Você pode baixar novamente depois.\n\n"
            f"Modelo: {info.full_id}\nTamanho: {format_size(info.size_bytes)}",
        )
        dlg.add_response("cancel", "Cancelar")
        dlg.add_response("remove", "Remover")
        dlg.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.set_default_response("cancel")
        dlg.connect("response", self._on_remove_response, info, backend)
        dlg.present()

    def _on_remove_response(self, _dlg, response: str, info: ModelInfo, backend: str) -> None:
        if response != "remove":
            return

        def worker():
            if backend == "whisper":
                ok = remove_whisper(info.full_id)
            elif backend == "parakeet":
                ok = remove_parakeet(info.full_id)
            elif backend == "ollama":
                ok = remove_ollama(info.full_id)
            else:
                ok = False
            GLib.idle_add(self._on_remove_done, info, ok)

        threading.Thread(target=worker, daemon=True, name=f"recordo-rm-{info.short_name}").start()
        self.window.toast(f"⏳ Removendo {info.short_name}…")

    def _on_remove_done(self, info: ModelInfo, ok: bool) -> bool:
        if ok:
            self.window.toast(f"✓ {info.short_name} removido")
        else:
            self.window.toast(f"⚠ Falha ao remover {info.short_name}")
        self._refresh_all()
        return False

    def _start_download(self, info: ModelInfo, backend: str) -> None:
        card = self._cards[info.full_id]
        if card["downloading"]:
            return  # já em progresso

        card["downloading"] = True
        card["btn_action"].set_label("⏸ Cancelar")
        card["btn_action"].remove_css_class("suggested-action")
        card["btn_action"].add_css_class("destructive-action")
        card["progress"].set_visible(True)
        card["progress"].set_fraction(0.0)
        card["progress"].set_text("0%")
        card["status_label"].set_markup("<small>⏳ Iniciando…</small>")

        cancel_evt = threading.Event()
        self._cancel_events[info.full_id] = cancel_evt

        def progress_cb(pct: float, msg: str) -> None:
            GLib.idle_add(self._on_progress, info, pct, msg)

        def worker():
            # Bug fix v0.2.2: capturar exceção e propagar mensagem real ao user
            err_msg = ""
            ok = False
            try:
                if backend == "whisper":
                    ok = download_whisper(info.full_id, on_progress=progress_cb, cancel_event=cancel_evt)
                elif backend == "parakeet":
                    ok = download_parakeet(info.full_id, on_progress=progress_cb, cancel_event=cancel_evt)
                elif backend == "ollama":
                    ok = download_ollama(info.full_id, on_progress=progress_cb, cancel_event=cancel_evt)
                else:
                    err_msg = f"backend desconhecido: {backend}"
                if not ok and not err_msg:
                    err_msg = "download retornou False (sem detalhes — veja /tmp/recordo.gui.log)"
            except Exception as e:
                log.exception("download %s falhou: %s", info.full_id, e)
                err_msg = f"{type(e).__name__}: {e}"
                ok = False
            GLib.idle_add(self._on_download_done, info, ok, err_msg)

        # Re-binda btn pra cancelar
        try:
            card["btn_action"].disconnect_by_func(self._on_action_clicked)
        except Exception:
            pass
        card["btn_action"].connect("clicked", self._on_cancel_download, info)

        threading.Thread(target=worker, daemon=True, name=f"recordo-dl-{info.short_name}").start()
        self.window.toast(f"⏳ Baixando {info.short_name}…")

    def _on_progress(self, info: ModelInfo, pct: float, msg: str) -> bool:
        card = self._cards.get(info.full_id)
        if card is None:
            return False
        if not card["downloading"]:
            return False
        card["progress"].set_fraction(pct / 100.0)
        card["progress"].set_text(f"{int(pct)}%")
        card["status_label"].set_markup(f"<small>{msg[:60]}</small>")
        return False

    def _on_cancel_download(self, _btn, info: ModelInfo) -> None:
        evt = self._cancel_events.get(info.full_id)
        if evt is not None:
            evt.set()
            self.window.toast(f"⏸ Cancelando {info.short_name}…")

    def _on_download_done(self, info: ModelInfo, ok: bool, err_msg: str = "") -> bool:
        card = self._cards.get(info.full_id)
        if card is None:
            return False
        card["downloading"] = False
        self._cancel_events.pop(info.full_id, None)

        if ok:
            self.window.toast(f"✓ {info.short_name} instalado")
        else:
            # Bug fix v0.2.2: dialog modal com erro real (era só toast genérico)
            self.window.toast(f"⚠ Falha ao baixar {info.short_name}")
            self._show_download_error_dialog(info, err_msg)

        # Reconectar handler normal
        try:
            card["btn_action"].disconnect_by_func(self._on_cancel_download)
        except Exception:
            pass
        card["btn_action"].connect("clicked", self._on_action_clicked, info, card["backend"])

        self._refresh_all()

    def _show_download_error_dialog(self, info: ModelInfo, err_msg: str) -> None:
        """Bug fix v0.2.2: dialog com detalhes do erro (era toast genérico)."""
        from html import escape

        title = f"❌ Falha ao baixar {info.short_name}"
        body_lines = [
            f"<b>Modelo:</b> {escape(info.full_id)}",
            f"<b>Tamanho esperado:</b> {format_size(info.size_bytes)}",
        ]
        if err_msg:
            body_lines.append(f"\n<b>Erro:</b>\n<tt>{escape(err_msg[:600])}</tt>")
        else:
            body_lines.append(
                "\n<i>Nenhuma mensagem de erro capturada — verifique:</i>\n"
                "  • Internet/conexão ao HuggingFace ou Ollama\n"
                "  • Espaço em disco suficiente (~/.cache/huggingface)\n"
                "  • Logs em /tmp/recordo.gui.log e /tmp/recordo.daemon.log"
            )

        body = "\n".join(body_lines)
        dlg = Adw.MessageDialog.new(self.window, title, body)
        dlg.set_body_use_markup(True)
        dlg.add_response("close", "Fechar")
        dlg.set_default_response("close")
        dlg.set_close_response("close")
        dlg.present()
        return False
