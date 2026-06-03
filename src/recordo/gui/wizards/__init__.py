# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Caio Hat
"""Wizards — first-run setup and similar guided flows."""

from .onboarding import OnboardingWizard, should_show_onboarding

__all__ = ["OnboardingWizard", "should_show_onboarding"]
