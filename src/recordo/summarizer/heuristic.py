"""HeuristicSummarizer — fallback sem LLM.

Usa abordagem TextRank-like simples sobre as sentenças do transcript:
  1. Tokeniza em sentenças
  2. Pontua cada sentença por tamanho médio + frequência de palavras-chave
  3. Pega top-N sentenças preservando ordem original
  4. Detecta padrões linguísticos para decisões e action items

Não substitui um LLM, mas dá um resumo decente quando Ollama não está
disponível ou quando o user quer algo determinístico/instantâneo.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any

from .base import Summarizer, SummaryResult

log = logging.getLogger(__name__)

# Stop words pt-BR mais comuns (subset suficiente para scoring)
_STOPWORDS_PT = frozenset(
    """a o e é de da do das dos em na no nas nos para com por
    que se um uma uns umas como mais menos muito pouco já não nem
    sim ou então mas porque pois assim aí ali aqui isso isto aquilo
    eu tu ele ela nós vós eles elas você vocês meu minha seu sua nosso nossa
    foi foram era ser está está estão tem têm tinha vai vão pode podem
    aí lá tá né cara mano""".split()
)

_DECISION_MARKERS = (
    r"vamos\s+(?:fazer|usar|implementar|criar|adotar|deixar|seguir|partir|começar|colocar)",
    r"decid[iu]m?\s+(?:que|por|usar|fazer|adotar)",
    r"ficou\s+(?:decidido|definido|combinado)",
    r"a\s+gente\s+(?:vai|combina|decide|fica)",
    r"vou\s+(?:fazer|tentar|implementar|adotar)",
    r"então\s+(?:vamos|fica|fazemos)",
)

_ACTION_MARKERS = (
    r"(?:precis[ao]|tem que|deve|vou|vai)\s+(?:fazer|implementar|criar|enviar|chamar|verificar|ver|testar|revisar|atualizar|resolver|finalizar)",
    r"(?:tarefa|action item|TODO|próximo passo)\s*[:=]?",
    r"\b(?:ficou|ficar)\s+(?:de|para)\s+\w+",
    r"alguém\s+precisa\s+\w+",
)


class HeuristicSummarizer(Summarizer):
    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config or {}
        self.top_n_sentences: int = cfg.get("top_n_sentences", 5)
        self.max_action_items: int = cfg.get("max_action_items", 8)

    @property
    def name(self) -> str:
        return "heuristic-textrank"

    def summarize(self, transcript: str, *, language: str = "pt", subject: str = "") -> SummaryResult:
        # Limpa timestamps comuns: "[ 0.0 → 8.0]" do formato txt do Whisper
        clean = re.sub(r"\[\s*[\d.]+\s*→\s*[\d.]+\s*\]", "", transcript)
        sentences = self._split_sentences(clean)
        if not sentences:
            return SummaryResult(backend=self.name, error="transcript vazio")

        scored = self._score_sentences(sentences)
        # Pega top N preservando ordem original
        top_indices = sorted(sorted(range(len(sentences)), key=lambda i: -scored[i])[: self.top_n_sentences])
        resumo_parts = [sentences[i] for i in top_indices]
        resumo = " ".join(resumo_parts).strip()
        # Limita resumo (3-5 frases é o ideal)
        if len(resumo) > 800:
            resumo = resumo[:800].rsplit(".", 1)[0] + "."

        decisoes = self._extract_pattern_matches(sentences, _DECISION_MARKERS, max_n=5)
        actions = self._extract_pattern_matches(sentences, _ACTION_MARKERS, max_n=self.max_action_items)
        topicos = self._extract_topics(sentences, scored)

        return SummaryResult(
            resumo=resumo,
            topicos=topicos,
            decisoes=decisoes,
            action_items=actions,
            backend=self.name,
        )

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        # Quebra em sentenças por . ! ? seguido de espaço ou newline
        parts = re.split(r"(?<=[.!?])\s+|\n+", text)
        # Filtra muito curtas / muito longas
        return [p.strip() for p in parts if 10 < len(p.strip()) < 400]

    def _score_sentences(self, sentences: list[str]) -> dict[int, float]:
        """Score por TF (sentença) sobre frequência global de palavras-chave."""
        # Frequência de palavras (sem stopwords)
        all_words = []
        for s in sentences:
            for w in re.findall(r"\b[\wÀ-ÿ]+\b", s.lower()):
                if w not in _STOPWORDS_PT and len(w) > 3:
                    all_words.append(w)
        word_freq = Counter(all_words)

        scores: dict[int, float] = {}
        for i, s in enumerate(sentences):
            words = re.findall(r"\b[\wÀ-ÿ]+\b", s.lower())
            content_words = [w for w in words if w not in _STOPWORDS_PT and len(w) > 3]
            if not content_words:
                scores[i] = 0
                continue
            # Score = soma das frequências das content words / num content words
            scores[i] = sum(word_freq.get(w, 0) for w in content_words) / len(content_words)
        return scores

    @staticmethod
    def _extract_pattern_matches(sentences: list[str], patterns: tuple[str, ...], max_n: int) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for s in sentences:
            for pat in patterns:
                if re.search(pat, s, re.IGNORECASE):
                    # Limpa repetições e normaliza
                    norm = re.sub(r"\s+", " ", s).strip(" .,;:")
                    if norm and norm.lower() not in seen:
                        seen.add(norm.lower())
                        out.append(norm)
                    break
            if len(out) >= max_n:
                break
        return out

    @staticmethod
    def _extract_topics(sentences: list[str], scores: dict[int, float]) -> list[str]:
        """Extrai 'tópicos' como bigrams/trigrams comuns de alto score."""
        # Combina text com weight por sentença (sentenças importantes contribuem mais)
        word_count: Counter[str] = Counter()
        for i, s in enumerate(sentences):
            weight = max(1.0, scores.get(i, 0))
            words = [
                w for w in re.findall(r"\b[\wÀ-ÿ]+\b", s.lower()) if w not in _STOPWORDS_PT and len(w) > 4
            ]
            for w in words:
                word_count[w] += weight
        # Top 5 palavras
        top = [w for w, _ in word_count.most_common(8)]
        return top[:5]
