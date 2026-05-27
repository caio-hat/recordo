"""Detecção de hardware (CPU/GPU) para escolha de backend de transcrição.

Detecta:
- CUDA (NVIDIA): ctranslate2 cuda support, faster-whisper rápido
- ROCm (AMD discreta): ctranslate2 não suporta diretamente, mas existe via PyTorch
- Vulkan: AMD/Intel/NVIDIA iGPUs e dGPUs, suportado por whisper.cpp
- CPU AVX2/AVX512: faster-whisper com int8 acelerado

Caminhos recomendados por hardware:
- CUDA → faster-whisper (device='cuda', compute='int8_float16')
- AMD discreta + ROCm → whisper.cpp com HIP backend
- AMD iGPU (680M etc) → whisper.cpp com Vulkan backend
- CPU sem GPU → faster-whisper (device='cpu', compute='int8')
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class HardwareInfo:
    cpu_brand: str = ""
    cpu_threads: int = 0
    has_avx2: bool = False
    has_avx512: bool = False
    gpus: list[str] | None = None  # Nomes dos GPU/iGPU
    has_cuda: bool = False
    has_rocm: bool = False
    has_vulkan: bool = False
    vulkan_device: str = ""

    def __post_init__(self) -> None:
        if self.gpus is None:
            self.gpus = []

    @property
    def best_whisper_backend(self) -> str:
        """Backend recomendado para Whisper baseado no hardware.

        Returns:
          'cuda', 'whisper_cpp_vulkan', 'whisper_cpp_hip', 'cpu_optimized', 'cpu'
        """
        if self.has_cuda:
            return "cuda"
        if self.has_rocm:
            return "whisper_cpp_hip"
        if self.has_vulkan:
            return "whisper_cpp_vulkan"
        if self.has_avx2 or self.has_avx512:
            return "cpu_optimized"
        return "cpu"

    @property
    def description(self) -> str:
        parts = []
        if self.cpu_brand:
            cpu_feat = []
            if self.has_avx512:
                cpu_feat.append("AVX-512")
            elif self.has_avx2:
                cpu_feat.append("AVX2")
            parts.append(
                f"CPU: {self.cpu_brand} ({self.cpu_threads}t)"
                + (f" [{', '.join(cpu_feat)}]" if cpu_feat else "")
            )
        if self.gpus:
            parts.append(f"GPU: {', '.join(self.gpus)}")
        accel = []
        if self.has_cuda:
            accel.append("CUDA")
        if self.has_rocm:
            accel.append("ROCm")
        if self.has_vulkan:
            accel.append(f"Vulkan ({self.vulkan_device})" if self.vulkan_device else "Vulkan")
        if accel:
            parts.append(f"Aceleradores: {', '.join(accel)}")
        return " · ".join(parts) or "(hardware desconhecido)"


def detect_hardware() -> HardwareInfo:
    """Detecta CPU + GPUs + aceleradores disponíveis."""
    info = HardwareInfo()

    # CPU
    try:
        cpu_text = subprocess.run(["lscpu"], capture_output=True, text=True, timeout=2, check=True).stdout
        m = re.search(r"^Model name:\s*(.+)$", cpu_text, re.M)
        if m:
            info.cpu_brand = m.group(1).strip()[:80]
        m = re.search(r"^CPU\(s\):\s*(\d+)$", cpu_text, re.M)
        if m:
            info.cpu_threads = int(m.group(1))
        flags = ""
        m = re.search(r"^Flags:\s*(.+)$", cpu_text, re.M)
        if m:
            flags = m.group(1).lower()
        info.has_avx2 = "avx2" in flags
        info.has_avx512 = "avx512" in flags
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # GPU detection via lspci
    try:
        lspci = subprocess.run(["lspci", "-nn"], capture_output=True, text=True, timeout=2, check=True).stdout
        for line in lspci.splitlines():
            if re.search(r"VGA|Display|3D", line, re.I):
                # Extrai nome do GPU "[AMD/ATI] Rembrandt [Radeon 680M]"
                m = re.search(r":\s*(.+?)\s*\[[\da-f]+:[\da-f]+\]", line)
                if m:
                    info.gpus.append(m.group(1).strip()[:80])
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # CUDA
    info.has_cuda = bool(shutil.which("nvidia-smi"))

    # ROCm
    info.has_rocm = bool(shutil.which("rocminfo") or shutil.which("rocm-smi"))

    # Vulkan
    if shutil.which("vulkaninfo"):
        try:
            out = subprocess.run(
                ["vulkaninfo", "--summary"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            ).stdout
            # Procurar primeiro deviceName que não seja llvmpipe (CPU fallback)
            for m in re.finditer(r"deviceName\s*=\s*(.+)", out):
                name = m.group(1).strip()
                if "llvmpipe" not in name.lower():
                    info.has_vulkan = True
                    info.vulkan_device = name
                    break
            # Se só tem llvmpipe, ainda count como Vulkan disponível mas não acelerado
            if not info.has_vulkan and "deviceName" in out:
                info.has_vulkan = False
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass

    return info
