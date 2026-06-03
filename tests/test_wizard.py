# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Caio Hat
"""Smoke test OnboardingWizard."""

import pytest

pytestmark = pytest.mark.gui


def test_wizard_constructs():
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from recordo.gui.wizards.onboarding import OnboardingWizard

    w = OnboardingWizard(on_complete=lambda b: None)
    assert w.get_title() == "Bem-vindo ao Recordo"


def test_should_show_onboarding_default_true():
    from recordo.gui.wizards.onboarding import should_show_onboarding

    assert should_show_onboarding({}) is True
    assert should_show_onboarding({"ui": {"first_run": True}}) is True
    assert should_show_onboarding({"ui": {"first_run": False}}) is False
    assert should_show_onboarding(None) is True
