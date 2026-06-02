"""Tasks extractor: extrai action items / tarefas / decisões com prazos.

Usa o mesmo summarizer factory existente (qualquer backend serve), mas com
prompt específico que produz lista de tarefas em formato markdown checkbox.

Saída:
- `tasks.md` no target_dir com lista de tarefas
- Seção "## Tarefas" embedada em `nota.md`

Estrutura cada tarefa:
  - [ ] [responsável?] descrição da tarefa (prazo se mencionado)

Exemplo:
  - [ ] @joao fazer deploy de staging (até sexta)
  - [ ] revisar PR #1234 do Acme (sem prazo)
  - [ ] decidir sobre migração K8s (próxima sprint)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from . import get_summarizer

log = logging.getLogger(__name__)


PROMPT_TEMPLATE = """Você é um assistente que extrai tarefas e action items de transcrições de reuniões.

Analise a transcrição abaixo e extraia tarefas concretas (action items, decisões, follow-ups).

Retorne APENAS JSON com a chave "tarefas", array de objetos:
{{
  "tarefas": [
    {{
      "descricao": "string clara descrevendo a tarefa",
      "responsavel": "nome ou null",
      "prazo": "data/marco temporal ou null",
      "tipo": "task" | "decisao" | "followup"
    }},
    ...
  ]
}}

Regras:
- Extraia APENAS tarefas concretas mencionadas explicitamente — não invente
- Tarefas devem ser acionáveis (fazer X, decidir Y, contatar Z)
- "responsavel": nome próprio se mencionado, null se não claro
- "prazo": expressão temporal exata ("até sexta", "próxima sprint", "em 2 semanas"), null se não mencionado
- "tipo": "task" (ação a fazer), "decisao" (decisão tomada), "followup" (acompanhamento)
- Se não há tarefas claras, retorne {{"tarefas": []}}

{subject_line}TRANSCRIÇÃO:
\"\"\"
{transcript}
\"\"\"
"""


@dataclass
class TaskItem:
    """Uma tarefa individual extraída."""

    descricao: str
    responsavel: str | None = None
    prazo: str | None = None
    tipo: str = "task"  # task | decisao | followup

    def to_markdown_line(self) -> str:
        """Renderiza como linha checkbox markdown."""
        prefix = "- [ ]"
        if self.tipo == "decisao":
            prefix = "- [x]"  # decisão = já feita

        parts = [prefix]
        if self.responsavel:
            parts.append(f"**@{self.responsavel}**")

        # Tag visual para tipo
        tag_emoji = {
            "task": "🔧",
            "decisao": "✅",
            "followup": "🔄",
        }.get(self.tipo, "🔧")
        parts.append(tag_emoji)

        parts.append(self.descricao.strip())

        if self.prazo:
            parts.append(f"_(prazo: {self.prazo.strip()})_")

        return " ".join(parts)


@dataclass
class TasksResult:
    """Resultado da extração de tarefas."""

    tasks: list[TaskItem] = field(default_factory=list)
    backend: str = ""
    error: str | None = None

    @property
    def is_empty(self) -> bool:
        return len(self.tasks) == 0

    def to_markdown(self) -> str:
        """Renderiza como markdown completo (para tasks.md)."""
        if self.error:
            return f"# Tarefas\n\n_(extração falhou: {self.error})_\n"
        if self.is_empty:
            return "# Tarefas\n\n_(nenhuma tarefa identificada na reunião)_\n"

        # Agrupa por tipo
        by_type: dict[str, list[TaskItem]] = {"task": [], "decisao": [], "followup": []}
        for t in self.tasks:
            by_type.setdefault(t.tipo, []).append(t)

        parts = ["# Tarefas\n"]

        if by_type.get("task"):
            parts.append("## 🔧 Action Items\n")
            for t in by_type["task"]:
                parts.append(t.to_markdown_line())
            parts.append("")

        if by_type.get("decisao"):
            parts.append("## ✅ Decisões\n")
            for t in by_type["decisao"]:
                parts.append(t.to_markdown_line())
            parts.append("")

        if by_type.get("followup"):
            parts.append("## 🔄 Follow-ups\n")
            for t in by_type["followup"]:
                parts.append(t.to_markdown_line())
            parts.append("")

        if self.backend:
            parts.append(f"\n_(gerado por: {self.backend})_\n")

        return "\n".join(parts)

    def to_section_markdown(self) -> str:
        """Renderiza como seção compacta para embedding em nota.md."""
        if self.error:
            return f"_(extração de tarefas falhou: {self.error})_\n"
        if self.is_empty:
            return "_(nenhuma tarefa identificada)_\n"

        lines = []
        for t in self.tasks:
            lines.append(t.to_markdown_line())
        if self.backend:
            lines.append(f"\n_(gerado por: {self.backend})_")
        return "\n".join(lines) + "\n"


def _parse_tasks_json(raw: str) -> list[TaskItem]:
    """Parse JSON do LLM em lista de TaskItem. Tolerante a markdown fence."""
    # Remove markdown code fences se presente
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*\n", "", cleaned)
        cleaned = re.sub(r"\n```\s*$", "", cleaned)

    # Tenta encontrar JSON object embedded
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if not match:
        log.warning("tasks: nenhum JSON encontrado em '%s'", cleaned[:200])
        return []

    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        log.warning("tasks: JSON inválido (%s) em '%s'", e, cleaned[:200])
        return []

    raw_tasks = data.get("tarefas", [])
    if not isinstance(raw_tasks, list):
        return []

    items: list[TaskItem] = []
    for raw_t in raw_tasks:
        if not isinstance(raw_t, dict):
            continue
        descricao = str(raw_t.get("descricao", "")).strip()
        if not descricao:
            continue
        items.append(
            TaskItem(
                descricao=descricao,
                responsavel=raw_t.get("responsavel") or None,
                prazo=raw_t.get("prazo") or None,
                tipo=str(raw_t.get("tipo", "task")).lower(),
            )
        )
    return items


def extract_tasks(
    transcript_text: str,
    *,
    subject: str = "",
    summarizer_cfg: dict[str, Any] | None = None,
    language: str = "pt",
) -> TasksResult:
    """Extrai tarefas via LLM. Usa mesmo summarizer factory.

    Args:
        transcript_text: texto da transcrição
        subject: assunto da reunião (opcional, melhora contexto)
        summarizer_cfg: configuração do summarizer (padrão: usa primary)
        language: idioma de saída ("pt" ou "en")

    Returns:
        TasksResult com lista de tarefas extraídas (vazia se nenhuma).
    """
    if summarizer_cfg is None:
        summarizer_cfg = {}

    if not transcript_text.strip():
        return TasksResult(error="transcrição vazia")

    backend_name = summarizer_cfg.get("backend", "ollama")
    if backend_name in ("none", "heuristic"):
        # Heurístico: não consegue extrair tasks confiavelmente
        return TasksResult(error=f"backend '{backend_name}' não suporta extração de tarefas")

    subject_line = f"Assunto da reunião: {subject}\n\n" if subject else ""

    # Limita o tamanho do transcript para caber no contexto (varia por provider)
    max_chars = summarizer_cfg.get(backend_name, {}).get("max_transcript_chars", 30000)
    transcript_truncated = transcript_text[:max_chars]
    if len(transcript_text) > max_chars:
        log.info(
            "tasks: transcript truncado %d → %d chars para %s",
            len(transcript_text),
            max_chars,
            backend_name,
        )

    prompt = PROMPT_TEMPLATE.format(
        subject_line=subject_line,
        transcript=transcript_truncated,
    )

    try:
        summarizer = get_summarizer(backend_name, summarizer_cfg)
    except Exception as e:
        log.exception("tasks: falha ao criar summarizer %s: %s", backend_name, e)
        return TasksResult(error=f"summarizer indisponível: {e}")

    log.info("tasks: extraindo via %s", summarizer.name)

    # Reusamos o método summarize do backend, mas o prompt é nosso
    # (não temos um método "raw_complete" no protocol; passamos o prompt
    # como transcript para reaproveitar o I/O configurado)
    try:
        # Truque: o summarizer espera transcript natural; vamos passar o prompt
        # já formatado e extrair JSON da resposta. Os summarizers cloud
        # normalmente retornam JSON no campo `resumo` quando o prompt instrui.
        result = summarizer.summarize(prompt, language=language, subject=subject)
    except Exception as e:
        log.exception("tasks: summarize falhou: %s", e)
        return TasksResult(error=f"LLM call falhou: {e}", backend=summarizer.name)

    # Parse JSON da resposta — tenta resumo primeiro, depois action_items
    raw_response = result.resumo or ""
    if not raw_response and result.action_items:
        # Algum backend pode preencher action_items diretamente
        items = [
            TaskItem(descricao=str(a).strip(), tipo="task") for a in result.action_items if str(a).strip()
        ]
        return TasksResult(tasks=items, backend=summarizer.name)

    items = _parse_tasks_json(raw_response)
    if not items:
        log.warning(
            "tasks: nenhuma tarefa parseada da resposta do %s. Raw: %s",
            summarizer.name,
            raw_response[:200],
        )

    return TasksResult(tasks=items, backend=summarizer.name)
