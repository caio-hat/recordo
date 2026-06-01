"""B18b: GUI smoke tests (GTK4 + libadwaita).

Mark @pytest.mark.gui — pytest-xvfb cria display virtual quando não há $DISPLAY.
Em CI sem xvfb instalado, marker permite skip via `pytest -m 'not gui'`.

Testes garantem:
- RecordoApp instancia
- Cada Page (Status/Control/Settings/Transcribe) monta sem exception
- Adw.PasswordEntryRow / password helpers funcionam corretamente
"""

from __future__ import annotations

import os

import pytest

# Skip suite inteira se nem display nem xvfb disponíveis
_HAS_DISPLAY = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
_HAS_XVFB = False
try:
    import pytest_xvfb  # noqa: F401

    _HAS_XVFB = True
except ImportError:
    pass

if not (_HAS_DISPLAY or _HAS_XVFB):
    pytest.skip("GUI tests require display or pytest-xvfb", allow_module_level=True)


@pytest.fixture(scope="module", autouse=True)
def init_adw():
    """Inicializa Adwaita uma vez."""
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw

    Adw.init()
    yield


class FakeWindow:
    """Stub de RecordoWindow para Page __init__ que precisa de window param."""

    def __init__(self):
        self.toasts: list[str] = []
        self.listbox = None
        self.stack = None

    def toast(self, msg: str, timeout: int = 3) -> None:
        self.toasts.append(msg)


@pytest.mark.gui
def test_app_class_imports_and_instantiates():
    """RecordoApp instancia sem exception."""
    from recordo.gui.app import RecordoApp

    app = RecordoApp()
    assert app is not None


@pytest.mark.gui
def test_status_page_mounts():
    from recordo.gui.page_status import StatusPage

    page = StatusPage(FakeWindow())
    assert page is not None


@pytest.mark.gui
def test_control_page_mounts():
    from recordo.gui.page_control import ControlPage

    page = ControlPage(FakeWindow())
    assert page is not None


@pytest.mark.gui
def test_settings_page_mounts_with_contextual_visibility():
    """B7+B1 regression: Settings monta + visibilidade contextual funciona."""
    from recordo.gui.page_settings import SettingsPage

    page = SettingsPage(FakeWindow())
    # Backend default em DEFAULTS é 'whisper' → só whisper visible
    # (config user pode overridar; só validamos que groups existem)
    assert page._whisper_group is not None
    assert page._parakeet_group is not None
    assert page._cohere_group is not None
    # Soma das visibilidades = 1 (apenas o backend ativo)
    visible_count = sum(
        [
            page._whisper_group.get_visible(),
            page._parakeet_group.get_visible(),
            page._cohere_group.get_visible(),
        ]
    )
    assert visible_count == 1, "deveria ter apenas 1 backend visível por vez"


@pytest.mark.gui
def test_settings_summarizer_contextual_visibility():
    from recordo.gui.page_settings import SettingsPage

    page = SettingsPage(FakeWindow())
    # Visibilidade dos providers
    sum_visible = sum(
        [
            page._sum_ollama_group.get_visible(),
            page._sum_gemini_group.get_visible(),
            page._sum_openai_group.get_visible(),
            page._sum_anthropic_group.get_visible(),
            page._sum_compat_group.get_visible(),
            page._sum_azure_group.get_visible(),
            page._sum_heuristic_group.get_visible(),
        ]
    )
    assert sum_visible == 1, "exatamente 1 provider visível por vez"


@pytest.mark.gui
def test_password_row_native_adw():
    """B2 regression: _make_password_row retorna Adw.PasswordEntryRow nativo."""
    from gi.repository import Adw

    from recordo.gui.page_settings import _make_password_row

    row = _make_password_row("Test API key", initial="secret")
    assert isinstance(row, Adw.PasswordEntryRow), (
        f"esperado Adw.PasswordEntryRow nativo, recebeu {type(row).__name__}"
    )
    assert row.get_text() == "secret"
    # Native PasswordEntryRow has built-in eye toggle button — no need to walk DOM


@pytest.mark.gui
def test_transcribe_page_mounts_with_header():
    from recordo.gui.page_transcribe import TranscribePage

    page = TranscribePage(FakeWindow())
    # Header card foi construído (chamou _build_header)
    assert page is not None
