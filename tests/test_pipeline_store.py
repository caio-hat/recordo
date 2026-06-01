"""Tests for B4 (_PipelineStatusStore) and B13 (decomposed _transcribe_async)."""

from __future__ import annotations

import threading

from recordo.pipeline import (
    _PipelineStatusStore,
    _resolve_backend_with_fallback,
)


class TestPipelineStatusStore:
    """B4: thread-safe + size cap."""

    def test_set_get_basic(self):
        store = _PipelineStatusStore(keep_last=10)
        store.set("session-1", {"ok": True})
        assert store.get("session-1") == {"ok": True}

    def test_get_unknown_returns_empty_dict(self):
        store = _PipelineStatusStore()
        assert store.get("nonexistent") == {}

    def test_get_returns_copy(self):
        """Mutations on returned dict shouldn't affect internal state."""
        store = _PipelineStatusStore()
        store.set("s", {"key": "value"})
        retrieved = store.get("s")
        retrieved["key"] = "modified"
        # Internal state should NOT be modified
        assert store.get("s") == {"key": "value"}

    def test_clear_old_keeps_last_n(self):
        store = _PipelineStatusStore(keep_last=3)
        for i in range(10):
            store.set(f"session-{i}", {"i": i})
        assert store.size() == 10
        dropped = store.clear_old()
        assert dropped == 7
        assert store.size() == 3
        # Last 3 inserted are kept
        for i in range(7, 10):
            assert store.get(f"session-{i}") == {"i": i}
        # Old ones are gone
        for i in range(7):
            assert store.get(f"session-{i}") == {}

    def test_clear_old_noop_when_under_limit(self):
        store = _PipelineStatusStore(keep_last=5)
        store.set("a", {})
        store.set("b", {})
        dropped = store.clear_old()
        assert dropped == 0
        assert store.size() == 2

    def test_clear_old_with_explicit_keep_last_override(self):
        store = _PipelineStatusStore(keep_last=10)
        for i in range(5):
            store.set(f"s-{i}", {"i": i})
        store.clear_old(keep_last=2)
        assert store.size() == 2

    def test_thread_safety_concurrent_writes(self):
        """10 threads, 100 writes each, no exceptions, no data loss."""
        store = _PipelineStatusStore(keep_last=10000)  # large cap, no eviction
        errors = []

        def worker(thread_id: int):
            try:
                for i in range(100):
                    store.set(f"thread-{thread_id}-iter-{i}", {"t": thread_id, "i": i})
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == [], f"thread errors: {errors}"
        assert store.size() == 1000  # 10 threads * 100

    def test_thread_safety_mixed_read_write(self):
        store = _PipelineStatusStore(keep_last=1000)
        errors = []
        results = []

        def writer():
            try:
                for i in range(50):
                    store.set(f"k-{i}", {"v": i})
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for i in range(50):
                    _ = store.get(f"k-{i}")
                    results.append(i)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer) for _ in range(3)] + [
            threading.Thread(target=reader) for _ in range(3)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []

    def test_clear_wipes_all(self):
        store = _PipelineStatusStore()
        store.set("a", {"x": 1})
        store.set("b", {"y": 2})
        store.clear()
        assert store.size() == 0


class TestResolveBackendWithFallback:
    """B13: helper de fallback parakeet → whisper."""

    def test_parakeet_with_nemo_unavailable_falls_back(self, monkeypatch):
        """Sem nemo, parakeet → whisper."""
        # Simula nemo ausente
        import sys as _sys

        # Cache nemo state
        nemo_cached = _sys.modules.get("nemo.collections.asr")
        if "nemo.collections.asr" in _sys.modules:
            del _sys.modules["nemo.collections.asr"]

        # Mock import to fail
        original_import = (
            __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__
        )

        def mocked_import(name, *args, **kwargs):
            if name == "nemo.collections.asr":
                raise ImportError("nemo not installed")
            return original_import(name, *args, **kwargs)

        if isinstance(__builtins__, dict):
            __builtins__["__import__"] = mocked_import
        else:
            __builtins__.__import__ = mocked_import

        # Mock ensure_whisper_installed to return True
        from recordo import pipeline as pipeline_mod

        monkeypatch.setattr(pipeline_mod, "ensure_whisper_installed", lambda: True)
        monkeypatch.setattr(pipeline_mod, "notify", lambda *a, **kw: None)

        try:
            cfg: dict = {}
            result = _resolve_backend_with_fallback("parakeet", cfg)
            assert result == "whisper"
            assert "whisper" in cfg
        finally:
            # Restore
            if isinstance(__builtins__, dict):
                __builtins__["__import__"] = original_import
            else:
                __builtins__.__import__ = original_import
            if nemo_cached:
                _sys.modules["nemo.collections.asr"] = nemo_cached

    def test_whisper_with_faster_whisper_unavailable_returns_none(self, monkeypatch):
        from recordo import pipeline as pipeline_mod

        monkeypatch.setattr(pipeline_mod, "ensure_whisper_installed", lambda: False)
        monkeypatch.setattr(pipeline_mod, "notify", lambda *a, **kw: None)

        cfg: dict = {"whisper": {}}
        result = _resolve_backend_with_fallback("whisper", cfg)
        assert result is None

    def test_cohere_does_not_need_install(self):
        """cohere is API HTTP, doesn't need local install check."""
        result = _resolve_backend_with_fallback("cohere", {})
        assert result == "cohere"
