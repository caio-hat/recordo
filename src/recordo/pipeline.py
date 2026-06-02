"""Pós-pipeline: mover áudio pra ~/Notas, gerar nota.md, transcrever (lazy)."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import NOTAS_DIR, Timeouts, load_config
from .notify import notify
from .recorder import Mark, SessionState
from .subject import safe_subject
from .summarizer import SummaryResult
from .transcribers import TranscriptionResult, get_transcriber

log = logging.getLogger(__name__)

WHISPER_PKGS = ["faster-whisper>=1.0"]
PLACEHOLDER = "_(processando — esta seção é preenchida quando o backend terminar)_"
SUMMARY_PLACEHOLDER = "_(resumo será gerado após a transcrição)_"
TOPICS_PLACEHOLDER = "_(assuntos serão identificados após a transcrição)_"


class _PipelineStatusStore:
    """Thread-safe store for pipeline async status, with size cap (B4).

    Indexed by target_dir.name. Maintains insertion order via dict() in
    Python 3.7+; clear_old() drops oldest entries beyond `keep_last`.
    """

    def __init__(self, keep_last: int = 20) -> None:
        self._data: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self.keep_last = keep_last

    def set(self, target_name: str, status: dict[str, Any]) -> None:
        with self._lock:
            self._data[target_name] = status

    def get(self, target_name: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._data.get(target_name, {}))

    def clear_old(self, *, keep_last: int | None = None) -> int:
        """Drop oldest entries beyond keep_last. Returns # of dropped entries."""
        n_keep = keep_last if keep_last is not None else self.keep_last
        with self._lock:
            if len(self._data) <= n_keep:
                return 0
            keys = list(self._data.keys())
            to_remove = keys[: len(keys) - n_keep]
            for k in to_remove:
                del self._data[k]
            return len(to_remove)

    def size(self) -> int:
        with self._lock:
            return len(self._data)

    def clear(self) -> None:
        """Wipe all entries (test/diagnostic helper)."""
        with self._lock:
            self._data.clear()


# Singleton store. Replaces the previous global dict.
_PIPELINE_STATUS_STORE = _PipelineStatusStore(keep_last=20)


def _safe_move(src: Path, dst: Path) -> None:
    """Move detectando cross-filesystem.

    Em mesmo FS: rename atômico (instantâneo).
    Cross-FS: shutil.move faz copy+unlink — pode demorar; logamos warning
    explícito pra debug se um move grande aparecer durante stop.
    """
    try:
        src_dev = src.stat().st_dev
        dst_dev = dst.parent.stat().st_dev
        if src_dev != dst_dev:
            size_mb = src.stat().st_size / (1024 * 1024)
            log.warning(
                "cross-filesystem move: %s → %s (%.1fMB, copy+unlink)",
                src,
                dst,
                size_mb,
            )
    except FileNotFoundError as e:
        # B15: log explícito em vez de silently passing
        log.warning("safe_move: stat falhou (%s) — tentando move mesmo assim", e)
    shutil.move(str(src), str(dst))


def transcribe(audio_path: Path, *, model_size: str = "large-v3-turbo", language: str = "pt") -> Path:
    """[legacy] Transcreve com Whisper. Mantida pra compat.

    Novo código deve usar `get_transcriber(...).transcribe(audio)` →
    `TranscriptionResult.write_txt/write_srt`.
    """
    transcriber = get_transcriber("whisper", {"whisper": {"model": model_size}})
    result = transcriber.transcribe(audio_path, language=language)
    txt_out = audio_path.parent / "transcricao.txt"
    srt_out = audio_path.parent / "transcricao.srt"
    result.write_txt(txt_out)
    result.write_srt(srt_out)
    return txt_out


def ensure_whisper_installed() -> bool:
    """Verifica + instala faster-whisper no venv corrente, se faltar."""
    try:
        import faster_whisper  # noqa: F401

        return True
    except ImportError:
        pass
    log.info("instalando faster-whisper (lazy) — pode demorar na 1ª vez")
    uv = shutil.which("uv")
    cmd = (
        [uv, "pip", "install", "--python", sys.executable, *WHISPER_PKGS]
        if uv
        else [sys.executable, "-m", "pip", "install", *WHISPER_PKGS]
    )
    try:
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        import importlib

        importlib.invalidate_caches()
        return True
    except subprocess.CalledProcessError as e:
        log.error("falha ao instalar faster-whisper: %s", e)
        return False


def _format_mark(m: Mark) -> str:
    h, m_, s = int(m.ts_seconds // 3600), int((m.ts_seconds % 3600) // 60), int(m.ts_seconds % 60)
    return f"- [{h:02d}:{m_:02d}:{s:02d}] {m.text or '(marca)'}"


def _render_nota_md(
    state: SessionState, marks: list[Mark], target_dir: Path, backend_name: str = "pending"
) -> None:
    """Gera nota.md inicial com placeholder. Backend nome ajustado depois."""
    duration_min = sum(s.duration for s in state.segments) / 60
    marks_block = "\n".join(_format_mark(m) for m in marks) or "_(nenhuma marca registrada)_"
    nota_md = target_dir / "nota.md"
    nota_md.write_text(
        f"""---
subject: {state.subject}
date: {state.started_at}
duration_min: {duration_min:.1f}
audio: ./audio.opus
transcricao: ./transcricao.txt
segments: {len(state.segments)}
auto_started: {state.auto_started}
backend: {backend_name}
transcription_status: pending
tags: [reuniao]
---

# {state.subject}

## Assuntos da Conversa

{TOPICS_PLACEHOLDER}

## Resumo

{SUMMARY_PLACEHOLDER}

## Marcas durante gravação

{marks_block}

## Notas manuais


## Transcrição

{PLACEHOLDER}
""",
        encoding="utf-8",
    )


def post_pipeline(
    state: SessionState,
    final_audio: Path,
    marks: list[Mark],
    *,
    config: dict[str, Any] | None = None,
    whisper_model: str | None = None,  # backward-compat
    language: str | None = None,
) -> Path | None:
    """Move áudio pra ~/Notas/, gera nota.md, spawn transcrição em thread.

    Backend de transcrição escolhido por `config['transcriber']['backend']`
    (default config.toml: whisper). Argumentos kwargs legacy ainda funcionam.
    """
    if not final_audio or not final_audio.exists():
        return None

    cfg = config if config is not None else load_config()
    transcriber_cfg = cfg.get("transcriber", {})
    backend = transcriber_cfg.get("backend", "whisper")
    lang = language or transcriber_cfg.get("language", "pt")

    # backward-compat: parâmetro antigo whisper_model sobrescreve
    if whisper_model:
        transcriber_cfg.setdefault("whisper", {})["model"] = whisper_model

    date_str = datetime.fromisoformat(state.started_at).strftime("%Y-%m-%d")
    safe = safe_subject(state.subject)
    target_dir = NOTAS_DIR / f"{date_str}_{safe}"
    target_dir.mkdir(parents=True, exist_ok=True)

    audio_dst = target_dir / "audio.opus"
    _safe_move(final_audio, audio_dst)

    src_dir = Path(state.output_dir)
    for extra in src_dir.glob("*_report.md"):
        _safe_move(extra, target_dir / extra.name)

    nota_md = target_dir / "nota.md"
    _render_nota_md(state, marks, target_dir, backend_name=backend)

    summarizer_cfg = cfg.get("summarizer")
    # Status dict partilhado pra que callers (ex: rerun-pipeline) possam
    # detectar erros assíncronos via join + check.
    pipeline_status: dict[str, Any] = {}
    _PIPELINE_STATUS_STORE.set(target_dir.name, pipeline_status)

    threading.Thread(
        target=_transcribe_async,
        args=(audio_dst, nota_md, backend, transcriber_cfg, lang, target_dir),
        kwargs={
            "summarizer_cfg": summarizer_cfg,
            "subject": state.subject,
            "status": pipeline_status,
            "marks": marks,
        },
        daemon=False,
        name="recordo-transcribe",
    ).start()
    return target_dir


def get_pipeline_status(target_dir: Path) -> dict[str, Any]:
    """Lê o status atual do pipeline de uma sessão pós-pipeline.

    Status keys:
      'ok' (bool): True se transcrição+resumo concluíram sem erro
      'transcriber' (str): backend usado (após fallback automático)
      'summary_backend' (str): summarizer usado (após fallback)
      'error' (str): mensagem se algo falhou
    """
    return _PIPELINE_STATUS_STORE.get(target_dir.name)


def _resolve_backend_with_fallback(backend: str, transcriber_cfg: dict[str, Any]) -> str | None:
    """B13: helper para fallback automático parakeet→whisper.

    Returns the backend to actually use, or None if no usable backend.
    Side effects: emits notify on fallback, updates transcriber_cfg.
    """
    if backend == "parakeet":
        try:
            import nemo.collections.asr  # noqa: F401
        except ImportError:
            log.warning(
                "parakeet config'd mas nemo não instalado — "
                "fallback automático para whisper "
                "(instale com setup.sh --with-parakeet)"
            )
            notify(
                "⚠ Parakeet indisponível",
                "Usando Whisper como fallback. Para Parakeet: setup.sh --with-parakeet",
                urgency="normal",
            )
            backend = "whisper"
            transcriber_cfg.setdefault("whisper", {})

    if backend == "whisper" and not ensure_whisper_installed():
        notify(
            "⚠️ Transcrição indisponível",
            "faster-whisper não instalado. Áudio em ~/Notas/.",
            urgency="critical",
        )
        return None

    return backend


def _run_transcription(
    audio_dst: Path,
    nota_md: Path,
    backend: str,
    transcriber_cfg: dict[str, Any],
    language: str,
    marks: list[Mark] | None,
) -> TranscriptionResult | None:
    """B13: roda transcrição + escreve transcricao.txt/.srt + atualiza status.

    Returns TranscriptionResult on success, None on transcriber unavailability.
    Raises on transcribe() failure (caller handles).
    """
    actual_backend = _resolve_backend_with_fallback(backend, transcriber_cfg)
    if actual_backend is None:
        return None

    transcriber = get_transcriber(actual_backend, transcriber_cfg)
    result = transcriber.transcribe(audio_dst, language=language)
    _write_result(audio_dst, nota_md, result, marks=marks)
    _set_transcription_status(nota_md, "done")
    return result


def _run_topics(
    result: TranscriptionResult,
    nota_md: Path,
    target_dir: Path,
    subject: str,
    summarizer_cfg: dict[str, Any],
) -> str:
    """B13: extrai e embeda tópicos. Returns backend name used."""
    from .topics import extract_topics

    topics_result = extract_topics(result, subject=subject, summarizer_cfg=summarizer_cfg)
    _embed_topics(nota_md, topics_result)
    _write_topics_json(target_dir, topics_result)
    return topics_result.backend


def _run_summary_step(
    result: TranscriptionResult,
    nota_md: Path,
    target_dir: Path,
    subject: str,
    summarizer_cfg: dict[str, Any],
    language: str,
) -> str:
    """B13: gera e embeda resumo. Returns backend name used."""
    summary = _generate_summary(
        result.text,
        subject=subject,
        summarizer_cfg=summarizer_cfg,
        language=language,
    )
    _embed_summary(nota_md, summary)
    _write_summary_md(target_dir, summary)
    return summary.backend


def _transcribe_async(
    audio_dst: Path,
    nota_md: Path,
    backend: str,
    transcriber_cfg: dict[str, Any],
    language: str,
    target_dir: Path,
    summarizer_cfg: dict[str, Any] | None = None,
    subject: str = "",
    status: dict[str, Any] | None = None,
    marks: list[Mark] | None = None,
) -> None:
    """Worker thread coordenando transcribe → topics → summary.

    `status` é dict partilhado com caller (preenchemos 'ok', 'transcriber',
    'summary_backend', 'topics_backend', 'error'). Pipeline status store
    é limpo (clear_old) ao final para evitar memory growth indefinido (B4).
    """
    if status is None:
        status = {}
    try:
        # Step 1: Transcribe
        result = _run_transcription(audio_dst, nota_md, backend, transcriber_cfg, language, marks)
        if result is None:
            status["error"] = "transcrição indisponível"
            return
        status["transcriber"] = result.backend
        notify(
            "✓ Transcrição pronta",
            f"~/Notas/{target_dir.name}/ — gerando resumo…",
            icon="document-edit",
            transient=True,
        )

        # Step 2: Topics + Summary (only if summarizer configured)
        if summarizer_cfg is not None:
            status["topics_backend"] = _run_topics(result, nota_md, target_dir, subject, summarizer_cfg)
            status["summary_backend"] = _run_summary_step(
                result, nota_md, target_dir, subject, summarizer_cfg, language
            )
            notify(
                "✓ Nota completa",
                f"~/Notas/{target_dir.name}/",
                icon="document-edit",
                transient=True,
            )

        status["ok"] = True
    except Exception as e:
        log.exception("falha transcrição/resumo async: %s", e)
        status["error"] = str(e)[:200]
        _set_transcription_status(nota_md, "error")
        notify("⚠️ Erro pipeline", str(e)[:120], urgency="critical")
    finally:
        # B4: cap status store size to avoid unbounded growth
        n_dropped = _PIPELINE_STATUS_STORE.clear_old()
        if n_dropped:
            log.debug("pipeline status store: dropped %d old entries", n_dropped)


def _generate_summary(
    transcript_text: str,
    *,
    subject: str,
    summarizer_cfg: dict[str, Any],
    language: str = "pt",
) -> SummaryResult:
    """Gera resumo com cascata de fallbacks.

    Cascata padrão (configurável):
      1. Provider primário (config['backend'])
      2. Se cloud falhou e config['fallback_to_local']=True (default): tenta ollama
      3. Se ollama falhou e config['fallback_to_heuristic']=True (default): tenta heuristic

    `backend` no config['backend']:
      ollama | gemini | openai | openai_compat | anthropic | azure_openai
      | heuristic | none

    Marca origem do fallback no `result.backend` ("X (fallback de Y)").
    """
    from .summarizer import get_summarizer
    from .summarizer.base import NoOpSummarizer

    backend_name = summarizer_cfg.get("backend", "ollama")
    if backend_name == "none":
        return NoOpSummarizer().summarize(transcript_text, language=language, subject=subject)

    primary = get_summarizer(backend_name, summarizer_cfg)
    log.info("gerando resumo com %s", primary.name)
    result = primary.summarize(transcript_text, language=language, subject=subject)

    if not result.error:
        return result

    # Fallback 1: cloud → ollama (se backend primário não era ollama)
    cloud_backends = {"gemini", "openai", "openai_compat", "anthropic", "azure_openai"}
    if backend_name in cloud_backends and summarizer_cfg.get("fallback_to_local", True):
        log.warning("%s falhou (%s) — tentando ollama como fallback local", primary.name, result.error)
        ollama_summ = get_summarizer("ollama", summarizer_cfg)
        ollama_result = ollama_summ.summarize(transcript_text, language=language, subject=subject)
        if not ollama_result.error:
            ollama_result.backend = f"{ollama_result.backend} (fallback de {primary.name})"
            return ollama_result
        # ollama falhou também → próximo fallback
        log.warning("ollama também falhou (%s)", ollama_result.error)
        result = ollama_result

    # Fallback 2: heuristic (sempre disponível, sem deps)
    if summarizer_cfg.get("fallback_to_heuristic", True):
        log.warning("último fallback: heuristic")
        fallback = get_summarizer("heuristic", summarizer_cfg)
        heuristic_result = fallback.summarize(transcript_text, language=language, subject=subject)
        if not heuristic_result.error:
            heuristic_result.backend = f"{heuristic_result.backend} (fallback de {primary.name})"
            return heuristic_result

    return result


def _write_result(
    audio_dst: Path,
    nota_md: Path,
    result: TranscriptionResult,
    marks: list[Mark] | None = None,
) -> None:
    """Persiste arquivos de transcrição e atualiza nota.md.

    Se marks forem passadas, interleava elas no transcricao.txt no timestamp
    correto — ex: `[📍 02:05] decisão importante` entre as linhas dos segments.
    """
    txt_out = audio_dst.parent / "transcricao.txt"
    srt_out = audio_dst.parent / "transcricao.srt"
    result.write_txt(txt_out)
    result.write_srt(srt_out)

    # Interleave marks no txt se fornecidas
    if marks:
        _interleave_marks_into_txt(txt_out, marks)

    nota = nota_md.read_text(encoding="utf-8")
    embedded = _format_transcript_for_nota(result, marks=marks)
    nota = nota.replace(PLACEHOLDER, embedded)
    # atualiza linha backend no frontmatter se já existir
    if "backend:" in nota:
        nota = re.sub(r"^backend:.*$", f"backend: {result.backend}", nota, count=1, flags=re.M)
    nota_md.write_text(nota, encoding="utf-8")


def _format_transcript_for_nota(
    result: TranscriptionResult,
    *,
    marks: list[Mark] | None = None,
    gap_threshold_seconds: float = 3.0,
    max_chars_per_paragraph: int = 600,
) -> str:
    """Renderiza segments como parágrafos com timestamps no início.

    Agrupa segments consecutivos em parágrafos quebrando quando:
      - O gap (silêncio) entre segments excede `gap_threshold_seconds`
      - O parágrafo já passou de `max_chars_per_paragraph`

    Marks são interleaveadas no timestamp correspondente como `📍 mm:ss · texto`.

    Formato: cada parágrafo começa com `**[mm:ss]**` em negrito, depois o texto
    fluido. Resultado é legível e MUITO mais compacto que o bloco com timestamps
    por segment.
    """
    if not result.segments:
        return "_(transcrição vazia)_"

    sorted_marks = sorted(marks or [], key=lambda m: m.ts_seconds)
    pending_marks = list(sorted_marks)

    paragraphs: list[tuple[float, str]] = []  # (start_seconds, texto)
    current_start: float | None = None
    current_text: list[str] = []

    def _flush() -> None:
        if current_text and current_start is not None:
            paragraphs.append((current_start, " ".join(current_text).strip()))

    prev_end = 0.0
    for seg in result.segments:
        text = seg.text.strip()
        if not text:
            continue

        # Insere marks que vieram antes deste segment
        while pending_marks and pending_marks[0].ts_seconds <= seg.start:
            mk = pending_marks.pop(0)
            if current_text:
                _flush()
                current_start = None
                current_text = []
            mk_text = mk.text.strip() or "(marca)"
            paragraphs.append((mk.ts_seconds, f"**📍 MARCA:** {mk_text}"))

        # Decide se quebra parágrafo: gap longo OU caracteres excedidos
        gap = seg.start - prev_end
        current_total = sum(len(t) for t in current_text) + len(text)
        if current_text and (gap > gap_threshold_seconds or current_total > max_chars_per_paragraph):
            _flush()
            current_start = None
            current_text = []

        if current_start is None:
            current_start = seg.start
        current_text.append(text)
        prev_end = seg.end

    _flush()

    # Marks restantes (após o último segment)
    while pending_marks:
        mk = pending_marks.pop(0)
        mk_text = mk.text.strip() or "(marca)"
        paragraphs.append((mk.ts_seconds, f"**📍 MARCA:** {mk_text}"))

    # Renderiza
    lines: list[str] = []
    for start, text in paragraphs:
        ts = _format_mark_ts(start)
        if text.startswith("**📍 MARCA:**"):
            lines.append(text)
        else:
            lines.append(f"**[{ts}]** {text}")
        lines.append("")  # linha em branco entre parágrafos

    return "\n".join(lines).strip() + "\n"


def _interleave_marks_into_txt(txt_path: Path, marks: list[Mark]) -> None:
    """Insere linhas '[📍 mm:ss] texto da marca' no transcricao.txt nos pontos certos.

    Estratégia: lê o txt linha-a-linha, parseia '[start → end]' de cada,
    insere marks ANTES da primeira linha cujo start >= mark.ts_seconds.
    """
    if not marks or not txt_path.exists():
        return

    sorted_marks = sorted(marks, key=lambda m: m.ts_seconds)
    pending = list(sorted_marks)

    out_lines: list[str] = []
    for line in txt_path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\[\s*([\d.]+)\s+→\s+[\d.]+\]", line)
        if m:
            line_start = float(m.group(1))
            # Insere todas as marks que vieram antes desta linha
            while pending and pending[0].ts_seconds <= line_start:
                mk = pending.pop(0)
                ts_str = _format_mark_ts(mk.ts_seconds)
                text = mk.text.strip() or "(marca)"
                out_lines.append(f"[📍 {ts_str}] {text}")
        out_lines.append(line)

    # Marks sem segment correspondente após o final
    while pending:
        mk = pending.pop(0)
        ts_str = _format_mark_ts(mk.ts_seconds)
        text = mk.text.strip() or "(marca)"
        out_lines.append(f"[📍 {ts_str}] {text}")

    txt_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")


def _format_mark_ts(seconds: float) -> str:
    """Segundos → mm:ss ou hh:mm:ss."""
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


def _embed_summary(nota_md: Path, summary: Any) -> None:
    """Substitui SUMMARY_PLACEHOLDER em nota.md pelo bloco markdown do resumo.

    Atualiza também a linha `summarizer:` no frontmatter (adiciona se ausente).
    """
    nota = nota_md.read_text(encoding="utf-8")
    md_block = summary.to_markdown()

    if SUMMARY_PLACEHOLDER in nota:
        nota = nota.replace(SUMMARY_PLACEHOLDER, md_block.rstrip())
    else:
        # Nota sem placeholder (re-rodada): substitui bloco "## Resumo" existente
        # até a próxima `## ` (Marcas) ou fim
        if re.search(r"^## Resumo\b", nota, flags=re.M):
            nota = re.sub(
                r"## Resumo\s*\n+(?:.*?\n)*?(?=## |\Z)",
                f"## Resumo\n\n{md_block.rstrip()}\n\n",
                nota,
                count=1,
                flags=re.DOTALL | re.M,
            )
        else:
            # Nota sem seção Resumo (formato antigo): insere antes de `## Marcas`
            nota = re.sub(
                r"^(## Marcas)",
                f"## Resumo\n\n{md_block.rstrip()}\n\n\\1",
                nota,
                count=1,
                flags=re.M,
            )

    # Frontmatter: atualiza/adiciona summarizer:
    if re.search(r"^summarizer:.*$", nota, flags=re.M):
        nota = re.sub(
            r"^summarizer:.*$",
            f"summarizer: {summary.backend or 'none'}",
            nota,
            count=1,
            flags=re.M,
        )
    elif "backend:" in nota:
        nota = re.sub(
            r"^(backend:.*)$",
            f"\\1\nsummarizer: {summary.backend or 'none'}",
            nota,
            count=1,
            flags=re.M,
        )

    nota_md.write_text(nota, encoding="utf-8")


def _write_summary_md(target_dir: Path, summary: Any) -> None:
    """Salva resumo.md standalone (útil pra grep/scripts externos)."""
    if summary.is_empty and not summary.error:
        return
    (target_dir / "resumo.md").write_text(
        f"# Resumo — {target_dir.name}\n\n{summary.to_markdown()}",
        encoding="utf-8",
    )


def _embed_topics(nota_md: Path, topics_result: Any) -> None:
    """Substitui TOPICS_PLACEHOLDER em nota.md pelo bloco markdown dos tópicos.

    Atualiza linha `topics_backend:` no frontmatter (adiciona se ausente).
    """
    nota = nota_md.read_text(encoding="utf-8")
    md_block = topics_result.to_markdown()

    if TOPICS_PLACEHOLDER in nota:
        nota = nota.replace(TOPICS_PLACEHOLDER, md_block.rstrip())
    else:
        # Nota sem placeholder (re-rodada): substitui bloco "## Assuntos" existente
        # até a próxima `## ` (Resumo) ou EOF
        if re.search(r"^## Assuntos da Conversa\b", nota, flags=re.M):
            nota = re.sub(
                r"## Assuntos da Conversa\s*\n+(?:.*?\n)*?(?=## |\Z)",
                f"## Assuntos da Conversa\n\n{md_block.rstrip()}\n\n",
                nota,
                count=1,
                flags=re.DOTALL | re.M,
            )
        else:
            # Insere antes de `## Resumo` (formato antigo sem topics)
            nota = re.sub(
                r"^(## Resumo)",
                f"## Assuntos da Conversa\n\n{md_block.rstrip()}\n\n\\1",
                nota,
                count=1,
                flags=re.M,
            )

    # Frontmatter: atualiza/adiciona topics_backend:
    if re.search(r"^topics_backend:.*$", nota, flags=re.M):
        nota = re.sub(
            r"^topics_backend:.*$",
            f"topics_backend: {topics_result.backend or 'none'}",
            nota,
            count=1,
            flags=re.M,
        )
    elif "summarizer:" in nota:
        nota = re.sub(
            r"^(summarizer:.*)$",
            f"\\1\ntopics_backend: {topics_result.backend or 'none'}",
            nota,
            count=1,
            flags=re.M,
        )
    elif "backend:" in nota:
        nota = re.sub(
            r"^(backend:.*)$",
            f"\\1\ntopics_backend: {topics_result.backend or 'none'}",
            nota,
            count=1,
            flags=re.M,
        )

    nota_md.write_text(nota, encoding="utf-8")


def _write_topics_json(target_dir: Path, topics_result: Any) -> None:
    """Salva topics.json standalone (úteis pra plotar timeline visual ou scripts)."""
    if topics_result.is_empty and not topics_result.error:
        return
    (target_dir / "topics.json").write_text(topics_result.to_json(), encoding="utf-8")


def _set_transcription_status(nota_md: Path, status: str) -> None:
    """Atualiza linha transcription_status no frontmatter da nota.md.

    Status válidos: pending | done | error
    Idempotente — adiciona linha se ausente, atualiza se existe.
    """
    if not nota_md.exists():
        return
    try:
        content = nota_md.read_text(encoding="utf-8")
    except OSError:
        return

    if re.search(r"^transcription_status:.*$", content, flags=re.M):
        new = re.sub(
            r"^transcription_status:.*$",
            f"transcription_status: {status}",
            content,
            count=1,
            flags=re.M,
        )
    elif "backend:" in content:
        new = re.sub(
            r"^(backend:.*)$",
            f"\\1\ntranscription_status: {status}",
            content,
            count=1,
            flags=re.M,
        )
    else:
        return  # frontmatter malformado, skip

    if new != content:
        nota_md.write_text(new, encoding="utf-8")


def retranscribe(
    target_dir: Path,
    *,
    backend: str = "whisper",
    transcriber_cfg: dict[str, Any] | None = None,
    language: str = "pt",
    summarizer_cfg: dict[str, Any] | None = None,
    subject: str | None = None,
) -> TranscriptionResult:
    """Re-transcreve uma gravação existente em ~/Notas/ com outro backend.

    Usado pela GUI Page Transcribe. Sobrescreve transcricao.{txt,srt} e nota.md.
    Se summarizer_cfg fornecido, regenera o resumo também.
    """
    audio = target_dir / "audio.opus"
    if not audio.exists():
        raise FileNotFoundError(f"audio.opus ausente em {target_dir}")
    nota_md = target_dir / "nota.md"
    if not nota_md.exists():
        raise FileNotFoundError(f"nota.md ausente em {target_dir}")

    transcriber = get_transcriber(backend, transcriber_cfg or {})
    result = transcriber.transcribe(audio, language=language)

    # Restaura placeholder pra _write_result substituir corretamente
    nota = nota_md.read_text(encoding="utf-8")
    if PLACEHOLDER not in nota:
        # já tinha transcrição antiga — remove bloco ``` ``` final pra substituir
        nota = re.sub(
            r"## Transcrição\s*\n+```.*?```\s*$",
            f"## Transcrição\n\n{PLACEHOLDER}\n",
            nota,
            flags=re.DOTALL,
        )
        nota_md.write_text(nota, encoding="utf-8")

    _write_result(audio, nota_md, result)

    # Resumo opcional
    if summarizer_cfg is not None:
        # Subject vem do parâmetro ou do nome do diretório (formato YYYY-MM-DD_<safe>)
        if subject is None:
            name = target_dir.name
            # remove prefix "YYYY-MM-DD_"
            subject = re.sub(r"^\d{4}-\d{2}-\d{2}_", "", name).replace("_", " ")
        summary = _generate_summary(
            result.text,
            subject=subject,
            summarizer_cfg=summarizer_cfg,
            language=language,
        )
        _embed_summary(nota_md, summary)
        _write_summary_md(target_dir, summary)

    log.info("re-transcrição completa: %s (%s)", target_dir.name, result.backend)
    return result


def rerun_pipeline_for_session(
    session_dir: Path,
    *,
    wait_for_transcribe: bool = True,
    config: dict[str, Any] | None = None,
) -> Path | None:
    """Recovery: re-roda post_pipeline numa sessão em ~/recordings/.

    Útil quando o concat final ficou truncado (caso comum: -c copy com
    Opus + reset de PTS) ou quando o post_pipeline morreu silenciosamente
    e ~/Notas/<data>_<assunto>/ não foi criado.

    Operação:
      1. Carrega SessionState do session.json
      2. Regenera o concat final via _concat_list.txt + ffmpeg -c copy.
         Faz sanity check duração; se truncado, retry com reencode libopus.
      3. Chama post_pipeline normalmente.
      4. Se wait_for_transcribe=True, faz join na thread de transcrição.

    Retorna o target_dir em ~/Notas/ ou None se falhou.
    """
    from .recorder import SessionState  # tardio pra evitar ciclo

    state = SessionState.load(session_dir)
    valid_segs = [s for s in state.segments if s.status == "merged"]
    if not valid_segs:
        log.error("rerun: nenhum segmento merged em %s", session_dir)
        return None

    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", state.subject).strip("_") or "Gravacao"
    final = session_dir / f"{safe}_{state.session_id}.opus"
    list_file = session_dir / "_concat_list.txt"

    # Regenera _concat_list.txt + final com -c copy primeiro
    list_file.write_text("".join(f"file '{Path(s.merged_file).as_posix()}'\n" for s in valid_segs))
    expected_dur = sum(s.duration for s in valid_segs)
    if not _ffmpeg_concat(list_file, final, reencode=False):
        return None

    # Sanity check
    actual = _ffprobe_duration(final)
    if actual is not None and actual < expected_dur * 0.5:
        log.warning(
            "rerun: concat -c copy truncou (%.1fs/%.1fs) — retry reencode",
            actual,
            expected_dur,
        )
        if not _ffmpeg_concat(list_file, final, reencode=True, bitrate=state.bitrate):
            return None
        actual = _ffprobe_duration(final)

    log.info("rerun: concat OK (%.1fs)", actual or 0)

    # Agora chama post_pipeline com a sessão recuperada
    target = post_pipeline(state, final, state.marks, config=config)
    if target is None:
        return None

    if wait_for_transcribe:
        # Join na thread "recordo-transcribe" pra esperar a transcrição
        for t in threading.enumerate():
            if t.name == "recordo-transcribe" and t.is_alive():
                log.info("rerun: aguardando transcrição (thread %s)", t.name)
                t.join()
                break

        # Checa status — propaga erro mesmo que o concat tenha funcionado
        status = get_pipeline_status(target)
        if status.get("error"):
            log.error("rerun: pipeline com erro: %s", status["error"])
            return None
        if not status.get("ok"):
            log.warning("rerun: pipeline finalizou sem flag ok (status=%s)", status)

    return target


def _ffmpeg_concat(list_file: Path, output: Path, *, reencode: bool, bitrate: str = "32k") -> bool:
    """Helper: roda ffmpeg concat. Retorna True/False."""
    base = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
    ]
    if reencode:
        cmd = [*base, "-c:a", "libopus", "-b:a", bitrate, "-application", "voip", "-y", str(output)]
    else:
        cmd = [*base, "-c", "copy", "-y", str(output)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return True
    except subprocess.CalledProcessError as e:
        log.error("ffmpeg concat falhou (reencode=%s): %s", reencode, e.stderr)
        return False


def _ffprobe_duration(path: Path) -> float | None:
    """Helper: ffprobe duração em segundos."""
    try:
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=Timeouts.FFPROBE_TIMEOUT_SEC,
            check=True,
        )
        return float(r.stdout.strip())
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError, FileNotFoundError):
        return None
