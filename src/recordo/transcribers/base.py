"""ABC pra backends de transcrição."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TranscriptionSegment:
    start: float  # segundos
    end: float
    text: str


@dataclass
class TranscriptionResult:
    segments: list[TranscriptionSegment] = field(default_factory=list)
    language: str = ""
    language_probability: float = 0.0
    backend: str = ""  # ex: "whisper-large-v3-turbo" | "parakeet-tdt-0.6b-v3"

    @property
    def text(self) -> str:
        """Concatena texto bruto (sem timestamps)."""
        return "\n".join(s.text.strip() for s in self.segments if s.text.strip())

    def write_txt(self, path: Path) -> None:
        with path.open("w", encoding="utf-8") as f:
            for s in self.segments:
                f.write(f"[{s.start:7.1f} → {s.end:7.1f}] {s.text.strip()}\n")

    def write_srt(self, path: Path) -> None:
        with path.open("w", encoding="utf-8") as f:
            for i, s in enumerate(self.segments, 1):
                f.write(f"{i}\n{_fmt_srt(s.start)} --> {_fmt_srt(s.end)}\n{s.text.strip()}\n\n")


def _fmt_srt(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t - h * 3600 - m * 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


class Transcriber(ABC):
    """Interface comum pra todos backends."""

    @abstractmethod
    def transcribe(self, audio: Path, *, language: str = "pt") -> TranscriptionResult:
        """Transcreve áudio e retorna resultado estruturado."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Nome legível do backend pra logging e nota.md (ex: 'whisper-large-v3-turbo')."""
