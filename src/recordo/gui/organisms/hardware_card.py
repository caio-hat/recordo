# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Caio Hat
"""HardwareCard — mostra RAM/CPU/GPU detectados + recomendação de backend."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from ...hardware import HardwareReport, format_size_mb, probe
from ..atoms import Caption, Heading, StatusBadge
from ..molecules import Card


class HardwareCard(Card):
    """Mostra resumo do hardware atual + qual backend recomendado.

    Auto-refresh: tem método refresh() que re-probe e re-renderiza.
    """

    def __init__(self, *, on_open_models=None):
        super().__init__(variant="default", spacing=12)
        self._on_open_models = on_open_models
        self._content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.append(self._content_box)
        self.refresh()

    def refresh(self) -> None:
        """Re-probe hardware e re-renderiza o card."""
        while self._content_box.get_first_child() is not None:
            self._content_box.remove(self._content_box.get_first_child())

        report: HardwareReport = probe()

        # Header
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.append(Heading("Sistema", level=2))
        header.append(Gtk.Box(hexpand=True))  # spacer
        avail_pct = (report.memory.available_mb / max(1, report.memory.total_mb)) * 100
        if avail_pct < 25:
            badge = StatusBadge("warning", "Memória baixa")
        elif avail_pct < 50:
            badge = StatusBadge("info", "Memória ok")
        else:
            badge = StatusBadge("success", "Memória livre")
        header.append(badge)
        self._content_box.append(header)

        # Info lines
        ram_text = (
            f"🧮 Memória: {format_size_mb(report.memory.available_mb)} livres"
            f" de {format_size_mb(report.memory.total_mb)}"
        )
        cpu_text = (
            f"⚡ CPU: {report.cpu.model_name or 'desconhecida'}"
            f" · {report.cpu.physical_cores} núcleos / {report.cpu.logical_cores} threads"
        )
        self._content_box.append(Caption(ram_text))
        self._content_box.append(Caption(cpu_text))
        if report.gpus:
            for g in report.gpus:
                gpu_text = f"🎮 GPU {g.vendor.upper()}: {g.model[:60]}"
                if g.has_cuda:
                    gpu_text += " · CUDA"
                if g.has_rocm:
                    gpu_text += " · ROCm"
                self._content_box.append(Caption(gpu_text))
        else:
            self._content_box.append(Caption("🎮 GPU: não detectada (CPU only)"))
