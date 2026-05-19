"""Tests for subject extraction heuristics."""

from __future__ import annotations

from recordo.subject import detect_subject_from_title, safe_subject


class TestSafeSubject:
    def test_alphanumeric(self):
        assert safe_subject("Reunião X") == "Reunião_X"

    def test_strips_special(self):
        # "/" e "!" removidos, espaços viram underscore (e múltiplos collapsem)
        assert safe_subject("Daily / Sync!") == "Daily_Sync"

    def test_empty_fallback(self):
        assert safe_subject("") == "Gravacao"
        assert safe_subject("   ") == "Gravacao"

    def test_truncates_long(self):
        long = "a" * 200
        assert len(safe_subject(long)) <= 80

    def test_collapses_spaces(self):
        assert safe_subject("Daily    Sync") == "Daily_Sync"


class TestDetectSubjectFromTitle:
    def test_teams_pipe(self):
        assert detect_subject_from_title("Sales Sync | Microsoft Teams") == "Sales_Sync"

    def test_teams_dash(self):
        assert detect_subject_from_title("1on1 Caio - Microsoft Teams") == "1on1_Caio"

    def test_teams_pt(self):
        assert detect_subject_from_title("Reunião em Planejamento Q3 | algo") == "Planejamento_Q3"

    def test_meet(self):
        assert detect_subject_from_title("Daily Standup - Google Meet") == "Daily_Standup"

    def test_zoom(self):
        assert detect_subject_from_title("Diretoria Zoom Meeting") == "Diretoria"

    def test_slack_huddle(self):
        assert detect_subject_from_title("Huddle in #engineering") == "engineering"

    def test_slack_app(self):
        assert detect_subject_from_title("Random - Slack") == "Random"

    def test_discord(self):
        assert detect_subject_from_title("Gaming - Discord") == "Gaming"

    def test_unknown_title_fallback_timestamp(self):
        out = detect_subject_from_title("Notepad - random title")
        assert out.startswith("call_")

    def test_empty_fallback(self):
        out = detect_subject_from_title("")
        assert out.startswith("call_")
