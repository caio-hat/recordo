"""Tests for ffmpeg command builders (puros, sem invocação)."""
from __future__ import annotations

from pathlib import Path

import pytest

from recordo.ffmpeg_cmds import build_capture_cmd, build_concat_cmd, build_merge_cmd


def test_capture_uses_libopus(tmp_path: Path):
    cmd = build_capture_cmd("alsa_input.x", tmp_path / "out.opus",
                            max_seconds=1800, bitrate="32k")
    assert "libopus" in cmd
    assert "-b:a" in cmd
    assert "32k" in cmd
    assert "-application" in cmd and "voip" in cmd
    assert "-t" in cmd and "1800" in cmd


def test_capture_pulse_input(tmp_path: Path):
    cmd = build_capture_cmd("alsa_input.foo", tmp_path / "out.opus",
                            max_seconds=300, bitrate="48k")
    idx = cmd.index("-i")
    assert cmd[idx + 1] == "alsa_input.foo"
    assert cmd[idx - 1] == "pulse"


def test_merge_empty_returns_empty(tmp_path: Path):
    sys_f = tmp_path / "sys.opus"
    mic_f = tmp_path / "mic.opus"
    cmd = build_merge_cmd(sys_f, mic_f, tmp_path / "out.opus", "merge", "32k")
    assert cmd == []


def test_merge_split_layout(tmp_path: Path):
    sys_f = tmp_path / "sys.opus"
    sys_f.write_bytes(b"x" * 100)
    mic_f = tmp_path / "mic.opus"
    mic_f.write_bytes(b"y" * 100)
    cmd = build_merge_cmd(sys_f, mic_f, tmp_path / "out.opus", "split", "32k")
    assert "join=inputs=2:channel_layout=stereo" in " ".join(cmd)
    assert "libopus" in cmd


def test_merge_with_loudnorm(tmp_path: Path):
    sys_f = tmp_path / "sys.opus"
    sys_f.write_bytes(b"x" * 100)
    mic_f = tmp_path / "mic.opus"
    mic_f.write_bytes(b"y" * 100)
    cmd = build_merge_cmd(sys_f, mic_f, tmp_path / "out.opus", "merge", "32k")
    full = " ".join(cmd)
    assert "amerge=inputs=2" in full
    assert "loudnorm" in full


def test_merge_silence_for_missing_sys(tmp_path: Path):
    sys_f = tmp_path / "sys.opus"  # vazio
    mic_f = tmp_path / "mic.opus"
    mic_f.write_bytes(b"y" * 100)
    cmd = build_merge_cmd(sys_f, mic_f, tmp_path / "out.opus", "merge", "32k")
    assert "anullsrc=channel_layout=mono:sample_rate=48000" in " ".join(cmd)


def test_concat_writes_list_file(tmp_path: Path):
    segs = [tmp_path / "a.opus", tmp_path / "b.opus"]
    for s in segs:
        s.write_bytes(b"x")
    list_p = tmp_path / "list.txt"
    cmd = build_concat_cmd(segs, list_p, tmp_path / "final.opus")
    assert list_p.exists()
    content = list_p.read_text()
    assert "a.opus" in content and "b.opus" in content
    assert "concat" in cmd
    assert "libopus" in cmd
