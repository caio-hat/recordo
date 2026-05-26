"""StatusCard — Adw.Bin com indicador grande + tempo decorrido."""

from __future__ import annotations

from gi.repository import Adw, Gtk


class StatusCard(Adw.Bin):
    def __init__(self):
        super().__init__()

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24, margin_top=48, margin_bottom=48)
        outer.set_halign(Gtk.Align.CENTER)
        outer.set_valign(Gtk.Align.CENTER)
        self.set_child(outer)

        # Indicador circular grande
        self.indicator = Gtk.Label()
        self.indicator.set_markup('<span size="96000">⚫</span>')
        outer.append(self.indicator)

        # Título de status
        self.title = Gtk.Label()
        self.title.set_markup('<span size="x-large" weight="bold">Idle</span>')
        outer.append(self.title)

        # Subject (se gravando)
        self.subject = Gtk.Label()
        self.subject.add_css_class("dim-label")
        outer.append(self.subject)

        # Linha info
        self.info = Gtk.Label()
        outer.append(self.info)

    def update(self, status: dict) -> None:
        if status.get("recording"):
            self.indicator.set_markup('<span size="96000" color="#e53e3e">●</span>')
            elapsed = int(status.get("elapsed_seconds", 0))
            mm, ss = divmod(elapsed, 60)
            hh, mm = divmod(mm, 60)
            timer = f"{hh:02d}:{mm:02d}:{ss:02d}" if hh else f"{mm:02d}:{ss:02d}"
            self.title.set_markup(f'<span size="x-large" weight="bold">🔴 {timer}</span>')
            self.subject.set_markup(f'<span size="large">{status.get("subject", "—")}</span>')
            segs = status.get("segments", 0)
            marks = status.get("marks", 0)
            auto = " · auto-detect" if status.get("auto_started") else ""
            self.info.set_markup(f'<span color="#888">segmentos: {segs} · marcas: {marks}{auto}</span>')
        else:
            self.indicator.set_markup('<span size="96000">⚫</span>')
            self.title.set_markup('<span size="x-large" weight="bold">Idle</span>')
            last = status.get("since_last_stop_seconds")
            if last:
                m, s = divmod(int(last), 60)
                self.subject.set_markup(
                    f'<span size="large">Última gravação encerrada há {m:02d}:{s:02d}</span>'
                )
            else:
                self.subject.set_markup('<span size="large">Daemon ativo, sem gravação</span>')
            self.info.set_text("")

    def set_offline(self, error: str) -> None:
        self.indicator.set_markup('<span size="96000" color="#888">⚠</span>')
        self.title.set_markup('<span size="x-large" weight="bold">Daemon offline</span>')
        self.subject.set_text(error)
        self.info.set_text("")
