# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Caio Hat
"""Testes para gui/organisms/."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gui


def test_organisms_imports():
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from recordo.gui.organisms import HardwareCard, MarkdownView, RecordingCard

    assert all([HardwareCard, RecordingCard, MarkdownView])


def test_hardware_card_renders():
    from recordo.gui.organisms import HardwareCard

    c = HardwareCard()
    assert c._content_box.get_first_child() is not None


def test_recording_card_with_existing_dir(tmp_path):
    from recordo.gui.organisms import RecordingCard

    rec_dir = tmp_path / "2026-06-01_test_meeting"
    rec_dir.mkdir()
    (rec_dir / "nota.md").write_text("---\nduration_min: 12.5\n---\n# Test", encoding="utf-8")
    (rec_dir / "transcricao.txt").write_text("hello", encoding="utf-8")
    card = RecordingCard(rec_dir)
    assert "recordo-card" in card.get_css_classes()


def test_markdown_view_handles_missing_webkit_gracefully():
    from recordo.gui.organisms import MarkdownView

    mv = MarkdownView()
    assert mv is not None
