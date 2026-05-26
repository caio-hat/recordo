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
            AudioSource("alsa_output.usb.monitor", "", "SUSPENDED"),  # sys, score 50
            AudioSource("bluez_output.bt.monitor", "", "RUNNING"),  # sys, score 130
            AudioSource("alsa_input.usb-cam", "", "SUSPENDED"),  # mic, score 50
            AudioSource("bluez_input.bt", "", "RUNNING"),  # mic, score 130
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
        # binary bate exato com allow set; loop testa app_name primeiro mas falha,
        # depois binary que casa → retorna binary
        monkeypatch.setattr(
            "recordo.sources.list_source_outputs",
            lambda: [{"app_name": "Microsoft Teams (Preview)", "binary": "teams-for-linux"}],
        )
        cfg = {"apps": ["teams-for-linux"], "deny_apps": []}
        assert detect_active_call(cfg) == "teams-for-linux"


class TestRmsDbfs:
    """Testa o cálculo RMS s16le → dBFS (lógica pura, sem subprocess)."""

    def test_silence_returns_low_db(self):
        from recordo.sources import _rms_dbfs_s16le

        # 1s de silêncio @16kHz mono
        data = b"\x00\x00" * 16000
        db = _rms_dbfs_s16le(data)
        assert db <= -60  # silêncio absoluto

    def test_full_scale_sine_near_zero_db(self):
        import math
        import struct

        from recordo.sources import _rms_dbfs_s16le

        # tom puro a 440Hz, amplitude 0.7 do full-scale → ~-3 dBFS
        rate = 16000
        amp = int(32767 * 0.7)
        samples = [
            int(amp * math.sin(2 * math.pi * 440 * i / rate))
            for i in range(rate)  # 1 segundo
        ]
        data = b"".join(struct.pack("<h", s) for s in samples)
        db = _rms_dbfs_s16le(data)
        # senoide RMS ~= amp/sqrt(2) → ~-6 dBFS de pico-rms
        assert -10 < db < -3

    def test_empty_returns_floor(self):
        from recordo.sources import _rms_dbfs_s16le

        assert _rms_dbfs_s16le(b"") <= -90
