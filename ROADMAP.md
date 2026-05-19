# Roadmap

## v0.1.0 — Empacotamento (atual)

**Estado:** ✅ Released

- [x] Refator do script monolítico em pacote Python modular (`src/recordo/`)
- [x] `pyproject.toml` + `hatchling` + entry point `recordo`
- [x] Daemon asyncio + UNIX socket
- [x] Auto-detect fontes Bluetooth/USB/builtin
- [x] Auto-subject (Teams/Meet/Zoom/Slack/Discord)
- [x] Watchdog silêncio + hard cap 4h
- [x] Post-pipeline (~/Notas/ + nota.md + faster-whisper lazy)
- [x] Auto-detect call (opt-in)
- [x] Wrappers `gravar` + `marcar`
- [x] systemd user unit (workaround Cinnamon `default.target`)
- [x] Cinnamon keybindings idempotentes (`apply-cinnamon.sh` detecta slots livres)
- [x] Vicinae integration (4 scripts + customDirs auto-append)
- [x] `setup.sh` / `uninstall.sh` / `doctor.sh` / `Makefile`
- [x] Logo SVG (color + mono + tray + favicon)
- [x] Docs (README, CLAUDE.md, ARCHITECTURE.md)
- [x] Tests pytest (subject, sources, ffmpeg_cmds, config)
- [x] CI GitHub Actions (ruff + pytest + shellcheck + validate)

## v0.2.0 — Applet Cinnamon

**Estado:** 📋 Planejado

UUID: `recordo@caio-hat`. Layout cinnamon-spices.

```
recordo/
└── recordo@caio-hat/
    ├── info.json                 {"author":"caio-hat"}
    └── files/
        └── recordo@caio-hat/
            ├── metadata.json     uuid, name, version, icon
            ├── applet.js         GJS lógica principal
            ├── settings-schema.json
            ├── stylesheet.css
            ├── icon.png          48×48 (do logo-mono.svg)
            └── po/               i18n gettext (pt_BR + en)
```

### Funcionalidades alvo

- 🔴 **Ícone painel**: vermelho gravando / cinza idle (mudança via CSS class)
- 🕐 **Label dinâmica**: tempo decorrido `🔴 12:34`, ou subject curto truncado
- **Click esquerdo**: toggle (mesmo `Super+R`)
- **Click direito**: menu popup
  - Iniciar/Parar gravação
  - Marcar momento (input inline)
  - Status detalhado (segments, marks)
  - Última gravação → `xdg-open nota.md`
  - Toggle auto-detect on/off
  - Abrir pasta `~/Notas/`
  - Restart daemon
  - Settings
- **Tooltip**: `🔴 Gravando "Daily" há 12:34 · 1 segmento · 2 marcas`
- **Refresh**: 2s polling `recordo --status` (não invasivo)
- **i18n**: pt_BR + en via gettext

### IPC

Sem D-Bus. Padrão `next-meeting` (Gio.Subprocess + JSON stdin/stdout):

```javascript
let proc = new Gio.Subprocess({
    argv: ["recordo", "--status"],
    flags: Gio.SubprocessFlags.STDOUT_PIPE,
});
proc.init(null);
proc.communicate_utf8_async(null, null, (proc, res) => {
    let [, stdout] = proc.communicate_utf8_finish(res);
    let status = JSON.parse(stdout);
    // update UI
});
```

### Settings (settings-schema.json)

- `show-timer`: bool — mostra `MM:SS` no painel quando gravando
- `show-subject`: bool — mostra subject truncado no painel
- `subject-max-chars`: int — truncate
- `notify-on-actions`: bool — toast ao clicar
- `refresh-interval`: int — segundos (default 2)
- `panel-icon-style`: string — "filled" | "outlined"

### Install via setup.sh já preparado

`setup.sh` Fase 1 já contém placeholder pra symlinkar `recordo@caio-hat/files/recordo@caio-hat/` → `~/.local/share/cinnamon/applets/recordo@caio-hat/` se a pasta existir.

### Eventual submissão

Submeter PR pra `linuxmint/cinnamon-spices-applets` seguindo guia. Requer `icon.png` 48×48 + `screenshot.png` ~800×500.

## v0.3.0 — GTK settings standalone

**Estado:** 💭 Idea

Aplicativo GTK4 (Python+PyGObject ou Vala) para configurar `auto-detect.json` visualmente, sem editar JSON. Aproveitaria `geminae-app` pattern (settings-gtk em monorepo).

## v0.4.0 — Integração calendário

**Estado:** 💭 Idea

Daemon lê feeds ICS (mesmas URLs do `next-meeting@caio-hat`). 5min antes de reunião agendada, notify pra confirmar gravação. Auto-subject vem direto do título do evento (mais preciso que xdotool window).

Cuidado: respeitar `auto_started` flag pra distinguir gravações intencionais vs calendário-driven.

## v0.5.0 — Diarização local

**Estado:** 💭 Idea

`pyannote-audio` ou `whisperX` pra identificar quem falou em cada trecho. Beneficiado pelo `--layout split` (sys=L vs mic=R já dá pista).

Output `nota.md` ganharia seção:
```
## Locutores

- **A** (provavelmente eu, mic): 8min
- **B** (sys loopback, outra pessoa): 12min
```

## v0.6.0 — Editor inline de transcrição

**Estado:** 💭 Idea

Modo `recordo edit ~/Notas/<...>/` abre TUI Rich com áudio + transcrição lado-a-lado. Permite corrigir transcrição enquanto escuta. Salva incremental.

## Limitações conhecidas

- **Wayland**: `xdotool getactivewindow` não funciona. Auto-subject vai sempre cair no fallback timestamp. Mitigação futura: usar `swaymsg` (sway) ou portal `org.freedesktop.portal.Window` (genérico).
- **Sem Bluetooth audio profile switch**: se headset BT está em SCO/HSP (mic), monitor de sistema é silencioso. User precisa manter A2DP+input dual mode no PipeWire.
- **Áudios encriptados (DRM)**: streams protegidos pelo sistema (raros em call) não são capturáveis pelo loopback PulseAudio. Sem solução.
