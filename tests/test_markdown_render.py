# SPDX-License-Identifier: GPL-3.0-only
"""Tests for recordo.markdown_render."""

from recordo.markdown_render import RenderOptions, render_markdown_to_html


def test_render_basic_markdown():
    html = render_markdown_to_html("# Hello\n\nParagraph text.")
    assert "<h1" in html
    assert "Hello" in html
    assert "<p>" in html


def test_render_strips_frontmatter():
    md = "---\nkey: val\ntitle: Test\n---\n# Title\n\nBody."
    html = render_markdown_to_html(md)
    assert "key:" not in html
    assert "Title" in html
    assert "<h1" in html


def test_render_dark_mode_uses_dark_bg():
    html = render_markdown_to_html("# X", RenderOptions(dark=True))
    assert "#242424" in html


def test_render_light_mode_uses_light_bg():
    html = render_markdown_to_html("# X", RenderOptions(dark=False))
    assert "#fafafa" in html


def test_render_code_block_syntax_highlight():
    md = "```python\nx = 1\n```\n"
    html = render_markdown_to_html(md)
    assert "recordo-code" in html
    assert "highlight" in html or 'class="' in html


def test_render_table():
    md = "| a | b |\n| - | - |\n| 1 | 2 |\n"
    html = render_markdown_to_html(md)
    assert "<table>" in html
    assert "<td>" in html
