# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Caio Hat
"""Testes para gui/atoms/. Requer xvfb (marker gui)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gui


def test_atoms_imports():
    import gi

    gi.require_version("Gtk", "4.0")
    from recordo.gui.atoms import ActionButton, Heading, StatusBadge

    assert StatusBadge is not None
    assert Heading is not None
    assert ActionButton is not None


def test_status_badge_applies_classes():
    from recordo.gui.atoms import StatusBadge

    b = StatusBadge("success", "OK")
    classes = b.get_css_classes()
    assert "recordo-status-badge" in classes
    assert "success" in classes


def test_status_badge_set_status_swaps_variant():
    from recordo.gui.atoms import StatusBadge

    b = StatusBadge("success", "OK")
    b.set_status("error", "Falha")
    classes = b.get_css_classes()
    assert "success" not in classes
    assert "error" in classes
    assert b.get_text() == "Falha"


def test_heading_levels():
    from recordo.gui.atoms import Heading

    h1 = Heading("Título", level=1)
    h2 = Heading("Seção", level=2)
    h3 = Heading("Sub", level=3)
    assert "recordo-heading-1" in h1.get_css_classes()
    assert "recordo-heading-2" in h2.get_css_classes()
    assert "recordo-heading-3" in h3.get_css_classes()


def test_action_button_variants():
    from recordo.gui.atoms import ActionButton

    primary = ActionButton("Salvar", variant="primary")
    danger = ActionButton("Apagar", variant="danger")
    flat = ActionButton("Cancelar", variant="flat")
    assert "suggested-action" in primary.get_css_classes()
    assert "destructive-action" in danger.get_css_classes()
    assert "flat" in flat.get_css_classes()
