# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Caio Hat
"""Smoke test DashboardPage."""

import pytest

pytestmark = pytest.mark.gui


def test_dashboard_constructs():
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from recordo.gui.pages.dashboard import DashboardPage

    p = DashboardPage(
        on_open_settings=lambda: None,
        on_open_models=lambda: None,
        on_open_logs=lambda: None,
        on_open_recording=lambda path: None,
    )
    assert p.get_tag() == "dashboard"
