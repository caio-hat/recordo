"""Tests for Phase B: detect_meeting multi-signal + popup persistent config."""

from __future__ import annotations

from unittest.mock import patch

from recordo.sources import (
    DEFAULT_MEETING_APPS,
    MeetingSignal,
    detect_meeting,
)


class TestDetectMeeting:
    """B2: multi-signal meeting detection."""

    def test_no_signals_returns_not_in_meeting(self):
        with patch("recordo.sources.list_source_outputs", return_value=[]):
            with patch("recordo.sources.list_sink_inputs", return_value=[]):
                sig = detect_meeting()
        assert sig.in_meeting is False
        assert sig.confidence == 0.0
        assert sig.signals_active == []
        assert sig.apps_detected == []

    def test_mic_used_by_firefox_running(self):
        """Sig1: source-output RUNNING (firefox) → conf 0.9, in_meeting True."""
        source_outputs = [
            {
                "state": "RUNNING",
                "binary": "firefox",
                "app_name": "Firefox",
                "corked": False,
            }
        ]
        with patch("recordo.sources.list_source_outputs", return_value=source_outputs):
            with patch("recordo.sources.list_sink_inputs", return_value=[]):
                sig = detect_meeting()
        assert sig.in_meeting is True
        assert sig.confidence == 0.9
        assert "firefox" in sig.apps_detected
        assert any("mic_used_by" in s for s in sig.signals_active)

    def test_recordo_excluded_from_signals(self):
        """Sig1: nosso próprio recording (ffmpeg/recordo) NÃO deve disparar."""
        source_outputs = [
            {"state": "RUNNING", "binary": "ffmpeg", "app_name": "ffmpeg", "corked": False},
            {"state": "RUNNING", "binary": "python3", "app_name": "Recordo", "corked": False},
        ]
        with patch("recordo.sources.list_source_outputs", return_value=source_outputs):
            with patch("recordo.sources.list_sink_inputs", return_value=[]):
                sig = detect_meeting()
        assert sig.in_meeting is False

    def test_corked_state_ignored(self):
        """source-output CORKED (paused) não deve disparar."""
        source_outputs = [
            {"state": "RUNNING", "binary": "firefox", "corked": True},
        ]
        with patch("recordo.sources.list_source_outputs", return_value=source_outputs):
            with patch("recordo.sources.list_sink_inputs", return_value=[]):
                sig = detect_meeting()
        assert sig.in_meeting is False

    def test_idle_state_ignored(self):
        """source-output IDLE (não RUNNING) não deve disparar."""
        source_outputs = [
            {"state": "IDLE", "binary": "firefox", "corked": False},
        ]
        with patch("recordo.sources.list_source_outputs", return_value=source_outputs):
            with patch("recordo.sources.list_sink_inputs", return_value=[]):
                sig = detect_meeting()
        assert sig.in_meeting is False

    def test_speaker_audio_from_zoom(self):
        """Sig2: sink-input do zoom RUNNING + volume>0 → conf 0.7."""
        sink_inputs = [
            {
                "state": "RUNNING",
                "binary": "zoom",
                "app_name": "Zoom",
                "corked": False,
                "volume_pct": 80,
            }
        ]
        with patch("recordo.sources.list_source_outputs", return_value=[]):
            with patch("recordo.sources.list_sink_inputs", return_value=sink_inputs):
                sig = detect_meeting()
        assert sig.in_meeting is True
        assert sig.confidence == 0.7
        assert "zoom" in sig.apps_detected

    def test_speaker_muted_volume_zero(self):
        """sink-input com volume=0 NÃO deve disparar Sig2 (muted)."""
        sink_inputs = [
            {
                "state": "RUNNING",
                "binary": "zoom",
                "corked": False,
                "volume_pct": 0,
            }
        ]
        with patch("recordo.sources.list_source_outputs", return_value=[]):
            with patch("recordo.sources.list_sink_inputs", return_value=sink_inputs):
                sig = detect_meeting()
        assert sig.in_meeting is False

    def test_non_meeting_app_speaker_ignored(self):
        """sink-input de app fora da whitelist não deve disparar Sig2."""
        sink_inputs = [
            {
                "state": "RUNNING",
                "binary": "spotify",
                "app_name": "Spotify",
                "corked": False,
                "volume_pct": 100,
            }
        ]
        with patch("recordo.sources.list_source_outputs", return_value=[]):
            with patch("recordo.sources.list_sink_inputs", return_value=sink_inputs):
                sig = detect_meeting()
        # Spotify não está na whitelist → Sig2 não dispara
        assert sig.in_meeting is False

    def test_multi_signal_boosts_confidence(self):
        """Múltiplos sinais aumentam confidence."""
        source_outputs = [{"state": "RUNNING", "binary": "firefox", "corked": False}]
        sink_inputs = [{"state": "RUNNING", "binary": "zoom", "corked": False, "volume_pct": 50}]
        with patch("recordo.sources.list_source_outputs", return_value=source_outputs):
            with patch("recordo.sources.list_sink_inputs", return_value=sink_inputs):
                sig = detect_meeting()
        # 2 sinais → conf max(0.9, 0.7) + 0.1 = 1.0
        assert sig.in_meeting is True
        assert sig.confidence == 1.0
        assert len(sig.signals_active) == 2

    def test_custom_meeting_apps_overrides_default(self):
        """cfg['meeting_apps'] custom substitui default."""
        sink_inputs = [
            {
                "state": "RUNNING",
                "binary": "myapp",
                "corked": False,
                "volume_pct": 50,
            }
        ]
        with patch("recordo.sources.list_source_outputs", return_value=[]):
            with patch("recordo.sources.list_sink_inputs", return_value=sink_inputs):
                # Default: myapp não está na lista
                sig_default = detect_meeting()
                # Custom: agora myapp está
                sig_custom = detect_meeting({"meeting_apps": ["myapp"]})
        assert sig_default.in_meeting is False
        assert sig_custom.in_meeting is True


class TestMeetingSignalDataclass:
    def test_meeting_signal_is_dataclass(self):
        sig = MeetingSignal(
            in_meeting=True,
            confidence=0.8,
            reason="test",
            signals_active=["x"],
            apps_detected=["y"],
        )
        assert sig.in_meeting is True
        assert sig.confidence == 0.8


class TestDefaultMeetingApps:
    def test_includes_major_meeting_apps(self):
        all_apps_lower = [a.lower() for a in DEFAULT_MEETING_APPS]
        for must_have in [
            "teams-for-linux",
            "zoom",
            "slack",
            "discord",
            "firefox",
            "google-chrome",
            "chromium",
        ]:
            assert must_have in all_apps_lower, f"missing: {must_have}"

    def test_count_reasonable(self):
        assert len(DEFAULT_MEETING_APPS) > 30
        assert len(DEFAULT_MEETING_APPS) < 100
