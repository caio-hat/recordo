# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Caio Hat
"""Markdown rendering pipeline: MD -> HTML com Pygments highlight + tema Adwaita.

Usado pelo WebKit em gui/organisms/markdown_view.py para mostrar nota.md, etc.
Sai HTML completo (com <html><head><style>...</style></head><body>...</body></html>).
"""

from __future__ import annotations

import html as html_mod
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from markdown_it import MarkdownIt
from mdit_py_plugins.anchors import anchors_plugin
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.tasklists import tasklists_plugin
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name, guess_lexer
from pygments.util import ClassNotFound

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RenderOptions:
    dark: bool = True
    show_line_numbers: bool = False
    base_font_size_pt: int = 11
    accent_color: str = "#3584e4"
    max_width_px: int = 720


def _slug(text: str) -> str:
    s = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    return re.sub(r"[\s_-]+", "-", s)[:60]


def _render_fence(self, tokens, idx, options, env):
    token = tokens[idx]
    info = (token.info or "").strip()
    lang = info.split()[0] if info else ""
    code = token.content or ""
    try:
        lexer = get_lexer_by_name(lang) if lang else guess_lexer(code)
    except ClassNotFound:
        lexer = None
    if lexer is not None:
        formatter = HtmlFormatter(cssclass="recordo-code", nowrap=False, linenos=False)
        return f'<div class="recordo-code-wrapper">{highlight(code, lexer, formatter)}</div>'
    return f'<pre class="recordo-code recordo-code-plain">{html_mod.escape(code)}</pre>'


def _build_md_parser() -> MarkdownIt:
    md = (
        MarkdownIt("commonmark", {"html": False, "linkify": True, "typographer": True})
        .enable("table")
        .enable("strikethrough")
        .use(tasklists_plugin, enabled=True, label=True)
        .use(footnote_plugin)
        .use(anchors_plugin, max_level=4, slug_func=_slug)
    )
    md.add_render_rule("fence", _render_fence)
    return md


def _build_css(opts: RenderOptions) -> str:
    if opts.dark:
        bg, fg, muted = "#242424", "#e0e0e0", "#888"
        card_bg, border, code_bg = "#303030", "#3a3a3a", "#1d1d1d"
        pygments_style = "monokai"
    else:
        bg, fg, muted = "#fafafa", "#1f1f1f", "#666"
        card_bg, border, code_bg = "#ffffff", "#e0e0e0", "#f5f5f5"
        pygments_style = "default"
    link = opts.accent_color

    pygments_css = HtmlFormatter(style=pygments_style, cssclass="recordo-code").get_style_defs(
        ".recordo-code"
    )

    return f"""
<style>
html, body {{ margin: 0; padding: 0; background: {bg}; color: {fg};
    font-family: -gtk-system-font, 'Cantarell', 'Inter', sans-serif;
    font-size: {opts.base_font_size_pt}pt; line-height: 1.55; }}
body {{ padding: 24px; max-width: {opts.max_width_px}px; margin: 0 auto; }}
h1, h2, h3, h4 {{ margin-top: 1.5em; margin-bottom: 0.5em; line-height: 1.25; }}
h1 {{ font-size: 1.6em; font-weight: 800; letter-spacing: -0.01em; }}
h2 {{ font-size: 1.3em; font-weight: 700; border-bottom: 1px solid {border}; padding-bottom: 4px; }}
h3 {{ font-size: 1.1em; font-weight: 600; }}
h4 {{ font-size: 1em; font-weight: 600; opacity: 0.85; }}
p {{ margin: 0.7em 0; }}
a {{ color: {link}; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
strong {{ font-weight: 700; }}
em {{ font-style: italic; }}
code {{ background: {code_bg}; padding: 1px 5px; border-radius: 4px; font-family: 'JetBrains Mono', 'Source Code Pro', monospace; font-size: 0.9em; }}
ul, ol {{ padding-left: 1.5em; margin: 0.5em 0; }}
li {{ margin: 0.3em 0; }}
blockquote {{ margin: 0.7em 0; padding: 0.5em 1em; border-left: 3px solid {link}; background: {card_bg}; color: {muted}; }}
hr {{ border: none; height: 1px; background: {border}; margin: 1.5em 0; }}
table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid {border}; }}
th {{ background: {card_bg}; font-weight: 600; }}
.recordo-code-wrapper {{ background: {code_bg}; border-radius: 8px; padding: 12px 16px; margin: 0.7em 0; overflow-x: auto; }}
.recordo-code-wrapper pre {{ margin: 0; }}
.recordo-code-plain {{ background: {code_bg}; padding: 12px 16px; border-radius: 8px; overflow-x: auto; }}
.task-list-item {{ list-style: none; }}
.task-list-item input[type=checkbox] {{ margin-right: 8px; }}
.frontmatter {{ display: none; }}
{pygments_css}
</style>
"""


def render_markdown_to_html(md_text: str, opts: RenderOptions | None = None) -> str:
    """Convert markdown text to standalone HTML page.

    Strip YAML frontmatter (entre --- ... ---) antes de renderizar.
    """
    opts = opts or RenderOptions()
    body = md_text or ""
    if body.startswith("---\n"):
        try:
            end_idx = body.index("\n---\n", 4)
            body = body[end_idx + 5 :]
        except ValueError:
            pass
    md = _build_md_parser()
    rendered = md.render(body)
    css = _build_css(opts)
    return f'<!DOCTYPE html><html><head><meta charset="utf-8">{css}</head><body>{rendered}</body></html>'


def render_file(path: Path, opts: RenderOptions | None = None) -> str:
    """Render a markdown file to HTML."""
    text = path.read_text(encoding="utf-8") if path.exists() else f"_(arquivo não encontrado: {path})_"
    return render_markdown_to_html(text, opts)
