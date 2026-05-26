"""Topic segmentation: extrai 'Assuntos da Conversa' com minutagem.

Para reuniões/calls que pulam de assunto (comum em ligações "do nada"),
quebramos a transcrição em tópicos com:
  - título curto (3-7 palavras)
  - timestamp inicio (mm:ss ou hh:mm:ss)
  - timestamp fim
  - se um tópico volta depois, registra novo intervalo separado

Exemplo de saída embedded em nota.md:

  ## Assuntos da Conversa

  - **00:00 — 05:23** · Filtragem de métricas Elasticsearch
  - **05:23 — 12:45** · Acesso ao Dashboard de produção
  - **12:45 — 18:30** · Filtragem por sites
  - **05:23 — 06:10** · Pergunta sobre métricas (volta do tópico anterior)

Usa LLM (mesmo provider configurado pra resumo). Heuristic fallback gera
tópicos baseados em sentenças-âncora e mudança de tema (TF cosine).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .summarizer import get_summarizer
from .transcribers import TranscriptionResult, TranscriptionSegment

log = logging.getLogger(__name__)

PROMPT_TEMPLATE = """Você é um assistente que segmenta transcrições em tópicos.

Analise a transcrição abaixo (com timestamps em segundos) e identifique os
tópicos discutidos. Quando um tópico já discutido VOLTA em outro momento,
registre como entrada separada.

Retorne APENAS JSON com a chave "topicos", array de objetos:
{{
  "topicos": [
    {{"titulo": "string curta (3-7 palavras)",
      "inicio_seconds": number,
      "fim_seconds": number,
      "retorno_de_topico_anterior": false}},
    ...
  ]
}}

Regras:
- Use 3 a 8 tópicos no total (não fragmente demais)
- "retorno_de_topico_anterior": true se este intervalo retoma um tópico já listado
- Cubra toda a duração da gravação
- Tópicos sequenciais não devem ter gaps grandes (< 5s)

{subject_line}TRANSCRIÇÃO (formato: [start_s → end_s] texto):
\"\"\"
{transcript}
\"\"\"
"""

MAX_TRANSCRIPT_CHARS = 30000


@dataclass
class Topic:
    """Um tópico com timerange."""

    titulo: str
    inicio_seconds: float
    fim_seconds: float
    retorno_de_topico_anterior: bool = False

    @property
    def inicio_str(self) -> str:
        return _fmt_ts(self.inicio_seconds)

    @property
    def fim_str(self) -> str:
        return _fmt_ts(self.fim_seconds)

    @property
    def duration_seconds(self) -> float:
        return max(0, self.fim_seconds - self.inicio_seconds)


@dataclass
class TopicsResult:
    topics: list[Topic] = field(default_factory=list)
    backend: str = ""  # ex: "ollama-gemma2:2b" ou "heuristic"
    error: str | None = None

    @property
    def is_empty(self) -> bool:
        return not self.topics

    def to_markdown(self) -> str:
        """Renderiza bloco markdown pra embed em nota.md."""
        if self.error:
            return f"_(assuntos indisponíveis: {self.error})_\n"
        if self.is_empty:
            return "_(sem tópicos identificados)_\n"

        lines: list[str] = []
        for t in self.topics:
            marker = " ↻ _(retoma tópico anterior)_" if t.retorno_de_topico_anterior else ""
            lines.append(f"- **{t.inicio_str} — {t.fim_str}** · {t.titulo}{marker}")
        if self.backend:
            lines.append("")
            lines.append(f"_(gerado por: {self.backend})_")
        return "\n".join(lines) + "\n"

    def to_json(self) -> str:
        return json.dumps(
            {"topics": [asdict(t) for t in self.topics], "backend": self.backend},
            ensure_ascii=False,
            indent=2,
        )


def _fmt_ts(seconds: float) -> str:
    """Segundos → mm:ss ou hh:mm:ss."""
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


def extract_topics(
    result: TranscriptionResult,
    *,
    subject: str = "",
    summarizer_cfg: dict[str, Any] | None = None,
) -> TopicsResult:
    """Extrai tópicos via LLM com fallback heuristic.

    Reusa o config do summarizer (mesmos providers, mesma cascata de fallbacks).
    Se LLM não disponível, cai pro algoritmo heurístico (segmentação por
    similaridade de sentenças vizinhas).
    """
    if not result.segments:
        return TopicsResult(error="transcrição vazia")

    cfg = summarizer_cfg or {}
    backend_name = cfg.get("backend", "ollama")

    # heuristic e none vão direto pra fallback heurístico
    if backend_name in ("none", "heuristic"):
        return _heuristic_extract_topics(result)

    # Tenta via LLM
    llm_result = _llm_extract_topics(result, subject=subject, summarizer_cfg=cfg)
    if not llm_result.error:
        return llm_result

    log.warning("LLM falhou em topic segmentation (%s) — fallback heuristic", llm_result.error)

    # Fallback: heuristic
    fallback = _heuristic_extract_topics(result)
    if not fallback.error:
        fallback.backend = f"{fallback.backend} (fallback de {llm_result.backend})"
    return fallback


def _llm_extract_topics(
    result: TranscriptionResult,
    *,
    subject: str,
    summarizer_cfg: dict[str, Any],
) -> TopicsResult:
    """Usa o summarizer configurado pra extrair tópicos via prompt JSON."""
    backend_name = summarizer_cfg.get("backend", "ollama")
    summ = get_summarizer(backend_name, summarizer_cfg)

    transcript_lines = [f"[{s.start:.1f} → {s.end:.1f}] {s.text.strip()}" for s in result.segments]
    transcript_text = "\n".join(transcript_lines)
    if len(transcript_text) > MAX_TRANSCRIPT_CHARS:
        transcript_text = transcript_text[:MAX_TRANSCRIPT_CHARS] + "\n[…truncado…]"

    subject_line = f"ASSUNTO: {subject}\n\n" if subject else ""
    prompt = PROMPT_TEMPLATE.format(transcript=transcript_text, subject_line=subject_line)

    # Reaproveita summarize() do backend pra fazer call HTTP — mas precisamos
    # passar nosso próprio prompt. Usaremos o método interno _call_with_retry
    # quando disponível, senão SummaryResult.resumo bruto.
    try:
        if hasattr(summ, "_call_with_retry"):
            response_text = summ._call_with_retry(prompt)
        elif hasattr(summ, "_call_ollama"):
            response_text = summ._call_ollama(prompt)
        else:
            return TopicsResult(backend=summ.name, error=f"{summ.name} não suporta prompt customizado")
    except Exception as e:
        return TopicsResult(backend=summ.name, error=f"erro chamando {summ.name}: {e}")

    try:
        data = _extract_json(response_text)
    except (ValueError, json.JSONDecodeError) as e:
        return TopicsResult(backend=summ.name, error=f"JSON inválido: {e}")

    raw_topics = data.get("topicos", [])
    topics: list[Topic] = []
    for t in raw_topics:
        if not isinstance(t, dict):
            continue
        try:
            topics.append(
                Topic(
                    titulo=str(t.get("titulo", "")).strip(),
                    inicio_seconds=float(t.get("inicio_seconds", 0)),
                    fim_seconds=float(t.get("fim_seconds", 0)),
                    retorno_de_topico_anterior=bool(t.get("retorno_de_topico_anterior", False)),
                )
            )
        except (ValueError, TypeError):
            continue

    # Validação básica: filtra inválidos (titulo vazio, fim < inicio)
    topics = [t for t in topics if t.titulo and t.fim_seconds > t.inicio_seconds]

    if not topics:
        return TopicsResult(backend=summ.name, error="nenhum tópico válido extraído")

    return TopicsResult(topics=topics, backend=summ.name)


def _heuristic_extract_topics(result: TranscriptionResult) -> TopicsResult:
    """Segmentação heurística sem LLM.

    Algoritmo simples: divide a duração total em N partes iguais (4-6) e
    rotula cada parte com palavras-chave dominantes nas sentenças do trecho.
    Não detecta retorno de tópicos (LLM é necessário pra isso).
    """
    if not result.segments:
        return TopicsResult(error="transcrição vazia")

    total_dur = result.segments[-1].end if result.segments else 0
    if total_dur < 60:  # < 1min: tópico único
        keywords = _top_keywords(result.segments)
        return TopicsResult(
            topics=[
                Topic(
                    titulo=" / ".join(keywords[:3]) or "Conversa curta",
                    inicio_seconds=result.segments[0].start,
                    fim_seconds=total_dur,
                )
            ],
            backend="heuristic-keywords",
        )

    # Divide em 4-6 partes iguais
    n_parts = min(6, max(3, int(total_dur / 600)))  # ~10min por parte
    boundary_step = total_dur / n_parts

    topics: list[Topic] = []
    for i in range(n_parts):
        start = i * boundary_step
        end = (i + 1) * boundary_step if i < n_parts - 1 else total_dur
        # Pega segmentos dentro do intervalo
        slice_segs = [s for s in result.segments if start <= s.start < end]
        keywords = _top_keywords(slice_segs)
        title = " / ".join(keywords[:3]) or f"Trecho {i + 1}"
        topics.append(
            Topic(
                titulo=title.capitalize(),
                inicio_seconds=start,
                fim_seconds=end,
            )
        )

    return TopicsResult(topics=topics, backend="heuristic-keywords")


def _top_keywords(segments: list[TranscriptionSegment], n: int = 5) -> list[str]:
    """Top N palavras de conteúdo (sem stopwords pt-BR)."""
    from collections import Counter

    stopwords = frozenset(
        """a o e é de da do das dos em na no nas nos para com por que se um uma
        uns umas como mais menos muito pouco já não nem sim ou então mas porque pois
        assim aí ali aqui isso isto aquilo eu tu ele ela nós vós eles elas você vocês
        meu minha seu sua nosso nossa foi foram era ser está estão tem têm tinha vai
        vão pode podem aí lá tá né cara mano gente tipo então""".split()
    )
    text = " ".join(s.text for s in segments).lower()
    words = re.findall(r"\b[\wÀ-ÿ]+\b", text)
    filtered = [w for w in words if w not in stopwords and len(w) > 4]
    return [w for w, _ in Counter(filtered).most_common(n)]


def _extract_json(text: str) -> dict[str, Any]:
    """Extrai dict JSON do texto."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    first = text.find("{")
    last = text.rfind("}")
    if first >= 0 and last > first:
        try:
            return json.loads(text[first : last + 1])
        except json.JSONDecodeError:
            pass
    m = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    if m:
        return json.loads(m.group(1))
    raise ValueError("nenhum JSON encontrado")
