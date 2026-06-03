# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Caio Hat
"""Testes para gui/atoms/progress."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gui


def test_progress_imports():
    import gi

    gi.require_version("Gtk", "4.0")
    from recordo.gui.atoms.progress import (
        IndeterminatePulse,
        LinearBar,
        Spinner,
        StepProgress,
    )

    assert all([LinearBar, Spinner, StepProgress, IndeterminatePulse])


def test_linear_bar_set_progress_clamps():
    from recordo.gui.atoms.progress import LinearBar

    bar = LinearBar()
    bar.set_progress(1.5, "over")
    assert bar.get_fraction() == 1.0
    bar.set_progress(-0.5, "under")
    assert bar.get_fraction() == 0.0
    bar.set_progress(0.5, "mid")
    assert bar.get_fraction() == 0.5


def test_step_progress_active_class():
    from recordo.gui.atoms.progress import StepProgress

    sp = StepProgress(["A", "B", "C"])
    sp.set_active(1)
    chips = []
    chip = sp.get_first_child()
    while chip is not None:
        chips.append(chip)
        chip = chip.get_next_sibling()
    assert "active" in chips[1].get_css_classes()
    assert "active" not in chips[0].get_css_classes()


def test_step_progress_done_persists():
    from recordo.gui.atoms.progress import StepProgress

    sp = StepProgress(["A", "B"])
    sp.set_done(0)
    chips = []
    chip = sp.get_first_child()
    while chip is not None:
        chips.append(chip)
        chip = chip.get_next_sibling()
    assert "done" in chips[0].get_css_classes()


def test_indeterminate_pulse_start_stop():
    from recordo.gui.atoms.progress import IndeterminatePulse

    p = IndeterminatePulse("Carregando")
    p.start()
    assert p._pulse_source_id is not None
    p.stop()
    assert p._pulse_source_id is None
