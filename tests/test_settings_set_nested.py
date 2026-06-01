"""Tests for SettingsScreen._set_nested + _coerce (B1 regression)."""

from __future__ import annotations

from recordo.tui_textual import SettingsScreen


class TestCoerce:
    """Test _coerce() type conversion."""

    def test_bool_true_variants(self):
        for v in ("true", "True", "TRUE", "1", "yes", "Y", "on", "t"):
            assert SettingsScreen._coerce(v, bool) is True, f"failed for {v!r}"

    def test_bool_false_variants(self):
        for v in ("false", "0", "no", "off", "", "anything-else"):
            assert SettingsScreen._coerce(v, bool) is False, f"failed for {v!r}"

    def test_bool_with_whitespace(self):
        assert SettingsScreen._coerce("  true  ", bool) is True
        assert SettingsScreen._coerce("  false  ", bool) is False

    def test_int_valid(self):
        assert SettingsScreen._coerce("42", int) == 42
        assert SettingsScreen._coerce("  100  ", int) == 100
        assert SettingsScreen._coerce("-5", int) == -5

    def test_int_invalid_returns_raw(self):
        # Failure to convert returns raw string (graceful degradation)
        assert SettingsScreen._coerce("not-a-number", int) == "not-a-number"
        assert SettingsScreen._coerce("3.14", int) == "3.14"

    def test_float_valid(self):
        assert SettingsScreen._coerce("3.14", float) == 3.14
        assert SettingsScreen._coerce("42", float) == 42.0
        assert SettingsScreen._coerce("-0.5", float) == -0.5

    def test_float_invalid_returns_raw(self):
        assert SettingsScreen._coerce("xyz", float) == "xyz"

    def test_str_passthrough(self):
        assert SettingsScreen._coerce("hello world", str) == "hello world"
        assert SettingsScreen._coerce("", str) == ""


class TestSetNested:
    """Test _set_nested() table-driven coercion."""

    def test_existing_int_key(self):
        """B1 case 1: existing int key in DEFAULTS, value comes as string."""
        cfg = {"summarizer": {"ollama": {"num_ctx": 8192}}}
        SettingsScreen._set_nested(cfg, "summarizer.ollama.num_ctx", "32768")
        assert cfg["summarizer"]["ollama"]["num_ctx"] == 32768
        assert isinstance(cfg["summarizer"]["ollama"]["num_ctx"], int)

    def test_new_int_key_not_in_defaults(self):
        """B1 main bug: new key (not present yet), table forces correct type."""
        cfg: dict = {"summarizer": {"ollama": {}}}
        # num_ctx is in _FIELD_TYPES → int
        SettingsScreen._set_nested(cfg, "summarizer.ollama.num_ctx", "16384")
        assert cfg["summarizer"]["ollama"]["num_ctx"] == 16384
        assert isinstance(cfg["summarizer"]["ollama"]["num_ctx"], int)

    def test_bool_existing(self):
        cfg = {"auto_detect": {"enabled": False}}
        SettingsScreen._set_nested(cfg, "auto_detect.enabled", "true")
        assert cfg["auto_detect"]["enabled"] is True

    def test_bool_new_key(self):
        """Bool table-driven works for new keys too."""
        cfg: dict = {}
        SettingsScreen._set_nested(cfg, "auto_detect.enabled", "yes")
        assert cfg["auto_detect"]["enabled"] is True

    def test_str_default_for_unknown_key(self):
        """Unknown dotted key defaults to str (no coercion)."""
        cfg: dict = {}
        SettingsScreen._set_nested(cfg, "unknown.totally.new", "any value")
        assert cfg["unknown"]["totally"]["new"] == "any value"

    def test_creates_intermediate_dicts(self):
        """3+ level deep path creates intermediate dicts."""
        cfg: dict = {}
        SettingsScreen._set_nested(cfg, "a.b.c.d", "value")
        assert cfg["a"]["b"]["c"]["d"] == "value"

    def test_overwrites_non_dict_intermediate(self):
        """If intermediate path has non-dict (corrupted config), replace with dict."""
        cfg = {"a": "string"}
        SettingsScreen._set_nested(cfg, "a.b.c", "value")
        assert cfg["a"]["b"]["c"] == "value"

    def test_float_field(self):
        """Float fields like temperature."""
        cfg: dict = {}
        SettingsScreen._set_nested(cfg, "summarizer.ollama.temperature", "0.7")
        assert cfg["summarizer"]["ollama"]["temperature"] == 0.7
        assert isinstance(cfg["summarizer"]["ollama"]["temperature"], float)

    def test_invalid_int_falls_back_to_string(self):
        """Invalid value for typed key keeps string (graceful)."""
        cfg: dict = {}
        SettingsScreen._set_nested(cfg, "summarizer.ollama.num_ctx", "abc")
        # Falls back to raw string, not crashes
        assert cfg["summarizer"]["ollama"]["num_ctx"] == "abc"


class TestFieldTypesTable:
    """Validate _FIELD_TYPES content."""

    def test_critical_keys_present(self):
        """Most-used keys must be in the table."""
        critical = [
            "summarizer.ollama.num_ctx",
            "summarizer.ollama.temperature",
            "auto_detect.enabled",
            "transcriber.whisper.beam_size",
            "watchdog.silence_max_seconds",
        ]
        for k in critical:
            assert k in SettingsScreen._FIELD_TYPES, f"missing critical key {k!r}"

    def test_all_types_are_valid(self):
        """Only int/float/bool/str allowed."""
        valid = {int, float, bool, str}
        for k, t in SettingsScreen._FIELD_TYPES.items():
            assert t in valid, f"invalid type for {k}: {t}"
