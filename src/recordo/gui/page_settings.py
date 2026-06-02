"""Page Settings: PreferencesPage espelhando config.toml.

Inclui:
- Gravação (bitrate, layout, max segment, hard cap)
- Watchdog (silêncio, lembrete)
- Transcrição (backend whisper/parakeet/cohere + campos por backend)
- Resumo LLM (8 backends + API keys com toggle eye + Ollama remoto)
- Auto-detect

API keys usam PasswordEntryRow + botão eye (Gtk.Button toggle reveal).
"""

from __future__ import annotations

import logging

from gi.repository import Adw, Gtk

from ..config import load_config, save_config

log = logging.getLogger(__name__)


WHISPER_MODELS = [
    "tiny",
    "base",
    "small",
    "medium",
    "large-v3",
    "large-v3-turbo",
    "distil-large-v3",
    "jlondonobo/whisper-large-v2-pt",  # fine-tune pt-BR (WER 6.5%)
]
LAYOUTS = ["merge", "split"]
TRANSCRIBE_BACKENDS = ["whisper", "parakeet", "cohere"]
COMPUTE_TYPES = ["int8", "int8_float16", "float16", "float32"]
DEVICES = ["cpu", "cuda", "auto"]
SUMMARIZER_BACKENDS = [
    "ollama",
    "gemini",
    "openai",
    "openai_compat",
    "anthropic",
    "azure_openai",
    "heuristic",
    "none",
]


def _make_password_row(title: str, initial: str = "") -> Adw.PasswordEntryRow:
    """Cria Adw.PasswordEntryRow nativo (libadwaita 1.4+).

    Inclui botão eye built-in com ícone do tema atual. Mais robusto que
    walks DOM no Gtk.Text interno do EntryRow (que era a abordagem antiga).
    """
    row = Adw.PasswordEntryRow(title=title)
    if initial:
        row.set_text(initial)
    return row


class SettingsPage(Gtk.ScrolledWindow):
    def __init__(self, window):
        super().__init__(vexpand=True, hexpand=True)
        self.window = window
        self.cfg = load_config()

        prefs = Adw.PreferencesPage()
        self.set_child(prefs)

        # ── Gravação ─────────────────────────────────────────────────────────
        self._build_recording_group(prefs)

        # ── Watchdog ─────────────────────────────────────────────────────────
        self._build_watchdog_group(prefs)

        # ── Transcrição ──────────────────────────────────────────────────────
        self._build_transcriber_group(prefs)

        # ── Resumo (LLM Provider) ────────────────────────────────────────────
        self._build_summarizer_group(prefs)

        # ── Pipeline (A2: opt-in toggle) ─────────────────────────────────────
        self._build_pipeline_group(prefs)

        # ── Auto-detect ──────────────────────────────────────────────────────
        self._build_autodetect_group(prefs)

        # ── Save button ──────────────────────────────────────────────────────
        save_group = Adw.PreferencesGroup()
        prefs.add(save_group)

        save_btn = Gtk.Button(label="💾  Salvar & recarregar daemon", halign=Gtk.Align.CENTER)
        save_btn.add_css_class("pill")
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", self._on_save)
        save_group.add(save_btn)

        # M2: check inicial do modelo configurado vs disco
        self._check_model_hint()

    # ── Builders ───────────────────────────────────────────────────────────
    def _build_recording_group(self, prefs: Adw.PreferencesPage) -> None:
        rec_group = Adw.PreferencesGroup(title="🎙 Gravação")
        prefs.add(rec_group)

        self.bitrate_row = Adw.EntryRow(title="Bitrate Opus")
        self.bitrate_row.set_text(self.cfg["recording"]["bitrate"])
        rec_group.add(self.bitrate_row)

        self.layout_row = Adw.ComboRow(title="Layout (mic/sys)")
        self.layout_row.set_model(Gtk.StringList.new(LAYOUTS))
        self.layout_row.set_selected(LAYOUTS.index(self.cfg["recording"]["layout"]))
        rec_group.add(self.layout_row)

        self.max_seg_row = Adw.SpinRow.new_with_range(60, 7200, 60)
        self.max_seg_row.set_title("Máx segmento (s)")
        self.max_seg_row.set_value(self.cfg["recording"]["max_segment"])
        rec_group.add(self.max_seg_row)

        self.hard_cap_row = Adw.SpinRow.new_with_range(600, 28800, 600)
        self.hard_cap_row.set_title("Hard cap sessão (s)")
        self.hard_cap_row.set_value(self.cfg["recording"]["hard_cap_seconds"])
        rec_group.add(self.hard_cap_row)

    def _build_watchdog_group(self, prefs: Adw.PreferencesPage) -> None:
        wd_group = Adw.PreferencesGroup(title="🐕 Watchdog")
        prefs.add(wd_group)

        self.silence_db_row = Adw.SpinRow.new_with_range(-80, -10, 1)
        self.silence_db_row.set_title("Silêncio threshold (dB)")
        self.silence_db_row.set_value(self.cfg["watchdog"]["silence_threshold_db"])
        wd_group.add(self.silence_db_row)

        self.silence_max_row = Adw.SpinRow.new_with_range(60, 3600, 30)
        self.silence_max_row.set_title("Silêncio máximo (s)")
        self.silence_max_row.set_value(self.cfg["watchdog"]["silence_max_seconds"])
        wd_group.add(self.silence_max_row)

        self.reminder_row = Adw.SpinRow.new_with_range(60, 3600, 60)
        self.reminder_row.set_title("Lembrete interval (s)")
        self.reminder_row.set_value(self.cfg["watchdog"]["reminder_interval"])
        wd_group.add(self.reminder_row)

    def _build_transcriber_group(self, prefs: Adw.PreferencesPage) -> None:
        # Group principal: só backend + idioma (sempre visíveis)
        tr_group = Adw.PreferencesGroup(
            title="✍ Transcrição",
            description="Escolha o backend; abaixo só os campos do backend selecionado aparecem.",
        )
        prefs.add(tr_group)

        cur_backend = self.cfg["transcriber"]["backend"]
        self.tr_backend_row = Adw.ComboRow(title="Backend")
        self.tr_backend_row.set_model(Gtk.StringList.new(TRANSCRIBE_BACKENDS))
        if cur_backend in TRANSCRIBE_BACKENDS:
            self.tr_backend_row.set_selected(TRANSCRIBE_BACKENDS.index(cur_backend))
        tr_group.add(self.tr_backend_row)

        # M2: Hint contextual se backend não tem modelo baixado
        self.tr_model_hint_row = Adw.ActionRow()
        self.tr_model_hint_row.set_visible(False)
        self.tr_model_hint_row.add_css_class("warning")
        hint_btn = Gtk.Button(label="🔽 Abrir Models Manager", valign=Gtk.Align.CENTER)
        hint_btn.add_css_class("suggested-action")
        hint_btn.connect("clicked", self._on_open_models_page)
        self.tr_model_hint_row.add_suffix(hint_btn)
        tr_group.add(self.tr_model_hint_row)
        # Conectar para atualizar hint quando backend muda
        self.tr_backend_row.connect("notify::selected", self._on_backend_changed)

        self.lang_row = Adw.EntryRow(title="Idioma (ISO 639-1)")
        self.lang_row.set_text(self.cfg["transcriber"]["language"])
        tr_group.add(self.lang_row)

        # ═════ Whisper group (visível só se backend=whisper) ═════
        self._whisper_group = Adw.PreferencesGroup(
            title="🎙 Whisper",
            description="faster-whisper local. Para qualidade pt-BR: jlondonobo/whisper-large-v2-pt.",
        )
        prefs.add(self._whisper_group)

        wh_cfg = self.cfg["transcriber"]["whisper"]

        self.whisper_model_row = Adw.ComboRow(title="Model")
        self.whisper_model_row.set_model(Gtk.StringList.new(WHISPER_MODELS))
        cur = wh_cfg.get("model", "large-v3-turbo")
        if cur in WHISPER_MODELS:
            self.whisper_model_row.set_selected(WHISPER_MODELS.index(cur))
        else:
            ml = Gtk.StringList.new([*WHISPER_MODELS, cur])
            self.whisper_model_row.set_model(ml)
            self.whisper_model_row.set_selected(len(WHISPER_MODELS))
        self._whisper_group.add(self.whisper_model_row)

        self.whisper_device_row = Adw.ComboRow(title="Device")
        self.whisper_device_row.set_model(Gtk.StringList.new(DEVICES))
        self.whisper_device_row.set_selected(DEVICES.index(wh_cfg.get("device", "cpu")))
        self._whisper_group.add(self.whisper_device_row)

        self.whisper_compute_row = Adw.ComboRow(title="compute_type")
        self.whisper_compute_row.set_model(Gtk.StringList.new(COMPUTE_TYPES))
        ct = wh_cfg.get("compute_type", "int8")
        if ct in COMPUTE_TYPES:
            self.whisper_compute_row.set_selected(COMPUTE_TYPES.index(ct))
        self._whisper_group.add(self.whisper_compute_row)

        self.whisper_prompt_row = Adw.EntryRow(title="initial_prompt (biasing pt-BR)")
        self.whisper_prompt_row.set_text(wh_cfg.get("initial_prompt", ""))
        self._whisper_group.add(self.whisper_prompt_row)

        # ═════ Parakeet group (visível só se backend=parakeet) ═════
        self._parakeet_group = Adw.PreferencesGroup(
            title="🦜 Parakeet TDT v3",
            description="NVIDIA NeMo, 25 idiomas. Requer GPU CUDA pra performance.",
        )
        prefs.add(self._parakeet_group)

        self.parakeet_onnx_row = Adw.SwitchRow(title="Usar ONNX-INT8")
        self.parakeet_onnx_row.set_subtitle("Mais rápido em CPU (requer port ONNX baixado)")
        self.parakeet_onnx_row.set_active(self.cfg["transcriber"].get("parakeet", {}).get("use_onnx", False))
        self._parakeet_group.add(self.parakeet_onnx_row)

        # ═════ Cohere group (visível só se backend=cohere) ═════
        self._cohere_group = Adw.PreferencesGroup(
            title="🪶 Cohere Transcribe",
            description="API #1 Open ASR Leaderboard 2026 (WER 5.42%). Get key: dashboard.cohere.com",
        )
        prefs.add(self._cohere_group)

        co_cfg = self.cfg["transcriber"].get("cohere", {})

        self.cohere_model_row = Adw.EntryRow(title="Model")
        self.cohere_model_row.set_text(co_cfg.get("model", "cohere-transcribe-03-2026"))
        self._cohere_group.add(self.cohere_model_row)

        self.cohere_key_row = _make_password_row(
            "API key (vazio = env COHERE_API_KEY)",
            initial=co_cfg.get("api_key", ""),
        )
        self._cohere_group.add(self.cohere_key_row)

        self.cohere_endpoint_row = Adw.EntryRow(title="Endpoint (override)")
        self.cohere_endpoint_row.set_text(
            co_cfg.get("endpoint", "https://api.cohere.com/v2/audio/transcriptions")
        )
        self._cohere_group.add(self.cohere_endpoint_row)

        # Ativa visibilidade contextual e conecta sinal
        self._update_transcriber_visibility()
        self.tr_backend_row.connect("notify::selected", self._on_transcriber_backend_changed)

    def _on_transcriber_backend_changed(self, *_args) -> None:
        self._update_transcriber_visibility()

    def _update_transcriber_visibility(self) -> None:
        """Mostra apenas o group do backend selecionado."""
        sel = TRANSCRIBE_BACKENDS[self.tr_backend_row.get_selected()]
        self._whisper_group.set_visible(sel == "whisper")
        self._parakeet_group.set_visible(sel == "parakeet")
        self._cohere_group.set_visible(sel == "cohere")

    def _build_summarizer_group(self, prefs: Adw.PreferencesPage) -> None:
        sum_group = Adw.PreferencesGroup(
            title="🧠 Resumo automático (LLM)",
            description="Ollama (local), Gemini, OpenAI, Groq/Together, Anthropic, Azure. Cascata fallback automático.",
        )
        prefs.add(sum_group)

        sum_cfg = self.cfg.get("summarizer", {})
        cur_backend = sum_cfg.get("backend", "ollama")

        self.sum_backend_row = Adw.ComboRow(title="Provider")
        self.sum_backend_row.set_model(Gtk.StringList.new(SUMMARIZER_BACKENDS))
        if cur_backend in SUMMARIZER_BACKENDS:
            self.sum_backend_row.set_selected(SUMMARIZER_BACKENDS.index(cur_backend))
        sum_group.add(self.sum_backend_row)

        # Fallbacks (sempre visíveis no group principal)
        self.sum_fallback_local_row = Adw.SwitchRow(title="↩ Fallback automático para Ollama se cloud falhar")
        self.sum_fallback_local_row.set_active(sum_cfg.get("fallback_to_local", True))
        sum_group.add(self.sum_fallback_local_row)

        self.sum_fallback_heuristic_row = Adw.SwitchRow(
            title="🔁 Fallback final: heurístico (sempre disponível)"
        )
        self.sum_fallback_heuristic_row.set_active(sum_cfg.get("fallback_to_heuristic", True))
        sum_group.add(self.sum_fallback_heuristic_row)

        # ═════ Ollama group ═════
        self._sum_ollama_group = Adw.PreferencesGroup(
            title="🦙 Ollama (local)",
            description="LLM local. Suporta servidor remoto (homelab).",
        )
        prefs.add(self._sum_ollama_group)

        ol_cfg = sum_cfg.get("ollama", {})
        self.sum_ollama_model_row = Adw.EntryRow(title="Model (ex: gemma4:e2b)")
        self.sum_ollama_model_row.set_text(ol_cfg.get("model", "gemma2:2b"))
        self._sum_ollama_group.add(self.sum_ollama_model_row)

        self.sum_ollama_host_row = Adw.EntryRow(title="Host (local ou remoto)")
        self.sum_ollama_host_row.set_text(ol_cfg.get("host", "http://localhost:11434"))
        self._sum_ollama_group.add(self.sum_ollama_host_row)

        self.sum_ollama_ctx_row = Adw.SpinRow.new_with_range(2048, 131072, 2048)
        self.sum_ollama_ctx_row.set_title("num_ctx (contexto em tokens)")
        self.sum_ollama_ctx_row.set_value(ol_cfg.get("num_ctx", 32768))
        self._sum_ollama_group.add(self.sum_ollama_ctx_row)

        # ═════ Gemini group ═════
        self._sum_gemini_group = Adw.PreferencesGroup(
            title="✨ Google Gemini",
            description="Get key: aistudio.google.com/apikey",
        )
        prefs.add(self._sum_gemini_group)

        gem_cfg = sum_cfg.get("gemini", {})
        self.sum_gemini_model_row = Adw.EntryRow(title="Model (ex: gemini-2.5-flash)")
        self.sum_gemini_model_row.set_text(gem_cfg.get("model", "gemini-2.5-flash"))
        self._sum_gemini_group.add(self.sum_gemini_model_row)

        self.sum_gemini_key_row = _make_password_row(
            "API key (vazio = env GEMINI_API_KEY)",
            initial=gem_cfg.get("api_key", ""),
        )
        self._sum_gemini_group.add(self.sum_gemini_key_row)

        # ═════ OpenAI group ═════
        self._sum_openai_group = Adw.PreferencesGroup(
            title="🤖 OpenAI",
            description="Get key: platform.openai.com/api-keys",
        )
        prefs.add(self._sum_openai_group)

        oa_cfg = sum_cfg.get("openai", {})
        self.sum_openai_model_row = Adw.EntryRow(title="Model (ex: gpt-4o-mini)")
        self.sum_openai_model_row.set_text(oa_cfg.get("model", "gpt-4o-mini"))
        self._sum_openai_group.add(self.sum_openai_model_row)

        self.sum_openai_key_row = _make_password_row(
            "API key (vazio = env OPENAI_API_KEY)",
            initial=oa_cfg.get("api_key", ""),
        )
        self._sum_openai_group.add(self.sum_openai_key_row)

        # ═════ Anthropic group ═════
        self._sum_anthropic_group = Adw.PreferencesGroup(
            title="🧠 Anthropic Claude",
            description="Get key: console.anthropic.com",
        )
        prefs.add(self._sum_anthropic_group)

        an_cfg = sum_cfg.get("anthropic", {})
        self.sum_anthropic_model_row = Adw.EntryRow(title="Model (ex: claude-3-5-haiku-20241022)")
        self.sum_anthropic_model_row.set_text(an_cfg.get("model", "claude-3-5-haiku-20241022"))
        self._sum_anthropic_group.add(self.sum_anthropic_model_row)

        self.sum_anthropic_key_row = _make_password_row(
            "API key (vazio = env ANTHROPIC_API_KEY)",
            initial=an_cfg.get("api_key", ""),
        )
        self._sum_anthropic_group.add(self.sum_anthropic_key_row)

        # ═════ OpenAI-compatible group (Groq/Together/etc) ═════
        self._sum_compat_group = Adw.PreferencesGroup(
            title="⚡ OpenAI-compatível (Groq, Together, OpenRouter, LM Studio)",
            description="Qualquer provider que implementa /v1/chat/completions. Mude base_url.",
        )
        prefs.add(self._sum_compat_group)

        oc_cfg = sum_cfg.get("openai_compat", {})
        self.sum_compat_url_row = Adw.EntryRow(title="base_url")
        self.sum_compat_url_row.set_text(oc_cfg.get("base_url", "https://api.groq.com/openai/v1"))
        self._sum_compat_group.add(self.sum_compat_url_row)

        self.sum_compat_model_row = Adw.EntryRow(title="Model (ex: llama-3.3-70b-versatile)")
        self.sum_compat_model_row.set_text(oc_cfg.get("model", "llama-3.3-70b-versatile"))
        self._sum_compat_group.add(self.sum_compat_model_row)

        self.sum_compat_key_row = _make_password_row(
            "API key (env GROQ_API_KEY ou similar)",
            initial=oc_cfg.get("api_key", ""),
        )
        self._sum_compat_group.add(self.sum_compat_key_row)

        # ═════ Azure group ═════
        self._sum_azure_group = Adw.PreferencesGroup(
            title="☁ Azure OpenAI",
            description="Deployment-based path + api-version.",
        )
        prefs.add(self._sum_azure_group)

        az_cfg = sum_cfg.get("azure_openai", {})
        self.sum_azure_endpoint_row = Adw.EntryRow(title="Endpoint (ex: https://your.openai.azure.com)")
        self.sum_azure_endpoint_row.set_text(az_cfg.get("endpoint", ""))
        self._sum_azure_group.add(self.sum_azure_endpoint_row)

        self.sum_azure_deployment_row = Adw.EntryRow(title="Deployment name")
        self.sum_azure_deployment_row.set_text(az_cfg.get("deployment", ""))
        self._sum_azure_group.add(self.sum_azure_deployment_row)

        self.sum_azure_version_row = Adw.EntryRow(title="api-version (ex: 2024-08-01-preview)")
        self.sum_azure_version_row.set_text(az_cfg.get("api_version", "2024-08-01-preview"))
        self._sum_azure_group.add(self.sum_azure_version_row)

        self.sum_azure_key_row = _make_password_row(
            "API key (vazio = env AZURE_OPENAI_API_KEY)",
            initial=az_cfg.get("api_key", ""),
        )
        self._sum_azure_group.add(self.sum_azure_key_row)

        # ═════ Heuristic info group ═════
        self._sum_heuristic_group = Adw.PreferencesGroup(
            title="🔤 Heurístico (TextRank-like)",
            description="Sem deps. Resumo via top-N sentenças por TF de palavras-chave. Sem API key.",
        )
        prefs.add(self._sum_heuristic_group)

        # Botão de teste
        test_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
            halign=Gtk.Align.CENTER,
            margin_top=8,
            margin_bottom=8,
        )
        self.btn_test_llm = Gtk.Button(label="🔍  Testar provider selecionado")
        self.btn_test_llm.add_css_class("pill")
        self.btn_test_llm.connect("clicked", self._on_test_llm)
        test_box.append(self.btn_test_llm)

        self.sum_test_status = Gtk.Label(xalign=0)
        self.sum_test_status.add_css_class("dim-label")
        test_box.append(self.sum_test_status)

        wrap_row = Adw.PreferencesRow()
        wrap_row.set_child(test_box)
        wrap_row.set_activatable(False)
        sum_group.add(wrap_row)

        # Aplica visibilidade contextual + conecta sinal
        self._update_summarizer_visibility()
        self.sum_backend_row.connect("notify::selected", self._on_summarizer_backend_changed)

    def _on_summarizer_backend_changed(self, *_args) -> None:
        self._update_summarizer_visibility()

    def _update_summarizer_visibility(self) -> None:
        """Mostra apenas o group do provider selecionado."""
        sel = SUMMARIZER_BACKENDS[self.sum_backend_row.get_selected()]
        self._sum_ollama_group.set_visible(sel == "ollama")
        self._sum_gemini_group.set_visible(sel == "gemini")
        self._sum_openai_group.set_visible(sel == "openai")
        self._sum_anthropic_group.set_visible(sel == "anthropic")
        self._sum_compat_group.set_visible(sel == "openai_compat")
        self._sum_azure_group.set_visible(sel == "azure_openai")
        self._sum_heuristic_group.set_visible(sel == "heuristic")

    def _on_backend_changed(self, *_args) -> None:
        """M2: chamado quando user muda combobox de backend."""
        self._check_model_hint()

    def _check_model_hint(self) -> None:
        """M2: mostra hint se backend selecionado tem modelo não baixado."""
        from ..models import (
            is_parakeet_installed,
            is_whisper_installed,
        )
        from ..models_registry import (
            PARAKEET_MODELS,
            WHISPER_MODELS,
        )

        sel_backend = TRANSCRIBE_BACKENDS[self.tr_backend_row.get_selected()]

        # Determina modelo configurado conforme backend
        if sel_backend == "whisper":
            model_short = self.cfg["transcriber"]["whisper"].get("model", "large-v3-turbo")
            info = WHISPER_MODELS.get(model_short)
            installed = is_whisper_installed(info.full_id) if info else False
            backend_label = "Whisper"
        elif sel_backend == "parakeet":
            model_full = self.cfg["transcriber"]["parakeet"].get("model", "nvidia/parakeet-tdt-0.6b-v3")
            # Match em PARAKEET_MODELS pelo full_id
            info = next((v for v in PARAKEET_MODELS.values() if v.full_id == model_full), None)
            installed = is_parakeet_installed(model_full) if info else False
            backend_label = "Parakeet"
        elif sel_backend == "cohere":
            # Cohere é API, sem download
            self.tr_model_hint_row.set_visible(False)
            return
        else:
            self.tr_model_hint_row.set_visible(False)
            return

        if installed:
            self.tr_model_hint_row.set_visible(False)
        else:
            model_name = info.short_name if info else model_short  # noqa: F841
            self.tr_model_hint_row.set_title(f"⚠ Modelo {backend_label} não baixado")
            self.tr_model_hint_row.set_subtitle(
                "O modelo configurado não está em disco. Baixe via Models Manager para usar este backend."
            )
            self.tr_model_hint_row.set_visible(True)

    def _on_open_models_page(self, _btn) -> None:
        """M2: navega para aba Models na sidebar."""
        try:
            row = self.window.listbox.get_first_child()
            while row is not None:
                if getattr(row, "tag", None) == "models":
                    self.window.listbox.select_row(row)
                    return
                row = row.get_next_sibling()
        except Exception:
            log.exception("falha navegar para Models Manager")

    def _build_pipeline_group(self, prefs: Adw.PreferencesPage) -> None:
        """A2: Configurações do pipeline (auto_run + steps automáticos)."""
        pp_cfg = self.cfg.get("pipeline", {})

        pp_group = Adw.PreferencesGroup(
            title="🚀 Pipeline pós-gravação",
            description=(
                "Controle quais passos rodam automaticamente após gravar. "
                "Quando desabilitado, você aciona manualmente via botões em cada gravação."
            ),
        )
        prefs.add(pp_group)

        # Switch principal: auto_run
        self.pp_auto_run_row = Adw.SwitchRow(
            title="Pipeline automático",
            subtitle=(
                "Ao parar gravação, executa transcrição (e resumo se habilitado). "
                "Desligue se quiser controle manual e economizar recursos."
            ),
        )
        self.pp_auto_run_row.set_active(bool(pp_cfg.get("auto_run", False)))
        pp_group.add(self.pp_auto_run_row)

        # Switch: auto_summarize (só relevante se auto_run=True)
        self.pp_auto_summarize_row = Adw.SwitchRow(
            title="Resumir automaticamente",
            subtitle="Quando o pipeline automático rodar, gera resumo via LLM.",
        )
        self.pp_auto_summarize_row.set_active(bool(pp_cfg.get("auto_summarize", True)))
        pp_group.add(self.pp_auto_summarize_row)

        # Switch: auto_tasks
        self.pp_auto_tasks_row = Adw.SwitchRow(
            title="Extrair tarefas automaticamente",
            subtitle="Gera lista de action items (tasks.md). Requer LLM configurado.",
        )
        self.pp_auto_tasks_row.set_active(bool(pp_cfg.get("auto_tasks", False)))
        pp_group.add(self.pp_auto_tasks_row)

    def _build_autodetect_group(self, prefs: Adw.PreferencesPage) -> None:
        ad_group = Adw.PreferencesGroup(
            title="🤖 Auto-detect Call",
            description="Detecta apps usando mic e inicia gravação automática (agressivo).",
        )
        prefs.add(ad_group)

        self.ad_enabled_row = Adw.SwitchRow(title="Habilitado")
        self.ad_enabled_row.set_active(self.cfg["auto_detect"]["enabled"])
        ad_group.add(self.ad_enabled_row)

        self.ad_min_dur_row = Adw.SpinRow.new_with_range(1, 60, 1)
        self.ad_min_dur_row.set_title("Min duração mic (s)")
        self.ad_min_dur_row.set_value(self.cfg["auto_detect"]["min_mic_duration_seconds"])
        ad_group.add(self.ad_min_dur_row)

        self.ad_quiet_row = Adw.SpinRow.new_with_range(0, 60, 1)
        self.ad_quiet_row.set_title("Quiet period após stop (min)")
        self.ad_quiet_row.set_value(self.cfg["auto_detect"]["quiet_period_after_stop_minutes"])
        ad_group.add(self.ad_quiet_row)

    # ── Save ───────────────────────────────────────────────────────────────
    def _on_save(self, _btn) -> None:
        try:
            # Recording
            self.cfg["recording"]["bitrate"] = self.bitrate_row.get_text()
            self.cfg["recording"]["layout"] = LAYOUTS[self.layout_row.get_selected()]
            self.cfg["recording"]["max_segment"] = int(self.max_seg_row.get_value())
            self.cfg["recording"]["hard_cap_seconds"] = int(self.hard_cap_row.get_value())

            # Watchdog
            self.cfg["watchdog"]["silence_threshold_db"] = float(self.silence_db_row.get_value())
            self.cfg["watchdog"]["silence_max_seconds"] = int(self.silence_max_row.get_value())
            self.cfg["watchdog"]["reminder_interval"] = int(self.reminder_row.get_value())

            # Transcriber
            self.cfg["transcriber"]["backend"] = TRANSCRIBE_BACKENDS[self.tr_backend_row.get_selected()]
            self.cfg["transcriber"]["language"] = self.lang_row.get_text()

            # Pode estar custom → busca selected via lookup do StringList
            ml = self.whisper_model_row.get_model()
            sel_idx = self.whisper_model_row.get_selected()
            self.cfg["transcriber"]["whisper"]["model"] = ml.get_string(sel_idx)
            self.cfg["transcriber"]["whisper"]["device"] = DEVICES[self.whisper_device_row.get_selected()]
            self.cfg["transcriber"]["whisper"]["compute_type"] = COMPUTE_TYPES[
                self.whisper_compute_row.get_selected()
            ]
            self.cfg["transcriber"]["whisper"]["initial_prompt"] = self.whisper_prompt_row.get_text()

            self.cfg["transcriber"].setdefault("parakeet", {})["use_onnx"] = (
                self.parakeet_onnx_row.get_active()
            )

            co_cfg = self.cfg["transcriber"].setdefault("cohere", {})
            co_cfg["model"] = self.cohere_model_row.get_text()
            co_cfg["api_key"] = self.cohere_key_row.get_text()
            co_cfg["endpoint"] = self.cohere_endpoint_row.get_text()

            # Summarizer
            sum_cfg = self.cfg.setdefault("summarizer", {})
            sum_cfg["backend"] = SUMMARIZER_BACKENDS[self.sum_backend_row.get_selected()]
            sum_cfg["fallback_to_local"] = self.sum_fallback_local_row.get_active()
            sum_cfg["fallback_to_heuristic"] = self.sum_fallback_heuristic_row.get_active()

            sum_cfg.setdefault("ollama", {})["model"] = self.sum_ollama_model_row.get_text()
            sum_cfg["ollama"]["host"] = self.sum_ollama_host_row.get_text()
            sum_cfg["ollama"]["num_ctx"] = int(self.sum_ollama_ctx_row.get_value())

            sum_cfg.setdefault("gemini", {})["model"] = self.sum_gemini_model_row.get_text()
            sum_cfg["gemini"]["api_key"] = self.sum_gemini_key_row.get_text()

            sum_cfg.setdefault("openai", {})["model"] = self.sum_openai_model_row.get_text()
            sum_cfg["openai"]["api_key"] = self.sum_openai_key_row.get_text()

            sum_cfg.setdefault("anthropic", {})["model"] = self.sum_anthropic_model_row.get_text()
            sum_cfg["anthropic"]["api_key"] = self.sum_anthropic_key_row.get_text()

            sum_cfg.setdefault("openai_compat", {})["base_url"] = self.sum_compat_url_row.get_text()
            sum_cfg["openai_compat"]["model"] = self.sum_compat_model_row.get_text()
            sum_cfg["openai_compat"]["api_key"] = self.sum_compat_key_row.get_text()

            # Auto-detect
            self.cfg["auto_detect"]["enabled"] = self.ad_enabled_row.get_active()
            self.cfg["auto_detect"]["min_mic_duration_seconds"] = int(self.ad_min_dur_row.get_value())
            self.cfg["auto_detect"]["quiet_period_after_stop_minutes"] = int(self.ad_quiet_row.get_value())

            # Pipeline (A2)
            pp = self.cfg.setdefault("pipeline", {})
            pp["auto_run"] = self.pp_auto_run_row.get_active()
            pp["auto_summarize"] = self.pp_auto_summarize_row.get_active()
            pp["auto_tasks"] = self.pp_auto_tasks_row.get_active()

            save_config(self.cfg)
            from .async_client import call_async

            def on_reload(resp: dict) -> None:
                if resp.get("ok"):
                    changes = resp.get("changes") or ["sem mudanças relevantes ao daemon"]
                    self.window.toast(f"✓ Config salva · {len(changes)} mudança(s) aplicada(s)")
                else:
                    self.window.toast(f"⚠ Salvo mas reload falhou: {resp.get('error', '?')}")

            call_async("reload_config", on_reload)
        except Exception as e:
            log.exception("erro ao salvar config")
            self.window.toast(f"⚠ Erro: {e}")

    # ── Test LLM ───────────────────────────────────────────────────────────
    def _on_test_llm(self, _btn) -> None:
        import threading

        from gi.repository import GLib

        from ..summarizer import get_summarizer

        backend = SUMMARIZER_BACKENDS[self.sum_backend_row.get_selected()]
        provider_cfg = {
            "ollama": {
                "model": self.sum_ollama_model_row.get_text(),
                "host": self.sum_ollama_host_row.get_text(),
                "num_ctx": int(self.sum_ollama_ctx_row.get_value()),
                "timeout_seconds": 60,
            },
            "gemini": {
                "model": self.sum_gemini_model_row.get_text(),
                "api_key": self.sum_gemini_key_row.get_text(),
                "timeout_seconds": 30,
            },
            "openai": {
                "model": self.sum_openai_model_row.get_text(),
                "api_key": self.sum_openai_key_row.get_text(),
                "timeout_seconds": 30,
            },
            "anthropic": {
                "model": self.sum_anthropic_model_row.get_text(),
                "api_key": self.sum_anthropic_key_row.get_text(),
                "timeout_seconds": 30,
            },
            "openai_compat": {
                "base_url": self.sum_compat_url_row.get_text(),
                "model": self.sum_compat_model_row.get_text(),
                "api_key": self.sum_compat_key_row.get_text(),
                "timeout_seconds": 30,
            },
        }

        self.btn_test_llm.set_sensitive(False)
        self.sum_test_status.set_markup(f"<i>Testando {backend}…</i>")

        def worker() -> None:
            try:
                summ = get_summarizer(backend, provider_cfg)
                test_text = (
                    "Esta é uma transcrição de teste. Vamos validar que o provedor "
                    "responde corretamente. Decidimos testar a integração."
                )
                result = summ.summarize(test_text, language="pt", subject="Teste")
                if result.error:
                    GLib.idle_add(self._on_test_done, False, f"Falhou: {result.error}")
                else:
                    GLib.idle_add(
                        self._on_test_done,
                        True,
                        f"OK — {result.backend}",
                    )
            except Exception as e:
                log.exception("test_llm falhou")
                GLib.idle_add(self._on_test_done, False, f"Erro: {e}")

        threading.Thread(target=worker, daemon=True, name="recordo-gui-test-llm").start()

    def _on_test_done(self, ok: bool, msg: str) -> bool:
        from gi.repository import GLib

        self.btn_test_llm.set_sensitive(True)
        icon = "✅" if ok else "❌"
        self.sum_test_status.set_markup(f"{icon} {msg}")
        self.window.toast(f"{icon} {msg}")
        return GLib.SOURCE_REMOVE
