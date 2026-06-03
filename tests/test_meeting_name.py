# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Caio Hat
"""Testes para meeting_name."""

from __future__ import annotations

from recordo.meeting_name import (
    _match_title,
    extract_meeting_name,
    sanitize_filename,
)


class TestSanitize:
    def test_basic_lowercase(self):
        assert sanitize_filename("Reunião de Plataforma") == "reuniao_de_plataforma"

    def test_strips_punctuation(self):
        assert sanitize_filename("Daniel's standup") == "daniels_standup"

    def test_max_len(self):
        s = sanitize_filename("a" * 100, max_len=20)
        assert len(s) <= 20

    def test_underscore_collapse(self):
        assert sanitize_filename("a   b   c") == "a_b_c"

    def test_empty_returns_empty(self):
        assert sanitize_filename("") == ""


class TestPatterns:
    def test_teams_meeting(self):
        m = _match_title("Reunião de Plataforma | Microsoft Teams")
        assert m.app == "teams"
        assert m.extracted == "Reunião de Plataforma"

    def test_zoom_personal_room(self):
        m = _match_title("John's Personal Meeting Room - Zoom")
        assert m.app == "zoom"
        assert m.extracted == "John"

    def test_meet_browser_tab(self):
        m = _match_title("Daily Standup - Google Meet")
        assert m.app == "meet"
        assert m.extracted == "Daily Standup"

    def test_unknown_returns_unknown(self):
        m = _match_title("Some random window")
        assert m.app == "unknown"
        assert m.extracted is None


class TestExtract:
    def test_extract_with_titles_explicit(self):
        titles = ["Firefox", "Daily | Microsoft Teams", "Terminal"]
        result = extract_meeting_name(titles=titles)
        assert result == "daily"

    def test_extract_prefers_detected_app(self):
        titles = [
            "Random Slack | Slack",
            "Important meeting | Microsoft Teams",
        ]
        result = extract_meeting_name(detected_app="teams", titles=titles)
        assert result == "important_meeting"

    def test_extract_no_match_returns_none(self):
        titles = ["Firefox", "Terminal"]
        result = extract_meeting_name(titles=titles)
        assert result is None

    def test_extract_empty_titles(self):
        result = extract_meeting_name(titles=[])
        assert result is None
