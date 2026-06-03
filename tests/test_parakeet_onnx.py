# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Caio Hat
"""Testes para ParakeetONNXTranscriber."""

from __future__ import annotations

import pytest

from recordo.transcribers.parakeet_onnx import (
    DEFAULT_MODEL_ID,
    ParakeetONNXTranscriber,
    _resolve_model_dir,
    is_installed,
)


def test_default_model_id():
    assert DEFAULT_MODEL_ID == "istupakov/parakeet-tdt-0.6b-v3-onnx"


def test_transcriber_name():
    t = ParakeetONNXTranscriber({"use_int8": True})
    assert t.name == "parakeet-onnx-int8"
    t2 = ParakeetONNXTranscriber({"use_int8": False})
    assert t2.name == "parakeet-onnx-fp32"


def test_resolve_model_dir_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HOME", str(tmp_path / "fake-cache"))
    assert _resolve_model_dir("foo/bar") is None


def test_is_installed_false_when_no_files(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HOME", str(tmp_path / "fake-cache"))
    assert is_installed() is False


def test_load_raises_when_model_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HOME", str(tmp_path / "fake-cache"))
    t = ParakeetONNXTranscriber({})
    with pytest.raises(RuntimeError, match="não encontrado"):
        t._load_recognizer()


def test_get_transcriber_dispatches_onnx_default():
    from recordo.transcribers import get_transcriber

    t = get_transcriber("parakeet", {"parakeet": {"engine": "onnx"}})
    assert "onnx" in t.name


def test_get_transcriber_dispatches_nemo_when_engine_nemo():
    from recordo.transcribers import get_transcriber

    t = get_transcriber("parakeet", {"parakeet": {"engine": "nemo"}})
    assert "onnx" not in t.name
