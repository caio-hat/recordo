"""B18a: TUI smoke tests via Textual `run_test()` (no display required).

Garante que mudanças em tui_textual.py não quebram montagem básica.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_tui_mounts_without_exception():
    """RecordoTUI monta com auto_start_daemon=False sem crash."""
    from recordo.tui_textual import RecordoTUI

    app = RecordoTUI(auto_start_daemon=False)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Widgets principais estão presentes
        assert app.query_one("#status-panel") is not None
        assert app.query_one("#devices-panel") is not None
        assert app.query_one("#recent-list") is not None


@pytest.mark.asyncio
async def test_help_screen_opens_and_closes():
    """Pressionar '?' abre HelpScreen, Esc fecha."""
    from recordo.tui_textual import HelpScreen, RecordoTUI

    app = RecordoTUI(auto_start_daemon=False)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()
        # HelpScreen na pilha
        assert any(isinstance(s, HelpScreen) for s in app.screen_stack)
        await pilot.press("escape")
        await pilot.pause()
        # Voltou ao screen principal
        assert not any(isinstance(s, HelpScreen) for s in app.screen_stack)


@pytest.mark.asyncio
async def test_settings_screen_opens_and_closes():
    """Pressionar 'c' abre SettingsScreen, Esc fecha."""
    from recordo.tui_textual import RecordoTUI, SettingsScreen

    app = RecordoTUI(auto_start_daemon=False)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("c")
        await pilot.pause()
        assert any(isinstance(s, SettingsScreen) for s in app.screen_stack)
        await pilot.press("escape")
        await pilot.pause()
        assert not any(isinstance(s, SettingsScreen) for s in app.screen_stack)


@pytest.mark.asyncio
async def test_rename_recent_no_crash_when_no_recordings(tmp_path, monkeypatch):
    """action_rename_recent não crasha se RecentList está vazio."""
    from recordo import config as config_mod
    from recordo.tui_textual import RecordoTUI

    # Aponta NOTAS_DIR pra tmp vazio
    monkeypatch.setattr(config_mod, "NOTAS_DIR", tmp_path)
    # Reload config import path
    import recordo.tui_textual as tui_mod

    monkeypatch.setattr(tui_mod, "NOTAS_DIR", tmp_path)

    app = RecordoTUI(auto_start_daemon=False)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Press 'n' rename — sem gravações deve só notificar
        await pilot.press("n")
        await pilot.pause()
        # Não crashou; nenhuma RenameDialog na pilha
        from recordo.tui_textual import RenameDialog

        assert not any(isinstance(s, RenameDialog) for s in app.screen_stack)


@pytest.mark.asyncio
async def test_quit_action_works():
    """Pressionar 'q' encerra app sem exception."""
    from recordo.tui_textual import RecordoTUI

    app = RecordoTUI(auto_start_daemon=False)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("q")
        # run_test sai naturalmente quando app.exit() é chamado
