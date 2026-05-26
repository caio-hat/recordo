"""Page Settings: PreferencesPage espelhando config.toml."""

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
]
LAYOUTS = ["merge", "split"]
BACKENDS = ["whisper", "parakeet"]
COMPUTE_TYPES = ["int8", "int8_float16", "float16", "float32"]
DEVICES = ["cpu", "cuda"]
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


class SettingsPage(Gtk.ScrolledWindow):
    def __init__(self, window):
        super().__init__(vexpand=True, hexpand=True)
        self.window = window
        self.cfg = load_config()

        prefs = Adw.PreferencesPage()
        self.set_child(prefs)

        # ── Recording ────────────────────────────────────────────────────────
        rec_group = Adw.PreferencesGroup(title="Gravação")
        prefs.add(rec_group)

        self.bitrate_row = Adw.EntryRow(title="Bitrate Opus")
        self.bitrate_row.set_text(self.cfg["recording"]["bitrate"])
        rec_group.add(self.bitrate_row)

        self.layout_row = Adw.ComboRow(title="Layout")
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

        # ── Watchdog ─────────────────────────────────────────────────────────
        wd_group = Adw.PreferencesGroup(title="Watchdog")
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

        # ── Transcriber ──────────────────────────────────────────────────────
        tr_group = Adw.PreferencesGroup(title="Transcrição")
        prefs.add(tr_group)

        self.backend_row = Adw.ComboRow(title="Backend")
        self.backend_row.set_model(Gtk.StringList.new(BACKENDS))
        self.backend_row.set_selected(BACKENDS.index(self.cfg["transcriber"]["backend"]))
        tr_group.add(self.backend_row)

        self.lang_row = Adw.EntryRow(title="Idioma (ISO 639-1)")
        self.lang_row.set_text(self.cfg["transcriber"]["language"])
        tr_group.add(self.lang_row)

        self.whisper_model_row = Adw.ComboRow(title="Whisper model")
        self.whisper_model_row.set_model(Gtk.StringList.new(WHISPER_MODELS))
        cur = self.cfg["transcriber"]["whisper"]["model"]
        if cur in WHISPER_MODELS:
            self.whisper_model_row.set_selected(WHISPER_MODELS.index(cur))
        tr_group.add(self.whisper_model_row)

        self.whisper_device_row = Adw.ComboRow(title="Whisper device")
        self.whisper_device_row.set_model(Gtk.StringList.new(DEVICES))
        self.whisper_device_row.set_selected(
            DEVICES.index(self.cfg["transcriber"]["whisper"].get("device", "cpu"))
        )
        tr_group.add(self.whisper_device_row)

        self.whisper_compute_row = Adw.ComboRow(title="Whisper compute_type")
        self.whisper_compute_row.set_model(Gtk.StringList.new(COMPUTE_TYPES))
        ct = self.cfg["transcriber"]["whisper"].get("compute_type", "int8")
        if ct in COMPUTE_TYPES:
            self.whisper_compute_row.set_selected(COMPUTE_TYPES.index(ct))
        tr_group.add(self.whisper_compute_row)

        self.parakeet_onnx_row = Adw.SwitchRow(title="Parakeet — usar ONNX-INT8")
        self.parakeet_onnx_row.set_subtitle("Mais rápido em CPU se port disponível")
        self.parakeet_onnx_row.set_active(self.cfg["transcriber"]["parakeet"].get("use_onnx", False))
        tr_group.add(self.parakeet_onnx_row)

        # ── Resumo (LLM Provider) ────────────────────────────────────────────
        sum_group = Adw.PreferencesGroup(
            title="Resumo automático",
            description="Provedor LLM para gerar resumo + tópicos das gravações.",
        )
        prefs.add(sum_group)

        sum_cfg = self.cfg.get("summarizer", {})
        cur_backend = sum_cfg.get("backend", "ollama")
        self.sum_backend_row = Adw.ComboRow(title="Provider")
        self.sum_backend_row.set_model(Gtk.StringList.new(SUMMARIZER_BACKENDS))
        if cur_backend in SUMMARIZER_BACKENDS:
            self.sum_backend_row.set_selected(SUMMARIZER_BACKENDS.index(cur_backend))
        sum_group.add(self.sum_backend_row)

        # Ollama
        self.sum_ollama_model_row = Adw.EntryRow(title="Ollama: model")
        self.sum_ollama_model_row.set_text(sum_cfg.get("ollama", {}).get("model", "gemma2:2b"))
        sum_group.add(self.sum_ollama_model_row)

        self.sum_ollama_host_row = Adw.EntryRow(title="Ollama: host")
        self.sum_ollama_host_row.set_text(sum_cfg.get("ollama", {}).get("host", "http://localhost:11434"))
        sum_group.add(self.sum_ollama_host_row)

        # Gemini
        self.sum_gemini_model_row = Adw.EntryRow(title="Gemini: model")
        self.sum_gemini_model_row.set_text(sum_cfg.get("gemini", {}).get("model", "gemini-2.5-flash"))
        sum_group.add(self.sum_gemini_model_row)

        self.sum_gemini_key_row = Adw.PasswordEntryRow(
            title="Gemini: API key (vazio = usa env GEMINI_API_KEY)"
        )
        self.sum_gemini_key_row.set_text(sum_cfg.get("gemini", {}).get("api_key", ""))
        sum_group.add(self.sum_gemini_key_row)

        # OpenAI
        self.sum_openai_model_row = Adw.EntryRow(title="OpenAI: model")
        self.sum_openai_model_row.set_text(sum_cfg.get("openai", {}).get("model", "gpt-4o-mini"))
        sum_group.add(self.sum_openai_model_row)

        self.sum_openai_key_row = Adw.PasswordEntryRow(
            title="OpenAI: API key (vazio = usa env OPENAI_API_KEY)"
        )
        self.sum_openai_key_row.set_text(sum_cfg.get("openai", {}).get("api_key", ""))
        sum_group.add(self.sum_openai_key_row)

        # Anthropic
        self.sum_anthropic_model_row = Adw.EntryRow(title="Anthropic: model")
        self.sum_anthropic_model_row.set_text(
            sum_cfg.get("anthropic", {}).get("model", "claude-3-5-haiku-20241022")
        )
        sum_group.add(self.sum_anthropic_model_row)

        self.sum_anthropic_key_row = Adw.PasswordEntryRow(
            title="Anthropic: API key (vazio = usa env ANTHROPIC_API_KEY)"
        )
        self.sum_anthropic_key_row.set_text(sum_cfg.get("anthropic", {}).get("api_key", ""))
        sum_group.add(self.sum_anthropic_key_row)

        # OpenAI-compatible (Groq/Together/etc)
        self.sum_compat_url_row = Adw.EntryRow(title="OpenAI-compatible: base_url")
        self.sum_compat_url_row.set_text(
            sum_cfg.get("openai_compat", {}).get("base_url", "https://api.groq.com/openai/v1")
        )
        sum_group.add(self.sum_compat_url_row)

        self.sum_compat_model_row = Adw.EntryRow(title="OpenAI-compatible: model")
        self.sum_compat_model_row.set_text(
            sum_cfg.get("openai_compat", {}).get("model", "llama-3.3-70b-versatile")
        )
        sum_group.add(self.sum_compat_model_row)

        self.sum_compat_key_row = Adw.PasswordEntryRow(
            title="OpenAI-compatible: API key (vazio = usa env GROQ_API_KEY)"
        )
        self.sum_compat_key_row.set_text(sum_cfg.get("openai_compat", {}).get("api_key", ""))
        sum_group.add(self.sum_compat_key_row)

        self.sum_fallback_local_row = Adw.SwitchRow(
            title="Fallback automático para Ollama em caso de falha cloud"
        )
        self.sum_fallback_local_row.set_active(sum_cfg.get("fallback_to_local", True))
        sum_group.add(self.sum_fallback_local_row)

        self.sum_fallback_heuristic_row = Adw.SwitchRow(
            title="Fallback final para heuristic (sempre disponível)"
        )
        self.sum_fallback_heuristic_row.set_active(sum_cfg.get("fallback_to_heuristic", True))
        sum_group.add(self.sum_fallback_heuristic_row)

        # Botão de teste
        test_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
            halign=Gtk.Align.CENTER,
            margin_top=8,
        )
        self.btn_test_llm = Gtk.Button(label="🔍 Testar provedor selecionado")
        self.btn_test_llm.add_css_class("pill")
        self.btn_test_llm.connect("clicked", self._on_test_llm)
        test_box.append(self.btn_test_llm)
        self.sum_test_status = Gtk.Label(xalign=0)
        self.sum_test_status.add_css_class("dim-label")
        test_box.append(self.sum_test_status)
        sum_group.add(Adw.PreferencesRow(child=test_box))

        # ── Auto-detect ──────────────────────────────────────────────────────
        ad_group = Adw.PreferencesGroup(
            title="Auto-detect Call",
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

        # ── Save button ──────────────────────────────────────────────────────
        save_group = Adw.PreferencesGroup()
        prefs.add(save_group)

        save_btn = Gtk.Button(label="Salvar & recarregar daemon", halign=Gtk.Align.CENTER)
        save_btn.add_css_class("pill")
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", self._on_save)
        save_group.add(save_btn)

    def _on_save(self, _btn) -> None:
        try:
            self.cfg["recording"]["bitrate"] = self.bitrate_row.get_text()
            self.cfg["recording"]["layout"] = LAYOUTS[self.layout_row.get_selected()]
            self.cfg["recording"]["max_segment"] = int(self.max_seg_row.get_value())
            self.cfg["recording"]["hard_cap_seconds"] = int(self.hard_cap_row.get_value())

            self.cfg["watchdog"]["silence_threshold_db"] = float(self.silence_db_row.get_value())
            self.cfg["watchdog"]["silence_max_seconds"] = int(self.silence_max_row.get_value())
            self.cfg["watchdog"]["reminder_interval"] = int(self.reminder_row.get_value())

            self.cfg["transcriber"]["backend"] = BACKENDS[self.backend_row.get_selected()]
            self.cfg["transcriber"]["language"] = self.lang_row.get_text()
            self.cfg["transcriber"]["whisper"]["model"] = WHISPER_MODELS[
                self.whisper_model_row.get_selected()
            ]
            self.cfg["transcriber"]["whisper"]["device"] = DEVICES[self.whisper_device_row.get_selected()]
            self.cfg["transcriber"]["whisper"]["compute_type"] = COMPUTE_TYPES[
                self.whisper_compute_row.get_selected()
            ]
            self.cfg["transcriber"]["parakeet"]["use_onnx"] = self.parakeet_onnx_row.get_active()

            # Summarizer (LLM Provider)
            sum_cfg = self.cfg.setdefault("summarizer", {})
            sum_cfg["backend"] = SUMMARIZER_BACKENDS[self.sum_backend_row.get_selected()]
            sum_cfg["fallback_to_local"] = self.sum_fallback_local_row.get_active()
            sum_cfg["fallback_to_heuristic"] = self.sum_fallback_heuristic_row.get_active()
            sum_cfg.setdefault("ollama", {})["model"] = self.sum_ollama_model_row.get_text()
            sum_cfg["ollama"]["host"] = self.sum_ollama_host_row.get_text()
            sum_cfg.setdefault("gemini", {})["model"] = self.sum_gemini_model_row.get_text()
            sum_cfg["gemini"]["api_key"] = self.sum_gemini_key_row.get_text()
            sum_cfg.setdefault("openai", {})["model"] = self.sum_openai_model_row.get_text()
            sum_cfg["openai"]["api_key"] = self.sum_openai_key_row.get_text()
            sum_cfg.setdefault("anthropic", {})["model"] = self.sum_anthropic_model_row.get_text()
            sum_cfg["anthropic"]["api_key"] = self.sum_anthropic_key_row.get_text()
            sum_cfg.setdefault("openai_compat", {})["base_url"] = self.sum_compat_url_row.get_text()
            sum_cfg["openai_compat"]["model"] = self.sum_compat_model_row.get_text()
            sum_cfg["openai_compat"]["api_key"] = self.sum_compat_key_row.get_text()

            self.cfg["auto_detect"]["enabled"] = self.ad_enabled_row.get_active()
            self.cfg["auto_detect"]["min_mic_duration_seconds"] = int(self.ad_min_dur_row.get_value())
            self.cfg["auto_detect"]["quiet_period_after_stop_minutes"] = int(self.ad_quiet_row.get_value())

            save_config(self.cfg)
            from .async_client import call_async

            def on_reload(resp: dict) -> None:
                if resp.get("ok"):
                    changes = resp.get("changes") or ["sem mudanças relevantes ao daemon"]
                    self.window.toast(f"Config salva · {len(changes)} mudança(s) aplicada(s)")
                else:
                    self.window.toast(f"Salvo mas reload falhou: {resp.get('error', '?')}")

            call_async("reload_config", on_reload)
        except Exception as e:
            log.exception("erro ao salvar config")
            self.window.toast(f"Erro: {e}")

    def _on_test_llm(self, _btn) -> None:
        """Roda teste rápido do provider selecionado."""
        import threading

        from gi.repository import GLib

        from ..summarizer import get_summarizer

        backend = SUMMARIZER_BACKENDS[self.sum_backend_row.get_selected()]
        # Coleta config atual da UI (sem salvar)
        provider_cfg = {
            "ollama": {
                "model": self.sum_ollama_model_row.get_text(),
                "host": self.sum_ollama_host_row.get_text(),
            },
            "gemini": {
                "model": self.sum_gemini_model_row.get_text(),
                "api_key": self.sum_gemini_key_row.get_text(),
            },
            "openai": {
                "model": self.sum_openai_model_row.get_text(),
                "api_key": self.sum_openai_key_row.get_text(),
            },
            "anthropic": {
                "model": self.sum_anthropic_model_row.get_text(),
                "api_key": self.sum_anthropic_key_row.get_text(),
            },
            "openai_compat": {
                "base_url": self.sum_compat_url_row.get_text(),
                "model": self.sum_compat_model_row.get_text(),
                "api_key": self.sum_compat_key_row.get_text(),
            },
        }

        self.btn_test_llm.set_sensitive(False)
        self.sum_test_status.set_markup(f"<i>Testando {backend}…</i>")

        def worker():
            try:
                summ = get_summarizer(backend, provider_cfg)
                # Resumo curto pra teste rápido
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
                        f"OK — {result.backend} respondeu",
                    )
            except Exception as e:
                log.exception("test_llm falhou")
                GLib.idle_add(self._on_test_done, False, f"Erro: {e}")

        threading.Thread(target=worker, daemon=True, name="recordo-gui-test-llm").start()

    def _on_test_done(self, ok: bool, msg: str) -> bool:
        self.btn_test_llm.set_sensitive(True)
        icon = "✅" if ok else "❌"
        self.sum_test_status.set_markup(f"{icon} {msg}")
        self.window.toast(f"{icon} {msg}")
        from gi.repository import GLib

        return GLib.SOURCE_REMOVE
