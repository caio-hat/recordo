"""Renomear gravações em ~/Notas/.

Operação atômica:
  1. Calcula novo path baseado na data preservada + safe_subject(novo_assunto)
  2. Se path destino existir, falha (não sobrescreve)
  3. Renomeia diretório (rename atômico se mesmo FS)
  4. Atualiza frontmatter da nota.md (subject) e título H1
  5. Atualiza resumo.md (título)

Não toca em transcricao.txt, transcricao.srt, audio.opus, *_report.md
(são imutáveis por design).

Use cases:
  - Calls que vieram com subject autodetectado genérico ("call_2026-05-26_10h00")
    e o user quer dar nome significativo ("Reunião Product Review")
  - Subject estava errado (autodetect pegou outra janela)
  - User mudou de ideia depois da gravação
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from .config import NOTAS_DIR
from .subject import safe_subject

log = logging.getLogger(__name__)


@dataclass
class RenameResult:
    ok: bool
    old_dir: Path
    new_dir: Path | None = None
    new_subject: str = ""
    error: str = ""
    files_updated: list[str] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.files_updated is None:
            self.files_updated = []


def rename_recording(
    target_dir: Path,
    new_subject: str,
    *,
    notas_dir: Path | None = None,
) -> RenameResult:
    """Renomeia uma gravação em ~/Notas/.

    Args:
      target_dir: caminho atual da gravação (ex: ~/Notas/2026-05-26_call_xyz/)
      new_subject: novo subject humano-legível ("Reunião Product Review")
      notas_dir: parent dir override (default: NOTAS_DIR)

    Returns:
      RenameResult com novo path e arquivos atualizados.
    """
    if notas_dir is None:
        notas_dir = NOTAS_DIR

    target_dir = target_dir.resolve()

    if not target_dir.exists():
        return RenameResult(ok=False, old_dir=target_dir, error="diretório não existe")
    if not target_dir.is_dir():
        return RenameResult(ok=False, old_dir=target_dir, error="não é diretório")

    safe = safe_subject(new_subject.strip())
    if not safe or safe == "Gravacao":
        return RenameResult(
            ok=False,
            old_dir=target_dir,
            error="novo assunto inválido ou vazio após sanitização",
        )

    # Extrai a data do nome atual (formato YYYY-MM-DD_<oldsafe>)
    name = target_dir.name
    date_match = re.match(r"^(\d{4}-\d{2}-\d{2})_(.+)$", name)
    if date_match:
        date_str = date_match.group(1)
        new_name = f"{date_str}_{safe}"
    else:
        # Sem prefixo de data — preservamos mas só renomeamos a parte do subject
        new_name = safe

    new_dir = target_dir.parent / new_name

    # Edge case: subject novo == subject atual (idempotente)
    if new_dir == target_dir:
        return RenameResult(
            ok=True,
            old_dir=target_dir,
            new_dir=new_dir,
            new_subject=new_subject,
            files_updated=[],
        )

    if new_dir.exists():
        return RenameResult(
            ok=False,
            old_dir=target_dir,
            error=f"destino já existe: {new_dir}",
        )

    # Atomic rename do diretório (instant em mesmo FS, copy+rm em cross-FS)
    try:
        target_dir.rename(new_dir)
    except OSError as e:
        return RenameResult(ok=False, old_dir=target_dir, error=f"falha ao renomear diretório: {e}")

    log.info("renomeado: %s → %s", target_dir.name, new_dir.name)
    files_updated: list[str] = []

    # Atualiza frontmatter + H1 da nota.md
    nota_md = new_dir / "nota.md"
    if nota_md.exists():
        try:
            content = nota_md.read_text(encoding="utf-8")
            updated = _update_nota_md(content, new_subject)
            if updated != content:
                nota_md.write_text(updated, encoding="utf-8")
                files_updated.append("nota.md")
        except OSError as e:
            log.warning("nota.md não atualizada: %s", e)

    # Atualiza título do resumo.md (se existir)
    resumo_md = new_dir / "resumo.md"
    if resumo_md.exists():
        try:
            content = resumo_md.read_text(encoding="utf-8")
            new_content = re.sub(
                r"^# Resumo — .+$",
                f"# Resumo — {new_dir.name}",
                content,
                count=1,
                flags=re.M,
            )
            if new_content != content:
                resumo_md.write_text(new_content, encoding="utf-8")
                files_updated.append("resumo.md")
        except OSError as e:
            log.warning("resumo.md não atualizado: %s", e)

    return RenameResult(
        ok=True,
        old_dir=target_dir,
        new_dir=new_dir,
        new_subject=new_subject,
        files_updated=files_updated,
    )


def _update_nota_md(content: str, new_subject: str) -> str:
    """Atualiza linhas `subject:` no frontmatter e # H1 da nota."""
    # Frontmatter: linha "subject: ..."
    content = re.sub(
        r"^subject:\s*.*$",
        f"subject: {new_subject}",
        content,
        count=1,
        flags=re.M,
    )
    # H1: primeira linha começando com `# ` (não `## `)
    content = re.sub(
        r"^# (?!#).+$",
        f"# {new_subject}",
        content,
        count=1,
        flags=re.M,
    )
    return content


def find_recording(name_or_path: str, *, notas_dir: Path | None = None) -> Path | None:
    """Resolve string (path ou nome) → diretório existente em ~/Notas/.

    Aceita:
      - Path absoluto: /home/user/Notas/<dir>
      - Path relativo: ./<dir>
      - Nome do diretório direto: 2026-05-26_call_x
      - Substring que matche um único diretório existente

    Retorna None se não encontrar ou ambíguo.
    """
    if notas_dir is None:
        notas_dir = NOTAS_DIR

    # Tenta como path direto
    p = Path(name_or_path).expanduser()
    if p.is_absolute() and p.exists():
        return p
    # Path relativo a CWD
    if p.exists():
        return p.resolve()
    # Nome direto em ~/Notas/
    direct = notas_dir / name_or_path
    if direct.exists():
        return direct
    # Busca substring em diretórios existentes
    if notas_dir.exists():
        matches = [d for d in notas_dir.iterdir() if d.is_dir() and name_or_path in d.name]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            log.warning(
                "ambíguo: %d diretórios casam '%s' — %s",
                len(matches),
                name_or_path,
                [m.name for m in matches],
            )
    return None
