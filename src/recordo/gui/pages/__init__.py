# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Caio Hat
"""Pages — top-level views (Dashboard + sub-pages via NavigationView)."""

from .dashboard import DashboardPage
from .logs import LogsSubPage
from .models import ModelsSubPage
from .recording_detail import RecordingDetailPage
from .settings import SettingsSubPage

__all__ = [
    "DashboardPage",
    "LogsSubPage",
    "ModelsSubPage",
    "RecordingDetailPage",
    "SettingsSubPage",
]
