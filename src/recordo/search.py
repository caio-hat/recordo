"""Search cross-notas em ~/Notas/.

Busca regex (case-insensitive por default) em:
  - nota.md (incl. resumo + transcrição embedded)
  - transcricao.txt
  - resumo.md (se existir)
  - topics.json

Ranking simples: número de matches (sentenças/contexto), então recency.
Snippets: ~80 chars antes/depois do match, juntando linhas vizinhas.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import NOTAS_DIR

log = logging.getLogger(__name__)

# Quais arquivos buscar por padrão e qual peso (mais alto = mais relevante)
_FILE_PATTERNS = (
    ("nota.md", 1.0),
    ("transcricao.txt", 0.5),
    ("resumo.md", 1.5),  # resumo é curto, match aqui é forte sinal
)

SNIPPET_CONTEXT_CHARS = 80
MAX_SNIPPETS_PER_FILE = 5


@dataclass
class SearchHit:
    recording_dir: Path
    file_relative: str  # ex: "nota.md"
    match_count: int
    snippets: list[str] = field(default_factory=list)
    weight: float = 1.0  # peso do tipo de arquivo

    @property
    def score(self) -> float:
        """Score = matches * weight * log(2 + recency_days)."""
        # Recency: arquivos modificados recentemente sobem
        try:
            days = (
                Path.cwd().stat().st_mtime - (self.recording_dir / self.file_relative).stat().st_mtime
            ) / 86400
            recency_factor = 1.0 / (1.0 + max(0, days) / 30)  # decay 30 dias
        except OSError:
            recency_factor = 1.0
        return self.match_count * self.weight * recency_factor


def search_notas(
    query: str,
    *,
    notas_dir: Path | None = None,
    case_sensitive: bool = False,
    file_filter: list[str] | None = None,
) -> list[SearchHit]:
    """Busca query em ~/Notas/ e retorna hits ordenados por score desc.

    Args:
      query: regex ou substring
      notas_dir: override do default
      case_sensitive: default False
      file_filter: lista de basenames a buscar (default: nota.md, transcricao.txt, resumo.md)
    """
    if notas_dir is None:
        notas_dir = NOTAS_DIR
    if not notas_dir.exists():
        return []

    files_filter = set(file_filter) if file_filter else None

    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        pattern = re.compile(query, flags)
    except re.error:
        # Fallback: trata como substring literal
        pattern = re.compile(re.escape(query), flags)

    hits: list[SearchHit] = []
    for d in sorted(notas_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not d.is_dir() or not d.name.startswith("2"):  # ignora dirs não-data
            continue

        for file_basename, weight in _FILE_PATTERNS:
            if files_filter and file_basename not in files_filter:
                continue
            f = d / file_basename
            if not f.exists():
                continue
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            matches = list(pattern.finditer(content))
            if not matches:
                continue

            snippets = _extract_snippets(content, matches[:MAX_SNIPPETS_PER_FILE], pattern)
            hits.append(
                SearchHit(
                    recording_dir=d,
                    file_relative=file_basename,
                    match_count=len(matches),
                    snippets=snippets,
                    weight=weight,
                )
            )

    hits.sort(key=lambda h: h.score, reverse=True)
    return hits


def _extract_snippets(content: str, matches: list[re.Match], pattern: re.Pattern) -> list[str]:
    """Extrai snippets contextuais ao redor de cada match."""
    snippets = []
    for m in matches:
        start = max(0, m.start() - SNIPPET_CONTEXT_CHARS)
        end = min(len(content), m.end() + SNIPPET_CONTEXT_CHARS)
        snippet = content[start:end].strip()
        # Highlight do match (usa _ ao invés de cores pra ser portátil)
        highlighted = pattern.sub(lambda mm: f"**{mm.group()}**", snippet, count=1)
        # Remove quebras de linha pra ficar one-liner
        highlighted = re.sub(r"\s+", " ", highlighted)
        snippets.append(highlighted)
    return snippets
