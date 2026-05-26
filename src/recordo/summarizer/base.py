"""Base ABC para summarizers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class SummaryResult:
    """Resultado estruturado de uma sumarização.

    Todos os campos são opcionais — backends podem preencher só alguns
    dependendo da capacidade. O `resumo` é o mais importante e deve estar
    sempre presente.
    """

    resumo: str = ""  # 3-5 frases descrevendo o que aconteceu
    decisoes: list[str] = field(default_factory=list)  # decisões tomadas
    action_items: list[str] = field(default_factory=list)  # ações a fazer
    topicos: list[str] = field(default_factory=list)  # tópicos discutidos
    backend: str = ""  # ex: "ollama-gemma4:e2b" | "heuristic-textrank"
    error: str | None = None  # se falhou, msg humano-amigável

    @property
    def is_empty(self) -> bool:
        return not (self.resumo or self.decisoes or self.action_items or self.topicos)

    def to_markdown(self) -> str:
        """Renderiza como bloco markdown pra embedding em nota.md."""
        if self.error:
            return f"_(resumo indisponível: {self.error})_\n"
        if self.is_empty:
            return "_(sem resumo gerado)_\n"

        parts: list[str] = []
        if self.resumo:
            parts.append(f"**Resumo:** {self.resumo.strip()}\n")
        if self.topicos:
            parts.append("\n**Tópicos discutidos:**")
            parts.extend(f"- {t.strip()}" for t in self.topicos)
        if self.decisoes:
            parts.append("\n**Decisões:**")
            parts.extend(f"- {d.strip()}" for d in self.decisoes)
        if self.action_items:
            parts.append("\n**Ações pendentes:**")
            parts.extend(f"- {a.strip()}" for a in self.action_items)
        if self.backend:
            parts.append(f"\n_(gerado por: {self.backend})_")
        return "\n".join(parts) + "\n"


class Summarizer(ABC):
    """Interface comum pra todos os backends de sumarização."""

    @abstractmethod
    def summarize(self, transcript: str, *, language: str = "pt", subject: str = "") -> SummaryResult:
        """Gera um SummaryResult a partir do transcript completo."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Nome legível pra logging e nota.md."""


class NoOpSummarizer(Summarizer):
    """Summarizer que não faz nada (placeholder para 'disabled')."""

    @property
    def name(self) -> str:
        return "none"

    def summarize(self, transcript: str, *, language: str = "pt", subject: str = "") -> SummaryResult:
        return SummaryResult(backend=self.name)
