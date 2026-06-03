"""Testes para o módulo de detecção de hardware."""

from __future__ import annotations

from unittest.mock import patch

from recordo.hardware import (
    CPUInfo,
    GPUInfo,
    HardwareReport,
    MemoryInfo,
    format_size_mb,
    preflight,
    probe_cpu,
    probe_memory,
    recommend_backends,
)


def _make_report(available_mb: int, total_mb: int = 0, has_accel: bool = False) -> HardwareReport:
    if not total_mb:
        total_mb = available_mb + 2000
    gpus = []
    if has_accel:
        gpus = [GPUInfo(vendor="nvidia", model="Test GPU", vram_mb=8000, has_cuda=True)]
    return HardwareReport(
        memory=MemoryInfo(
            total_mb=total_mb,
            available_mb=available_mb,
            used_mb=total_mb - available_mb,
            swap_total_mb=2048,
            swap_used_mb=0,
        ),
        cpu=CPUInfo(physical_cores=4, logical_cores=8, model_name="Test CPU", arch="x86_64"),
        gpus=gpus,
    )


class TestProbeMemory:
    def test_probe_memory_returns_valid(self):
        class FakeVM:
            total = 16 * 1024 * 1024 * 1024  # 16 GB
            available = 8 * 1024 * 1024 * 1024
            used = 8 * 1024 * 1024 * 1024

        class FakeSW:
            total = 2 * 1024 * 1024 * 1024
            used = 512 * 1024 * 1024

        with (
            patch("recordo.hardware.psutil.virtual_memory", return_value=FakeVM()),
            patch("recordo.hardware.psutil.swap_memory", return_value=FakeSW()),
        ):
            mem = probe_memory()
            assert mem.total_mb == 16384
            assert mem.available_mb == 8192
            assert mem.used_mb == 8192
            assert mem.swap_total_mb == 2048
            assert mem.swap_used_mb == 512


class TestProbeCPU:
    def test_probe_cpu_parses_proc_cpuinfo(self, monkeypatch, tmp_path):
        cpuinfo_content = (
            "processor\t: 0\n"
            "vendor_id\t: AuthenticAMD\n"
            "model name\t: AMD Ryzen 5 7535HS with Radeon Graphics\n"
            "cpu MHz\t\t: 3300.000\n"
        )
        fake_file = tmp_path / "cpuinfo"
        fake_file.write_text(cpuinfo_content)

        original_open = open

        def mock_open(path, *args, **kwargs):
            if str(path) == "/proc/cpuinfo":
                return original_open(str(fake_file), *args, **kwargs)
            return original_open(path, *args, **kwargs)

        with (
            patch("builtins.open", side_effect=mock_open),
            patch("recordo.hardware.psutil.cpu_count", side_effect=lambda logical: 12 if logical else 6),
            patch("recordo.hardware.psutil.cpu_freq", return_value=None),
        ):
            cpu = probe_cpu()
            assert cpu.model_name == "AMD Ryzen 5 7535HS with Radeon Graphics"
            assert cpu.physical_cores == 6
            assert cpu.logical_cores == 12


class TestRecommendBackends:
    def test_ordering_4gb(self):
        report = _make_report(available_mb=4000)
        recs = recommend_backends(report=report)
        viable = [r for r in recs if r.viable]
        not_viable = [r for r in recs if not r.viable]
        # 4GB: cohere(100), whisper-tiny(1500), whisper-base(2200), parakeet-onnx(2500) viable
        # whisper-large(4500), parakeet-nemo(6500) NOT viable
        assert all(r.backend in ("cohere", "whisper-tiny", "whisper-base", "parakeet-onnx") for r in viable)
        assert all(r.backend in ("whisper-large-v3-turbo", "parakeet-nemo") for r in not_viable)

    def test_ordering_8gb(self):
        report = _make_report(available_mb=8000)
        recs = recommend_backends(report=report)
        # All backends viable (8000 >= 6500)
        assert all(r.viable for r in recs)
        # whisper-large-v3-turbo should be first (best quality)
        assert recs[0].backend == "whisper-large-v3-turbo"

    def test_ordering_16gb(self):
        report = _make_report(available_mb=16000, has_accel=True)
        recs = recommend_backends(report=report)
        assert all(r.viable for r in recs)
        # With GPU acceleration, whisper-large should still be top
        assert recs[0].backend == "whisper-large-v3-turbo"
        # Priorities should be ascending
        priorities = [r.suggested_priority for r in recs]
        assert priorities == sorted(priorities)


class TestPreflight:
    def test_preflight_blocks_when_insufficient(self):
        report = _make_report(available_mb=2000)
        ok, msg = preflight("parakeet-nemo", report=report)
        assert ok is False
        assert "insuficiente" in msg.lower()

    def test_preflight_ok_when_sufficient(self):
        report = _make_report(available_mb=8000)
        ok, msg = preflight("whisper-large-v3-turbo", report=report)
        assert ok is True
        assert "OK" in msg

    def test_preflight_generic_whisper(self):
        report = _make_report(available_mb=2000)
        ok, _msg = preflight("whisper", report=report)
        # "whisper" maps to "whisper-large-v3-turbo" (4500 MB), should fail with 2000
        assert ok is False


class TestFormatSizeMb:
    def test_1500_is_gb(self):
        assert format_size_mb(1500) == "1,5 GB"

    def test_500_is_mb(self):
        assert format_size_mb(500) == "500 MB"

    def test_1000_is_gb(self):
        assert format_size_mb(1000) == "1,0 GB"

    def test_100_is_mb(self):
        assert format_size_mb(100) == "100 MB"
