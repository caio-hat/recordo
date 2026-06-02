"""Page Status: card grande com indicador + tempo decorrido + polling 1s + logs (D1)."""

from __future__ import annotations

import logging
from pathlib import Path

from gi.repository import GLib, Gtk

from .async_client import call_async
from .widgets.status_card import StatusCard

log = logging.getLogger(__name__)


# D1: Caminhos potenciais do log do daemon
LOG_PATHS = [
    Path("/tmp/recordo.daemon.log"),
    Path("/tmp/recordo.log"),
    Path.home() / ".local/share/recordo/daemon.log",
]

LOG_FILTERS = [
    ("Tudo", None),
    ("Info+", "INFO"),
    ("Warning+", "WARNING"),
    ("Error", "ERROR"),
]


class StatusPage(Gtk.Box):
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

        self.card = StatusCard()
        self.append(self.card)

        # Help footer
        help_label = Gtk.Label(xalign=0, wrap=True)
        help_label.add_css_class("dim-label")
        help_label.set_markup(
            "<small>Atalho global: <b>Super+R</b> alterna gravação · "
            "<b>Super+Shift+M</b> registra marca.\n"
            "Atualização automática a cada 1s.</small>"
        )
        help_label.set_margin_top(12)
        self.append(help_label)

        # ── D1: Logs viewer ───────────────────────────────────────────────
        logs_header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        logs_header_box.set_margin_top(20)

        logs_label = Gtk.Label(xalign=0)
        logs_label.set_markup("<b>Logs do daemon</b>")
        logs_label.set_hexpand(True)
        logs_header_box.append(logs_label)

        # Filter dropdown
        self.log_filter_combo = Gtk.DropDown.new_from_strings([f[0] for f in LOG_FILTERS])
        self.log_filter_combo.set_selected(0)
        self.log_filter_combo.set_tooltip_text("Filtrar por nível de log")
        self.log_filter_combo.connect("notify::selected", lambda *_: self._refresh_logs())
        logs_header_box.append(self.log_filter_combo)

        btn_open_log = Gtk.Button(icon_name="document-open-symbolic")
        btn_open_log.set_tooltip_text("Abrir log completo no editor padrão")
        btn_open_log.add_css_class("flat")
        btn_open_log.connect("clicked", self._on_open_log_external)
        logs_header_box.append(btn_open_log)

        btn_clear_view = Gtk.Button(icon_name="edit-clear-all-symbolic")
        btn_clear_view.set_tooltip_text("Limpar visualização (não apaga arquivo)")
        btn_clear_view.add_css_class("flat")
        btn_clear_view.connect("clicked", self._on_clear_view)
        logs_header_box.append(btn_clear_view)

        self.append(logs_header_box)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(220)
        scrolled.set_max_content_height(400)
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.add_css_class("card")

        self.log_textview = Gtk.TextView()
        self.log_textview.set_editable(False)
        self.log_textview.set_cursor_visible(False)
        self.log_textview.set_monospace(True)
        self.log_textview.set_top_margin(8)
        self.log_textview.set_bottom_margin(8)
        self.log_textview.set_left_margin(8)
        self.log_textview.set_right_margin(8)
        self.log_textview.set_wrap_mode(Gtk.WrapMode.NONE)
        scrolled.set_child(self.log_textview)

        self.append(scrolled)

        # Tracking de file size para tail incremental
        self._log_path = self._detect_log_path()
        self._log_offset = 0
        self._log_inode = None

        if self._log_path and self._log_path.exists():
            # Inicializar com últimas N linhas (não recarregar tudo)
            self._init_log_from_tail()

        # Auto refresh 1s — call assíncrona, não trava UI
        GLib.timeout_add(1000, self._refresh)
        # D1: refresh logs every 2s (mais lento que status — logs mudam menos)
        GLib.timeout_add(2000, self._refresh_logs)
        self._refresh()  # initial

    def _refresh(self) -> bool:
        call_async("status", self._on_status)
        return GLib.SOURCE_CONTINUE

    def _on_status(self, resp: dict) -> None:
        if not resp.get("ok"):
            self.card.set_offline(resp.get("error", "?"))
        else:
            self.card.update(resp)

    # ── D1: Logs viewer helpers ───────────────────────────────────────────
    @staticmethod
    def _detect_log_path() -> Path | None:
        for p in LOG_PATHS:
            if p.exists():
                return p
        return None

    def _init_log_from_tail(self) -> None:
        """Carrega últimas 200 linhas do log e seta offset para tail incremental."""
        if not self._log_path or not self._log_path.exists():
            return
        try:
            stat = self._log_path.stat()
            self._log_inode = stat.st_ino
            # Lê últimas N linhas eficientemente
            with open(self._log_path, "rb") as f:
                f.seek(0, 2)  # end
                file_size = f.tell()
                # Le últimos 50KB pra ter ~200 linhas tipicamente
                read_size = min(50 * 1024, file_size)
                f.seek(file_size - read_size)
                data = f.read().decode("utf-8", errors="ignore")
                self._log_offset = file_size
                lines = data.splitlines()[-200:]  # last 200
                self._set_log_text("\n".join(lines))
        except OSError as e:
            log.warning("falha tail log: %s", e)

    def _refresh_logs(self) -> bool:
        if not self._log_path:
            self._log_path = self._detect_log_path()
            if not self._log_path:
                return GLib.SOURCE_CONTINUE
            self._init_log_from_tail()
            return GLib.SOURCE_CONTINUE

        try:
            if not self._log_path.exists():
                return GLib.SOURCE_CONTINUE

            stat = self._log_path.stat()
            # Detect logrotate: inode mudou ou arquivo encolheu
            if stat.st_ino != self._log_inode or stat.st_size < self._log_offset:
                self._init_log_from_tail()
                return GLib.SOURCE_CONTINUE

            # Append diff
            if stat.st_size > self._log_offset:
                with open(self._log_path, "rb") as f:
                    f.seek(self._log_offset)
                    new_data = f.read().decode("utf-8", errors="ignore")
                    self._log_offset = f.tell()
                if new_data:
                    self._append_log_text(new_data)
        except OSError as e:
            log.debug("refresh logs erro: %s", e)
        return GLib.SOURCE_CONTINUE

    def _set_log_text(self, text: str) -> None:
        filtered = self._filter_text(text)
        buf = self.log_textview.get_buffer()
        buf.set_text(filtered, -1)
        self._scroll_to_bottom()

    def _append_log_text(self, text: str) -> None:
        filtered = self._filter_text(text)
        if not filtered:
            return
        buf = self.log_textview.get_buffer()
        end_iter = buf.get_end_iter()
        buf.insert(end_iter, filtered if filtered.startswith("\n") else "\n" + filtered)
        # Cap at 1000 lines to avoid unbounded growth
        line_count = buf.get_line_count()
        if line_count > 1000:
            start = buf.get_start_iter()
            cut = buf.get_iter_at_line(line_count - 800)[1]
            buf.delete(start, cut)
        self._scroll_to_bottom()

    def _filter_text(self, text: str) -> str:
        sel = self.log_filter_combo.get_selected()
        if sel < 0 or sel >= len(LOG_FILTERS):
            return text
        level = LOG_FILTERS[sel][1]
        if level is None:
            return text
        # Filtra: aceita linhas com level OU acima
        levels_order = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        try:
            min_idx = levels_order.index(level)
        except ValueError:
            return text
        accepted_levels = set(levels_order[min_idx:])

        kept = []
        for line in text.splitlines():
            line_upper = line.upper()
            if any(lvl in line_upper for lvl in accepted_levels):
                kept.append(line)
        return "\n".join(kept)

    def _scroll_to_bottom(self) -> None:
        buf = self.log_textview.get_buffer()
        end = buf.get_end_iter()
        # Idle scroll para esperar render
        GLib.idle_add(self.log_textview.scroll_to_iter, end, 0.0, False, 0.0, 0.0)

    def _on_open_log_external(self, _btn) -> None:
        if not self._log_path:
            self.window.toast("Log não encontrado")
            return
        import subprocess

        try:
            subprocess.Popen(["xdg-open", str(self._log_path)])
        except FileNotFoundError:
            self.window.toast(f"Log: {self._log_path}")

    def _on_clear_view(self, _btn) -> None:
        buf = self.log_textview.get_buffer()
        buf.set_text("", -1)
