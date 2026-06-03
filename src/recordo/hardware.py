"""Detecção de hardware e recomendação de backends de transcrição."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Literal

import psutil

log = logging.getLogger(__name__)

_SUBPROCESS_KWARGS: dict = {
    "capture_output": True,
    "text": True,
    "encoding": "utf-8",
    "errors": "replace",
    "timeout": 3,
}

# RAM mínima (MB) por backend
_BACKEND_RAM: dict[str, int] = {
    "cohere": 100,
    "whisper-tiny": 1500,
    "whisper-base": 2200,
    "whisper-large-v3-turbo": 4500,
    "parakeet-onnx": 2500,
    "parakeet-nemo": 6500,
}


@dataclass(frozen=True)
class MemoryInfo:
    total_mb: int
    available_mb: int
    used_mb: int
    swap_total_mb: int
    swap_used_mb: int


@dataclass(frozen=True)
class CPUInfo:
    physical_cores: int
    logical_cores: int
    model_name: str = ""
    max_freq_mhz: float = 0.0
    arch: str = ""  # x86_64, aarch64, etc


@dataclass(frozen=True)
class GPUInfo:
    vendor: Literal["nvidia", "amd", "intel", "unknown"]
    model: str
    vram_mb: int = 0
    has_cuda: bool = False
    has_rocm: bool = False
    has_vulkan: bool = False


@dataclass(frozen=True)
class HardwareReport:
    memory: MemoryInfo
    cpu: CPUInfo
    gpus: list[GPUInfo] = field(default_factory=list)

    @property
    def has_gpu_acceleration(self) -> bool:
        return any(g.has_cuda or g.has_rocm for g in self.gpus)


@dataclass(frozen=True)
class BackendRecommendation:
    backend: str
    viable: bool
    reason: str
    ram_required_mb: int
    suggested_priority: int


def format_size_mb(mb: int) -> str:
    """Helper: 1500 -> '1,5 GB' ou '500 MB'."""
    if mb >= 1000:
        gb = mb / 1000
        # Formato PT-BR com vírgula
        formatted = f"{gb:.1f}".replace(".", ",")
        return f"{formatted} GB"
    return f"{mb} MB"


def probe_memory() -> MemoryInfo:
    """Detecta memória via psutil."""
    try:
        vm = psutil.virtual_memory()
        sw = psutil.swap_memory()
        return MemoryInfo(
            total_mb=int(vm.total / (1024 * 1024)),
            available_mb=int(vm.available / (1024 * 1024)),
            used_mb=int(vm.used / (1024 * 1024)),
            swap_total_mb=int(sw.total / (1024 * 1024)),
            swap_used_mb=int(sw.used / (1024 * 1024)),
        )
    except Exception:
        log.exception("Erro ao detectar memória")
        return MemoryInfo(0, 0, 0, 0, 0)


def probe_cpu() -> CPUInfo:
    """Detecta CPU via /proc/cpuinfo + psutil."""
    model_name = ""
    try:
        with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("model name"):
                    parts = line.split(":", 1)
                    if len(parts) == 2:
                        model_name = parts[1].strip()
                    break
    except OSError:
        pass

    physical = psutil.cpu_count(logical=False) or 0
    logical = psutil.cpu_count(logical=True) or 0

    max_freq = 0.0
    try:
        freq = psutil.cpu_freq()
        if freq:
            max_freq = freq.max or 0.0
    except Exception:
        pass

    arch = os.uname().machine if hasattr(os, "uname") else ""

    return CPUInfo(
        physical_cores=physical,
        logical_cores=logical,
        model_name=model_name,
        max_freq_mhz=max_freq,
        arch=arch,
    )


def _detect_vendor(model: str) -> Literal["nvidia", "amd", "intel", "unknown"]:
    low = model.lower()
    if "nvidia" in low or "geforce" in low or "quadro" in low or "tesla" in low:
        return "nvidia"
    if "amd" in low or "ati" in low or "radeon" in low or "navi" in low or "rembrandt" in low:
        return "amd"
    if "intel" in low:
        return "intel"
    return "unknown"


def _probe_nvidia_vram() -> dict[str, int]:
    """Tenta nvidia-smi para obter VRAM. Retorna {model: vram_mb}."""
    if not shutil.which("nvidia-smi"):
        return {}
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            **_SUBPROCESS_KWARGS,
        )
        if r.returncode != 0:
            return {}
        result = {}
        for line in r.stdout.strip().splitlines():
            parts = line.split(",")
            if len(parts) >= 2:
                name = parts[0].strip()
                try:
                    vram = int(float(parts[1].strip()))
                except ValueError:
                    vram = 0
                result[name] = vram
        return result
    except (subprocess.TimeoutExpired, OSError):
        return {}


def _probe_rocm_vram() -> int:
    """Tenta rocm-smi para obter VRAM total. Retorna MB ou 0."""
    if not shutil.which("rocm-smi"):
        return 0
    try:
        r = subprocess.run(["rocm-smi", "--showmeminfo", "vram", "--csv"], **_SUBPROCESS_KWARGS)
        if r.returncode != 0:
            return 0
        for line in r.stdout.splitlines():
            if "total" in line.lower():
                nums = re.findall(r"(\d+)", line)
                if nums:
                    # rocm-smi reports in bytes typically
                    val = int(nums[-1])
                    if val > 1_000_000:
                        return val // (1024 * 1024)
                    return val
    except (subprocess.TimeoutExpired, OSError):
        pass
    return 0


def _check_vulkan() -> bool:
    """Verifica se Vulkan está disponível com device real."""
    if not shutil.which("vulkaninfo"):
        return False
    try:
        r = subprocess.run(["vulkaninfo", "--summary"], **_SUBPROCESS_KWARGS)
        if r.returncode != 0:
            return False
        for m in re.finditer(r"deviceName\s*=\s*(.+)", r.stdout):
            name = m.group(1).strip()
            if "llvmpipe" not in name.lower():
                return True
    except (subprocess.TimeoutExpired, OSError):
        pass
    return False


def probe_gpus() -> list[GPUInfo]:
    """Detecta GPUs via lspci + probes de aceleradores."""
    gpus: list[GPUInfo] = []
    models: list[tuple[str, str]] = []  # (raw_line_match, vendor)

    try:
        r = subprocess.run(["lspci", "-nn"], **_SUBPROCESS_KWARGS)
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                if re.search(r"VGA|3D", line, re.I):
                    # Format: "XX:XX.X Class [code]: Vendor Device [pci:id]"
                    m = re.search(r"\[\w{4}\]:\s*(.+?)\s*\[[\da-f]{4}:[\da-f]{4}\]", line)
                    if m:
                        models.append((m.group(1).strip(), ""))
    except (subprocess.TimeoutExpired, OSError):
        pass

    nvidia_vram = _probe_nvidia_vram()
    rocm_vram = _probe_rocm_vram()
    has_vulkan = _check_vulkan()
    has_cuda = bool(shutil.which("nvidia-smi"))
    has_rocm = bool(shutil.which("rocm-smi") or shutil.which("rocminfo"))

    for model_str, _ in models:
        vendor = _detect_vendor(model_str)
        vram = 0
        gpu_cuda = False
        gpu_rocm = False

        if vendor == "nvidia":
            gpu_cuda = has_cuda
            # Match nvidia_vram by partial name
            for nv_name, nv_vram in nvidia_vram.items():
                if nv_name.lower() in model_str.lower() or model_str.lower() in nv_name.lower():
                    vram = nv_vram
                    break
            if not vram and nvidia_vram:
                vram = next(iter(nvidia_vram.values()))
        elif vendor == "amd":
            gpu_rocm = has_rocm
            vram = rocm_vram

        gpus.append(
            GPUInfo(
                vendor=vendor,
                model=model_str[:80],
                vram_mb=vram,
                has_cuda=gpu_cuda,
                has_rocm=gpu_rocm,
                has_vulkan=has_vulkan and vendor != "unknown",
            )
        )

    return gpus


def probe() -> HardwareReport:
    """Combina probes de memória, CPU e GPU."""
    return HardwareReport(memory=probe_memory(), cpu=probe_cpu(), gpus=probe_gpus())


def recommend_backends(
    audio_duration_s: float | None = None,
    report: HardwareReport | None = None,
) -> list[BackendRecommendation]:
    """Retorna lista de backends ordenada por suggested_priority (asc)."""
    if report is None:
        report = probe()

    available = report.memory.available_mb
    has_accel = report.has_gpu_acceleration
    cores = report.cpu.logical_cores

    recommendations: list[BackendRecommendation] = []

    for backend, ram_req in _BACKEND_RAM.items():
        viable = available >= ram_req
        reason = f"RAM disponível: {format_size_mb(available)} · necessário: {format_size_mb(ram_req)}"

        # Calcular prioridade: menor = melhor
        priority = 100
        if viable:
            # Base priority pela qualidade do backend
            base = {
                "whisper-large-v3-turbo": 10,
                "parakeet-nemo": 15,
                "parakeet-onnx": 20,
                "whisper-base": 30,
                "whisper-tiny": 40,
                "cohere": 50,
            }[backend]

            # Bonus por GPU acceleration (modelos locais pesados se beneficiam)
            if has_accel and backend not in ("cohere", "whisper-tiny"):
                base -= 5

            # Bonus por cores (modelos CPU-bound)
            if cores >= 8:
                base -= 2

            priority = base
        else:
            priority = 200 + ram_req  # Inviáveis ficam por último, ordenados por custo

        recommendations.append(
            BackendRecommendation(
                backend=backend,
                viable=viable,
                reason=reason,
                ram_required_mb=ram_req,
                suggested_priority=priority,
            )
        )

    recommendations.sort(key=lambda r: r.suggested_priority)
    return recommendations


def preflight(backend: str, report: HardwareReport | None = None) -> tuple[bool, str]:
    """Verifica se o backend pode rodar. Retorna (ok, mensagem_pt_br)."""
    if report is None:
        report = probe()

    # Normalizar backend genérico
    if backend == "whisper":
        backend = "whisper-large-v3-turbo"

    ram_req = _BACKEND_RAM.get(backend)
    if ram_req is None:
        return False, f"Backend '{backend}' desconhecido."

    available = report.memory.available_mb
    if available < ram_req:
        return (
            False,
            f"RAM insuficiente para {backend}: disponível {format_size_mb(available)}, "
            f"necessário {format_size_mb(ram_req)}.",
        )

    return True, f"Hardware OK para {backend} ({format_size_mb(available)} disponível)."
