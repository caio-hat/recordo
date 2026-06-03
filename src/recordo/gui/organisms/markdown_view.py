# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Caio Hat
"""MarkdownView — renderer Markdown nativo GTK4.

Estratégia:
1. Tenta WebKit 6.0 (GTK4 nativo) — disponível em distros mais novas
2. Fallback: Gtk.TextView + TextBuffer com tags Pango ricas (headings,
   bold, italic, code blocks, lists, links). Funciona sem WebKit.

WebKit2 4.1 (GTK3) NÃO é compatível com Gtk 4.0 já carregado, então não
serve como fallback.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, Gtk, Pango

from ...markdown_render import RenderOptions, render_file, render_markdown_to_html

log = logging.getLogger(__name__)

# Tenta WebKit 6.0 (GTK4 nativo)
_WEBKIT_OK = False
WebKit = None  # type: ignore[assignment]
try:
    gi.require_version("WebKit", "6.0")
    from gi.repository import WebKit  # type: ignore[no-redef]

    _WEBKIT_OK = True
    log.info("MarkdownView: usando WebKit 6.0")
except (ValueError, ImportError):
    log.info("MarkdownView: WebKit 6.0 indisponível — usando renderer nativo Gtk4")


# ───────────────────────────────────────────────────────────────────────
# Renderer nativo Gtk4 (TextView + tags Pango)
# ───────────────────────────────────────────────────────────────────────


def _build_text_tags(buffer: Gtk.TextBuffer) -> dict:
    """Cria tags Pango para diferentes elementos markdown."""
    tags = {}
    tags["h1"] = buffer.create_tag(
        "h1", weight=Pango.Weight.BOLD, scale=1.8, pixels_above_lines=18, pixels_below_lines=8
    )
    tags["h2"] = buffer.create_tag(
        "h2", weight=Pango.Weight.BOLD, scale=1.4, pixels_above_lines=14, pixels_below_lines=6
    )
    tags["h3"] = buffer.create_tag(
        "h3", weight=Pango.Weight.BOLD, scale=1.2, pixels_above_lines=10, pixels_below_lines=4
    )
    tags["h4"] = buffer.create_tag("h4", weight=Pango.Weight.BOLD, scale=1.05)
    tags["bold"] = buffer.create_tag("bold", weight=Pango.Weight.BOLD)
    tags["italic"] = buffer.create_tag("italic", style=Pango.Style.ITALIC)
    tags["code"] = buffer.create_tag(
        "code",
        family="JetBrains Mono, Source Code Pro, monospace",
        background="#1d1d1d",
        foreground="#e0e0e0",
        scale=0.92,
    )
    tags["code_block"] = buffer.create_tag(
        "code_block",
        family="JetBrains Mono, Source Code Pro, monospace",
        background="#1d1d1d",
        foreground="#e0e0e0",
        scale=0.92,
        left_margin=24,
        right_margin=24,
        pixels_above_lines=8,
        pixels_below_lines=8,
    )
    tags["quote"] = buffer.create_tag(
        "quote",
        style=Pango.Style.ITALIC,
        left_margin=24,
        foreground="#a0a0a0",
        pixels_above_lines=4,
        pixels_below_lines=4,
    )
    tags["link"] = buffer.create_tag("link", foreground="#3584e4", underline=Pango.Underline.SINGLE)
    tags["list_item"] = buffer.create_tag("list_item", left_margin=24, indent=-12)
    tags["caption"] = buffer.create_tag("caption", scale=0.85, foreground="#888888")
    tags["hr"] = buffer.create_tag("hr", foreground="#444", pixels_above_lines=8, pixels_below_lines=8)
    return tags


def _strip_frontmatter(md: str) -> str:
    """Remove bloco YAML frontmatter (--- ... ---) inicial, se houver."""
    if md.startswith("---\n"):
        try:
            end = md.index("\n---\n", 4)
            return md[end + 5 :]
        except ValueError:
            pass
    return md


def _render_markdown_into_buffer(md_text: str, buffer: Gtk.TextBuffer, tags: dict) -> list[tuple]:
    """Renderiza markdown em texto + tags no TextBuffer.

    Estratégia simplificada (não tenta cobrir 100% do CommonMark):
      - Linhas começando com #/##/### são headings
      - Linhas começando com - * + são bullet list items
      - Blocos entre ``` são code blocks
      - >-prefixed linhas são quotes
      - **bold**, *italic*, `code` inline
      - [text](url) viram link clicável

    Retorna list de (start_offset, end_offset, url) para links → handlers.
    """
    md = _strip_frontmatter(md_text)
    links: list[tuple[int, int, str]] = []

    in_code_block = False

    for raw_line in md.splitlines():
        line = raw_line

        # Code block delimiter
        if line.strip().startswith("```"):
            if not in_code_block:
                in_code_block = True
                continue
            else:
                in_code_block = False
                # blank line após code block para respiro
                buffer.insert(buffer.get_end_iter(), "\n")
                continue

        if in_code_block:
            start_mark = buffer.create_mark(None, buffer.get_end_iter(), True)
            buffer.insert(buffer.get_end_iter(), line + "\n")
            start_iter = buffer.get_iter_at_mark(start_mark)
            buffer.apply_tag(tags["code_block"], start_iter, buffer.get_end_iter())
            buffer.delete_mark(start_mark)
            continue

        # Heading
        m = re.match(r"^(#{1,4})\s+(.+)$", line)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            tag = tags.get(f"h{level}", tags["h2"])
            start_mark = buffer.create_mark(None, buffer.get_end_iter(), True)
            buffer.insert(buffer.get_end_iter(), text + "\n")
            start_iter = buffer.get_iter_at_mark(start_mark)
            buffer.apply_tag(tag, start_iter, buffer.get_end_iter())
            buffer.delete_mark(start_mark)
            continue

        # Horizontal rule
        if re.match(r"^-{3,}$|^={3,}$|^_{3,}$", line.strip()):
            start_mark = buffer.create_mark(None, buffer.get_end_iter(), True)
            buffer.insert(buffer.get_end_iter(), "─" * 40 + "\n")
            start_iter = buffer.get_iter_at_mark(start_mark)
            buffer.apply_tag(tags["hr"], start_iter, buffer.get_end_iter())
            buffer.delete_mark(start_mark)
            continue

        # Quote
        if line.startswith(">"):
            text = line[1:].strip()
            start_mark = buffer.create_mark(None, buffer.get_end_iter(), True)
            buffer.insert(buffer.get_end_iter(), text + "\n")
            start_iter = buffer.get_iter_at_mark(start_mark)
            buffer.apply_tag(tags["quote"], start_iter, buffer.get_end_iter())
            buffer.delete_mark(start_mark)
            continue

        # Bullet list
        m_list = re.match(r"^(\s*)[-*+]\s+(.+)$", line)
        if m_list:
            indent = len(m_list.group(1))
            content = m_list.group(2)
            bullet = "  " * (indent // 2) + "•  "
            start_mark = buffer.create_mark(None, buffer.get_end_iter(), True)
            buffer.insert(buffer.get_end_iter(), bullet)
            _insert_inline_markdown(buffer, content + "\n", tags, links)
            start_iter = buffer.get_iter_at_mark(start_mark)
            buffer.apply_tag(tags["list_item"], start_iter, buffer.get_end_iter())
            buffer.delete_mark(start_mark)
            continue

        # Numbered list
        m_num = re.match(r"^(\s*)(\d+)[.)]\s+(.+)$", line)
        if m_num:
            indent = len(m_num.group(1))
            num = m_num.group(2)
            content = m_num.group(3)
            prefix = "  " * (indent // 2) + f"{num}. "
            start_mark = buffer.create_mark(None, buffer.get_end_iter(), True)
            buffer.insert(buffer.get_end_iter(), prefix)
            _insert_inline_markdown(buffer, content + "\n", tags, links)
            start_iter = buffer.get_iter_at_mark(start_mark)
            buffer.apply_tag(tags["list_item"], start_iter, buffer.get_end_iter())
            buffer.delete_mark(start_mark)
            continue

        # Linha vazia
        if not line.strip():
            buffer.insert(buffer.get_end_iter(), "\n")
            continue

        # Parágrafo regular com inline markdown
        _insert_inline_markdown(buffer, line + "\n", tags, links)

    return links


def _insert_inline_markdown(
    buffer: Gtk.TextBuffer, text: str, tags: dict, links: list[tuple[int, int, str]]
) -> None:
    """Processa **bold**, *italic*, `code`, [link](url) inline.

    Algoritmo simples: regex multi-pass. Não é CommonMark perfeito mas
    cobre 90% dos casos de notas/transcrições.
    """
    # Regex compõe alternativas; ordem importa: code antes de bold/italic
    pattern = re.compile(
        r"(?P<code>`[^`]+`)"
        r"|(?P<bold>\*\*[^*]+\*\*)"
        r"|(?P<italic>(?<!\*)\*[^*]+\*(?!\*))"
        r"|(?P<link>\[([^\]]+)\]\(([^)]+)\))"
    )

    pos = 0
    for m in pattern.finditer(text):
        # Insert plain text antes do match
        if m.start() > pos:
            buffer.insert(buffer.get_end_iter(), text[pos : m.start()])

        # Insert match com tag apropriada
        if m.group("code"):
            content = m.group("code")[1:-1]
            start_mark = buffer.create_mark(None, buffer.get_end_iter(), True)
            buffer.insert(buffer.get_end_iter(), content)
            start_iter = buffer.get_iter_at_mark(start_mark)
            buffer.apply_tag(tags["code"], start_iter, buffer.get_end_iter())
            buffer.delete_mark(start_mark)
        elif m.group("bold"):
            content = m.group("bold")[2:-2]
            start_mark = buffer.create_mark(None, buffer.get_end_iter(), True)
            buffer.insert(buffer.get_end_iter(), content)
            start_iter = buffer.get_iter_at_mark(start_mark)
            buffer.apply_tag(tags["bold"], start_iter, buffer.get_end_iter())
            buffer.delete_mark(start_mark)
        elif m.group("italic"):
            content = m.group("italic")[1:-1]
            start_mark = buffer.create_mark(None, buffer.get_end_iter(), True)
            buffer.insert(buffer.get_end_iter(), content)
            start_iter = buffer.get_iter_at_mark(start_mark)
            buffer.apply_tag(tags["italic"], start_iter, buffer.get_end_iter())
            buffer.delete_mark(start_mark)
        elif m.group("link"):
            link_text = m.group(5)
            link_url = m.group(6)
            start_mark = buffer.create_mark(None, buffer.get_end_iter(), True)
            buffer.insert(buffer.get_end_iter(), link_text)
            start_iter = buffer.get_iter_at_mark(start_mark)
            buffer.apply_tag(tags["link"], start_iter, buffer.get_end_iter())
            # Registra link com offsets
            offset_start = start_iter.get_offset()
            offset_end = buffer.get_end_iter().get_offset()
            links.append((offset_start, offset_end, link_url))
            buffer.delete_mark(start_mark)

        pos = m.end()

    # Insert tail
    if pos < len(text):
        buffer.insert(buffer.get_end_iter(), text[pos:])


# ───────────────────────────────────────────────────────────────────────
# MarkdownView widget público
# ───────────────────────────────────────────────────────────────────────


class MarkdownView(Gtk.Box):
    """Markdown viewer. Usa WebKit 6.0 se disponível, senão renderer Gtk4 nativo."""

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.set_vexpand(True)
        self.set_hexpand(True)

        if _WEBKIT_OK and WebKit is not None:
            self._webview = WebKit.WebView()
            try:
                self._webview.connect("decide-policy", self._on_policy)
            except Exception:
                pass
            self.append(self._webview)
            self._textview = None
        else:
            self._webview = None
            scrolled = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
            self._textview = Gtk.TextView()
            self._textview.set_editable(False)
            self._textview.set_cursor_visible(False)
            self._textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            self._textview.set_pixels_above_lines(2)
            self._textview.set_pixels_below_lines(2)
            self._textview.set_left_margin(20)
            self._textview.set_right_margin(20)
            self._textview.set_top_margin(20)
            self._textview.set_bottom_margin(20)
            self._textview.add_css_class("recordo-markdown-view")
            scrolled.set_child(self._textview)
            self.append(scrolled)
            self._tags = _build_text_tags(self._textview.get_buffer())
            self._setup_link_handler()

    def _setup_link_handler(self) -> None:
        """Liga clique em links abertos com tag 'link' a abrir browser."""
        click = Gtk.GestureClick()
        click.connect("released", self._on_textview_click)
        self._textview.add_controller(click)
        self._links: list[tuple[int, int, str]] = []

    def _on_textview_click(self, gesture, n_press, x, y) -> None:
        if not self._textview:
            return
        bx, by = self._textview.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, int(x), int(y))
        success, iter_at = self._textview.get_iter_at_location(bx, by)
        if not success:
            return
        offset = iter_at.get_offset()
        for start, end, url in self._links:
            if start <= offset < end:
                try:
                    Gio.AppInfo.launch_default_for_uri(url, None)
                except Exception:
                    log.exception("falha abrir link %s", url)
                return

    def load_file(self, path: Path) -> None:
        """Carrega arquivo .md/.txt e renderiza."""
        if self._webview is not None:
            opts = RenderOptions(dark=self._is_dark())
            html = render_file(path, opts)
            base_uri = f"file://{path.parent.resolve()}/"
            try:
                self._webview.load_html(html, base_uri)
            except Exception:
                self._webview.load_html(html)
            return

        # Fallback Gtk4 native
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            text = f"_(falha ao ler {path})_"
        self._render_into_textview(text)

    def load_markdown_text(self, md: str) -> None:
        if self._webview is not None:
            opts = RenderOptions(dark=self._is_dark())
            html = render_markdown_to_html(md, opts)
            try:
                self._webview.load_html(html)
            except Exception:
                pass
            return
        self._render_into_textview(md)

    def _render_into_textview(self, md: str) -> None:
        if self._textview is None:
            return
        buf = self._textview.get_buffer()
        buf.set_text("")
        self._links = _render_markdown_into_buffer(md, buf, self._tags)

    def _is_dark(self) -> bool:
        try:
            return Adw.StyleManager.get_default().get_dark()
        except Exception:
            return True

    def _on_policy(self, _wv, decision, decision_type):
        try:
            if decision_type == WebKit.PolicyDecisionType.NAVIGATION_ACTION:  # type: ignore
                navigation = decision.get_navigation_action()
                req = navigation.get_request()
                uri = req.get_uri() if req else ""
                if uri.startswith(("http://", "https://", "mailto:")):
                    Gio.AppInfo.launch_default_for_uri(uri, None)
                    decision.ignore()
                    return True
        except Exception:
            pass
        return False
