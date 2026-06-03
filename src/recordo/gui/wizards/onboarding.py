# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Caio Hat
"""OnboardingWizard — first-run guided setup (3 steps).

Mostrado quando config.first_run=True. Após completar/pular, salva
first_run=False e o app abre Dashboard normalmente.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from ...config import load_config, save_config
from ...hardware import HardwareReport, probe, recommend_backends
from ..atoms import ActionButton, Caption, Heading
from ..molecules import Card

log = logging.getLogger(__name__)


class OnboardingWizard(Adw.Window):
    """Window modal 3-step. Emite callback `on_complete(chosen_backend)` ao finalizar.

    Args:
        on_complete: callback chamado com nome do backend escolhido (ou None se pulou)
        parent: janela pai para modalidade
    """

    def __init__(
        self,
        *,
        on_complete: Callable[[str | None], None] | None = None,
        parent: Gtk.Window | None = None,
    ):
        super().__init__()
        self.set_title("Bem-vindo ao Recordo")
        self.set_default_size(560, 600)
        self.set_modal(True)
        if parent is not None:
            self.set_transient_for(parent)
        self._on_complete = on_complete
        self._chosen_backend: str | None = "whisper"
        self._report: HardwareReport | None = None

        toolbar = Adw.ToolbarView()
        self.set_content(toolbar)
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)
        toolbar.add_top_bar(header)

        self._carousel = Adw.Carousel()
        self._carousel.set_allow_long_swipes(False)
        self._carousel.set_allow_scroll_wheel(False)
        self._carousel.set_hexpand(True)
        self._carousel.set_vexpand(True)
        toolbar.set_content(self._carousel)

        self._carousel.append(self._build_step_welcome())
        self._carousel.append(self._build_step_hardware())
        self._carousel.append(self._build_step_finish())

        # Bottom bar: dots + botões
        bottom = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            margin_top=8,
            margin_bottom=12,
            margin_start=24,
            margin_end=24,
            spacing=8,
        )
        toolbar.add_bottom_bar(bottom)

        self._dots = Adw.CarouselIndicatorDots()
        self._dots.set_carousel(self._carousel)
        self._dots.set_halign(Gtk.Align.START)
        bottom.append(self._dots)
        bottom.append(Gtk.Box(hexpand=True))

        self._btn_skip = ActionButton("Pular tudo", variant="flat", on_click=self._on_skip)
        bottom.append(self._btn_skip)
        self._btn_back = ActionButton("← Voltar", variant="flat", on_click=self._on_back)
        bottom.append(self._btn_back)
        self._btn_next = ActionButton("Próximo →", variant="primary", on_click=self._on_next)
        bottom.append(self._btn_next)
        self._btn_finish = ActionButton("Concluir", variant="primary", on_click=self._on_finish)
        bottom.append(self._btn_finish)

        self._update_buttons()
        self._carousel.connect("page-changed", self._on_page_changed)

    # ── Step builders ───────────────────────────────────────────────────────

    def _build_step_welcome(self) -> Gtk.Widget:
        wrap = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=20,
            margin_top=32,
            margin_bottom=16,
            margin_start=32,
            margin_end=32,
            halign=Gtk.Align.CENTER,
            valign=Gtk.Align.CENTER,
        )
        img = Gtk.Image.new_from_icon_name("audio-input-microphone-symbolic")
        img.set_pixel_size(72)
        img.set_halign(Gtk.Align.CENTER)
        wrap.append(img)
        wrap.append(Heading("Bem-vindo ao Recordo", level=1))
        cap = Caption("Grave reuniões e tenha resumos automaticamente. Vamos configurar em 3 passos.")
        cap.set_halign(Gtk.Align.CENTER)
        cap.set_max_width_chars(50)
        wrap.append(cap)
        wrap.append(Gtk.Separator(margin_top=8, margin_bottom=8))
        wrap.append(Heading("Escolha o motor de transcrição", level=2))

        grp = Adw.PreferencesGroup()
        wrap.append(grp)

        self._radio_whisper = Gtk.CheckButton(label="Whisper — universal, alta qualidade (recomendado)")
        self._radio_whisper.set_active(True)
        self._radio_parakeet = Gtk.CheckButton(label="Parakeet ONNX — rápido, 25 idiomas (PT incluso)")
        self._radio_parakeet.set_group(self._radio_whisper)
        self._radio_cohere = Gtk.CheckButton(label="Cohere API — cloud, sem download (precisa API key)")
        self._radio_cohere.set_group(self._radio_whisper)

        for radio, value in [
            (self._radio_whisper, "whisper"),
            (self._radio_parakeet, "parakeet"),
            (self._radio_cohere, "cohere"),
        ]:
            row = Adw.ActionRow()
            row.set_title(radio.get_label() or "")
            row.add_prefix(radio)
            row.set_activatable_widget(radio)
            grp.add(row)
            radio.connect("toggled", self._on_radio_toggled, value)

        return wrap

    def _on_radio_toggled(self, widget: Gtk.CheckButton, value: str) -> None:
        if widget.get_active():
            self._chosen_backend = value

    def _build_step_hardware(self) -> Gtk.Widget:
        wrap = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=16,
            margin_top=24,
            margin_bottom=16,
            margin_start=24,
            margin_end=24,
        )
        wrap.append(Heading("Seu hardware", level=1))
        wrap.append(Caption("Detectamos os recursos da sua máquina. Vamos sugerir o melhor modelo."))

        from ..organisms import HardwareCard

        wrap.append(HardwareCard())

        self._reco_card = Card(variant="success", spacing=8)
        self._reco_card.set_margin_top(8)
        self._reco_card.append(Heading("Recomendação", level=3))
        self._reco_label = Caption("...")
        self._reco_card.append(self._reco_label)
        wrap.append(self._reco_card)

        self._refresh_reco()
        return wrap

    def _refresh_reco(self) -> None:
        try:
            self._report = probe()
            recos = recommend_backends(report=self._report)
            viable = [r for r in recos if r.viable]
            if viable:
                top = viable[0]
                self._reco_label.set_text(f"→ {top.backend} ({top.reason})")
            else:
                self._reco_label.set_text("Nenhum backend local cabe na memória livre. Use Cohere API.")
        except Exception:
            log.exception("refresh_reco falhou")
            self._reco_label.set_text("Não foi possível detectar o hardware.")

    def _build_step_finish(self) -> Gtk.Widget:
        wrap = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=20,
            margin_top=32,
            margin_bottom=16,
            margin_start=32,
            margin_end=32,
            halign=Gtk.Align.CENTER,
            valign=Gtk.Align.CENTER,
        )
        img = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
        img.set_pixel_size(64)
        img.set_halign(Gtk.Align.CENTER)
        wrap.append(img)
        wrap.append(Heading("Tudo pronto!", level=1))
        cap = Caption(
            "Você pode baixar o modelo escolhido agora ou depois pelo menu Modelos. Atalhos importantes:"
        )
        cap.set_halign(Gtk.Align.CENTER)
        cap.set_max_width_chars(50)
        wrap.append(cap)

        atalhos = Card(variant="default", spacing=4)
        atalhos.append(Caption("• Super+R — Iniciar/parar gravação"))
        atalhos.append(Caption("• Super+Shift+M — Marcar momento"))
        wrap.append(atalhos)
        return wrap

    # ── Navigation ──────────────────────────────────────────────────────────

    def _current_step(self) -> int:
        return int(self._carousel.get_position())

    def _on_page_changed(self, *_: object) -> None:
        self._update_buttons()
        if self._current_step() == 1:
            self._refresh_reco()

    def _update_buttons(self) -> None:
        step = self._current_step()
        last = self._carousel.get_n_pages() - 1
        self._btn_back.set_visible(step > 0)
        self._btn_next.set_visible(step < last)
        self._btn_finish.set_visible(step >= last)
        self._btn_skip.set_visible(step < last)

    def _on_next(self) -> None:
        step = self._current_step()
        if step < self._carousel.get_n_pages() - 1:
            self._carousel.scroll_to(self._carousel.get_nth_page(step + 1), True)

    def _on_back(self) -> None:
        step = self._current_step()
        if step > 0:
            self._carousel.scroll_to(self._carousel.get_nth_page(step - 1), True)

    def _on_skip(self) -> None:
        self._save_first_run_done()
        if self._on_complete:
            self._on_complete(None)
        self.close()

    def _on_finish(self) -> None:
        self._save_first_run_done()
        if self._on_complete:
            self._on_complete(self._chosen_backend)
        self.close()

    # ── Persistence ─────────────────────────────────────────────────────────

    def _save_first_run_done(self) -> None:
        try:
            cfg = load_config()
            cfg.setdefault("ui", {})["first_run"] = False
            if self._chosen_backend:
                cfg.setdefault("transcriber", {})["backend"] = self._chosen_backend
            save_config(cfg)
        except Exception:
            log.exception("falha ao salvar first_run=False")


def should_show_onboarding(cfg: dict | None) -> bool:
    """True se config indica primeira execução."""
    ui = cfg.get("ui", {}) if cfg else {}
    return bool(ui.get("first_run", True))
