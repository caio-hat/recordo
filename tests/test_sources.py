"""Tests for AudioSource scoring and selection."""
from __future__ import annotations

from recordo.sources import AudioSource, auto_pick, detect_active_call


class TestAudioSourceKind:
    def test_monitor_is_system(self):
        s = AudioSource("alsa_output.usb-X.monitor", "", "SUSPENDED")
        assert s.kind == "system"

    def test_input_is_mic(self):
        s = AudioSource("alsa_input.usb-X", "", "RUNNING")
        assert s.kind == "mic"

    def test_unknown(self):
        s = AudioSource("foo.bar", "", "IDLE")
        assert s.kind == "unknown"


class TestAudioSourceScore:
    def test_bluetooth_wins(self):
        bt = AudioSource("bluez_input.AA_BB.0", "", "RUNNING")
        usb = AudioSource("alsa_input.usb-Foo", "", "RUNNING")
        assert bt.score > usb.score

    def test_running_beats_suspended(self):
        a = AudioSource("alsa_input.usb-X", "", "RUNNING")
        b = AudioSource("alsa_input.usb-X", "", "SUSPENDED")
        assert a.score > b.score


class TestAutoPick:
    def test_picks_highest_scored(self):
        sources = [
            AudioSource("alsa_output.usb.monitor", "", "SUSPENDED"),         # sys, score 50
            AudioSource("bluez_output.bt.monitor", "", "RUNNING"),           # sys, score 130
            AudioSource("alsa_input.usb-cam", "", "SUSPENDED"),              # mic, score 50
            AudioSource("bluez_input.bt", "", "RUNNING"),                    # mic, score 130
        ]
        mic, sys_ = auto_pick(sources)
        assert mic == "bluez_input.bt"
        assert sys_ == "bluez_output.bt.monitor"

    def test_returns_none_when_empty(self):
        assert auto_pick([]) == (None, None)


class TestDetectActiveCall:
    def test_returns_none_when_no_outputs(self, monkeypatch):
        monkeypatch.setattr("recordo.sources.list_source_outputs", lambda: [])
        assert detect_active_call({"apps": ["zoom"]}) is None

    def test_matches_allowed_app(self, monkeypatch):
        monkeypatch.setattr(
            "recordo.sources.list_source_outputs",
            lambda: [{"app_name": "zoom", "binary": "zoom"}],
        )
        cfg = {"apps": ["zoom"], "deny_apps": []}
        assert detect_active_call(cfg) == "zoom"

    def test_deny_overrides_allow(self, monkeypatch):
        monkeypatch.setattr(
            "recordo.sources.list_source_outputs",
            lambda: [{"app_name": "firefox", "binary": "firefox"}],
        )
        cfg = {"apps": ["firefox"], "deny_apps": ["firefox"]}
        assert detect_active_call(cfg) is None

    def test_substring_match(self, monkeypatch):
        monkeypatch.setattr(
            "recordo.sources.list_source_outputs",
            lambda: [{"app_name": "Microsoft Teams (Preview)", "binary": "teams-for-linux"}],
        )
        cfg = {"apps": ["teams-for-linux"], "deny_apps": []}
        assert detect_active_call(cfg) == "Microsoft Teams (Preview)"
