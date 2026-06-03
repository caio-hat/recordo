"""Testes para gui/molecules/."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gui


def test_molecules_imports():
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from recordo.gui.molecules import Card, ConfirmDialog, EmptyState, InfoDialog

    assert all([Card, EmptyState, InfoDialog, ConfirmDialog])


def test_card_default_variant():
    from recordo.gui.molecules import Card

    c = Card()
    classes = c.get_css_classes()
    assert "recordo-card" in classes


def test_card_warning_variant():
    from recordo.gui.molecules import Card

    c = Card(variant="warning")
    classes = c.get_css_classes()
    assert "recordo-card" in classes
    assert "warning" in classes


def test_card_set_variant_swaps():
    from recordo.gui.molecules import Card

    c = Card(variant="warning")
    c.set_variant("success")
    classes = c.get_css_classes()
    assert "warning" not in classes
    assert "success" in classes


def test_empty_state_renders():
    from recordo.gui.molecules import EmptyState

    e = EmptyState(
        icon="folder-symbolic",
        title="Sem gravações",
        description="Aperte Super+R",
        action_label="Gravar",
        on_action=lambda: None,
    )
    assert "recordo-empty-state" in e.get_css_classes()


def test_info_dialog_escape():
    from recordo.gui.molecules import InfoDialog

    assert "&lt;script&gt;" == InfoDialog.escape("<script>")
