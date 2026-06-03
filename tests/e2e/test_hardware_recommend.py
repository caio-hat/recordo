# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Caio Hat
"""E2E hardware recommendation logic."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e


def test_recommend_low_ram_excludes_heavy_models():
    from recordo import hardware
    from recordo.hardware import CPUInfo, HardwareReport, MemoryInfo

    fake_report = HardwareReport(
        memory=MemoryInfo(total_mb=4000, available_mb=2000, used_mb=2000, swap_total_mb=0, swap_used_mb=0),
        cpu=CPUInfo(
            physical_cores=2, logical_cores=4, model_name="Test CPU", max_freq_mhz=2000.0, arch="x86_64"
        ),
        gpus=[],
    )
    recos = hardware.recommend_backends(report=fake_report)
    viable = [r for r in recos if r.viable]
    # Em 2GB livre, parakeet-onnx (2.5GB) não cabe; cohere e whisper-tiny sim.
    viable_backends = {r.backend for r in viable}
    assert "cohere" in viable_backends
    assert "whisper-tiny" in viable_backends
    assert "parakeet-nemo" not in viable_backends  # 6.5GB não cabe


def test_recommend_high_ram_includes_all():
    from recordo import hardware
    from recordo.hardware import CPUInfo, HardwareReport, MemoryInfo

    fake_report = HardwareReport(
        memory=MemoryInfo(
            total_mb=64000, available_mb=32000, used_mb=32000, swap_total_mb=8000, swap_used_mb=0
        ),
        cpu=CPUInfo(
            physical_cores=12, logical_cores=24, model_name="High End", max_freq_mhz=4000.0, arch="x86_64"
        ),
        gpus=[],
    )
    recos = hardware.recommend_backends(report=fake_report)
    viable = [r for r in recos if r.viable]
    assert len(viable) >= 4  # quase todos backends cabem


def test_preflight_blocks_when_low_ram():
    from recordo import hardware
    from recordo.hardware import CPUInfo, HardwareReport, MemoryInfo

    low_ram = HardwareReport(
        memory=MemoryInfo(total_mb=4000, available_mb=1000, used_mb=3000, swap_total_mb=0, swap_used_mb=0),
        cpu=CPUInfo(physical_cores=2, logical_cores=2, model_name="", max_freq_mhz=0, arch=""),
        gpus=[],
    )
    ok, msg = hardware.preflight("parakeet-nemo", low_ram)
    assert ok is False
    assert "mem" in msg.lower() or "ram" in msg.lower() or "mb" in msg.lower()
