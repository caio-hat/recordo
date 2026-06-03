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

# Backend choices: (id, title, subtitle)
_BACKEND_CHOICES = [
    (
        "whisper",
        "Whisper",
        "Universal · alta qualidade · funciona offline (recomendado)",
    ),
    (
        "parakeet",
        "Parakeet ONNX",
        "Rápido · 25 idiomas (PT incluso) · ~2 GB RAM · funciona offline",
    ),
    (
        "cohere",
        "Cohere (cloud)",
        "Sem download · precisa de API key · áudio enviado para cloud",
    ),
]


class OnboardingWizard(Adw.Window):
    """Window modal 3-step. Emite callback `on_complete(chosen_backend)` ao finalizar.

    Args:
        on_complete: callback chamado com nome do backend escolhido (None se pulou)
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
        self.set_default_size(640, 720)
        self.set_size_request(520, 480)
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

        # Carousel principal — cada step é envolto em Gtk.ScrolledWindow para
        # garantir que conteúdo nunca colapsa o bottom bar em telas pequenas.
        self._carousel = Adw.Carousel()
        self._carousel.set_allow_long_swipes(False)
        self._carousel.set_allow_scroll_wheel(False)
        self._carousel.set_hexpand(True)
        self._carousel.set_vexpand(True)
        toolbar.set_content(self._carousel)

        self._carousel.append(self._wrap_scrolled(self._build_step_welcome()))
        self._carousel.append(self._wrap_scrolled(self._build_step_hardware()))
        self._carousel.append(self._wrap_scrolled(self._build_step_finish()))

        # Bottom bar: dots + botões (sempre visível)
        bottom = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            margin_top=12,
            margin_bottom=12,
            margin_start=18,
            margin_end=18,
            spacing=8,
        )
        toolbar.add_bottom_bar(bottom)

        self._dots = Adw.CarouselIndicatorDots()
        self._dots.set_carousel(self._carousel)
        self._dots.set_halign(Gtk.Align.START)
        self._dots.set_valign(Gtk.Align.CENTER)
        bottom.append(self._dots)
        bottom.append(Gtk.Box(hexpand=True))

        self._btn_skip = ActionButton("Pular", variant="flat", on_click=self._on_skip)
        bottom.append(self._btn_skip)
        self._btn_back = ActionButton("Voltar", variant="flat", on_click=self._on_back)
        bottom.append(self._btn_back)
        self._btn_next = ActionButton("Avançar", variant="primary", on_click=self._on_next)
        bottom.append(self._btn_next)
        self._btn_finish = ActionButton("Concluir", variant="primary", on_click=self._on_finish)
        bottom.append(self._btn_finish)

        self._update_buttons()
        self._carousel.connect("page-changed", self._on_page_changed)

    # ── Helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _wrap_scrolled(content: Gtk.Widget) -> Gtk.Widget:
        """Envolve cada step em ScrolledWindow para garantir que bottom bar
        fique sempre visível mesmo em telas pequenas."""
        sw = Gtk.ScrolledWindow()
        sw.set_hexpand(True)
        sw.set_vexpand(True)
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.set_propagate_natural_height(False)
        clamp = Adw.Clamp(maximum_size=520, tightening_threshold=480)
        clamp.set_child(content)
        sw.set_child(clamp)
        return sw

    # ── Step builders ───────────────────────────────────────────────────────

    def _build_step_welcome(self) -> Gtk.Widget:
        wrap = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=18,
            margin_top=32,
            margin_bottom=24,
            margin_start=24,
            margin_end=24,
        )

        # Hero icon centered
        img = Gtk.Image.new_from_icon_name("audio-input-microphone-symbolic")
        img.set_pixel_size(64)
        img.set_halign(Gtk.Align.CENTER)
        wrap.append(img)

        title = Heading("Bem-vindo ao Recordo", level=1)
        title.set_halign(Gtk.Align.CENTER)
        title.set_xalign(0.5)
        wrap.append(title)

        subtitle = Caption("Grave reuniões e tenha resumos automaticamente. Vamos configurar em 3 passos.")
        subtitle.set_halign(Gtk.Align.CENTER)
        subtitle.set_xalign(0.5)
        subtitle.set_max_width_chars(50)
        subtitle.set_justify(Gtk.Justification.CENTER)
        wrap.append(subtitle)

        sep = Gtk.Separator(margin_top=8, margin_bottom=8)
        wrap.append(sep)

        section_title = Heading("Escolha o motor de transcrição", level=2)
        wrap.append(section_title)

        # PreferencesGroup com radio rows. CheckButton SEM label próprio
        # (label vai no Adw.ActionRow.title — evita duplicação visual).
        grp = Adw.PreferencesGroup()
        wrap.append(grp)

        first_radio: Gtk.CheckButton | None = None
        self._radios: dict[str, Gtk.CheckButton] = {}

        for choice_id, choice_title, choice_subtitle in _BACKEND_CHOICES:
            radio = Gtk.CheckButton()
            if first_radio is None:
                first_radio = radio
                radio.set_active(True)
            else:
                radio.set_group(first_radio)
            self._radios[choice_id] = radio

            row = Adw.ActionRow()
            row.set_title(choice_title)
            row.set_subtitle(choice_subtitle)
            row.add_prefix(radio)
            row.set_activatable_widget(radio)
            grp.add(row)

            radio.connect("toggled", self._on_radio_toggled, choice_id)

        return wrap

    def _on_radio_toggled(self, widget: Gtk.CheckButton, value: str) -> None:
        if widget.get_active():
            self._chosen_backend = value

    def _build_step_hardware(self) -> Gtk.Widget:
        wrap = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=16,
            margin_top=32,
            margin_bottom=24,
            margin_start=24,
            margin_end=24,
        )

        title = Heading("Seu hardware", level=1)
        title.set_halign(Gtk.Align.CENTER)
        title.set_xalign(0.5)
        wrap.append(title)

        subtitle = Caption("Detectamos os recursos da sua máquina e sugerimos o melhor modelo.")
        subtitle.set_halign(Gtk.Align.CENTER)
        subtitle.set_xalign(0.5)
        subtitle.set_max_width_chars(50)
        subtitle.set_justify(Gtk.Justification.CENTER)
        wrap.append(subtitle)

        from ..organisms import HardwareCard

        wrap.append(HardwareCard())

        self._reco_card = Card(variant="success", spacing=8)
        self._reco_card.append(Heading("Recomendação para sua máquina", level=3))
        self._reco_label = Caption("Detectando…")
        self._reco_label.set_wrap(True)
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
                self._reco_label.set_text(f"{top.backend}\n{top.reason}")
            else:
                self._reco_label.set_text(
                    "Nenhum backend local cabe na memória disponível. "
                    "Considere usar Cohere (cloud) ou liberar memória."
                )
        except Exception:
            log.exception("refresh_reco falhou")
            self._reco_label.set_text("Não foi possível detectar o hardware.")

    def _build_step_finish(self) -> Gtk.Widget:
        wrap = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=18,
            margin_top=32,
            margin_bottom=24,
            margin_start=24,
            margin_end=24,
        )

        img = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
        img.set_pixel_size(56)
        img.set_halign(Gtk.Align.CENTER)
        wrap.append(img)

        title = Heading("Tudo pronto!", level=1)
        title.set_halign(Gtk.Align.CENTER)
        title.set_xalign(0.5)
        wrap.append(title)

        subtitle = Caption("Você pode baixar o modelo escolhido agora ou depois pelo menu Modelos.")
        subtitle.set_halign(Gtk.Align.CENTER)
        subtitle.set_xalign(0.5)
        subtitle.set_max_width_chars(50)
        subtitle.set_justify(Gtk.Justification.CENTER)
        wrap.append(subtitle)

        atalhos = Card(variant="default", spacing=6)
        atalhos.append(Heading("Atalhos importantes", level=3))
        atalhos.append(Caption("Super + R — iniciar / parar gravação"))
        atalhos.append(Caption("Super + Shift + M — marcar momento durante gravação"))
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
