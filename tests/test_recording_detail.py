# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Caio Hat
"""Smoke RecordingDetailPage."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.gui


def test_recording_detail_constructs(tmp_path: Path) -> None:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from recordo.gui.pages.recording_detail import RecordingDetailPage

    rec = tmp_path / "2026-06-01_test"
    rec.mkdir()
    (rec / "nota.md").write_text("# Test\n\nbody", encoding="utf-8")
    page = RecordingDetailPage(rec)
    assert page.get_tag() == "recording-2026-06-01_test"
