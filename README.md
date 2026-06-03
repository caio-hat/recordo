<div align="center">

<img src="assets/logo.svg" width="160" alt="Recordo logo">

# Recordo

**Frictionless meeting recorder for Linux. _Record + Recordar._**

[![CI](https://github.com/caio-hat/recordo/actions/workflows/ci.yml/badge.svg)](https://github.com/caio-hat/recordo/actions/workflows/ci.yml)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPL_v3-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

Apertou `Super+R`. Tá gravando. Apertou de novo. Salvou. Transcreveu sozinho. Em `~/Notas/`.

</div>

---

## Por que existe

Quando uma call surge "do nada", cada passo (abrir terminal, lembrar comando, digitar assunto) é uma janela de desistência — especialmente para pessoas com TDAH. Recordo reduz tudo a **um atalho global**: `Super+R`. Sem decisões na hora.

Bonus: pós-gravação é 100% automático. Áudio Opus, transcrição via faster-whisper, arquivamento em `~/Notas/<data>_<assunto>/` com `nota.md` editável.

## Recursos

- 🔴 **Toggle global** `Super+R` — start/stop sem terminal
- 📍 **Marcar momento** `Super+Shift+M` — registra timestamp + nota opcional
- 🎛️ **TUI moderna** (`recordo --tui`) — painéis live com Textual + auto-conecta no daemon
- 🖼️ **GUI desktop** (`recordo --gui`) — GTK4 + libadwaita, dashboard único com NavigationView
- 🎙️ **Auto-detecção de fontes** — Bluetooth > USB > builtin, mic + system loopback
- 🎚️ **Auto-detect call** (opt-in) — event-driven via `pactl subscribe`, detecta Teams/Meet/Zoom/Slack/Discord usando mic e grava sozinho
- 🤖 **Auto-subject** — pega título da janela ativa (X11 ou Wayland: sway/i3/hyprland)
- 🏷️ **Auto-extração nome de reunião** — regex patterns para Teams/Zoom/Meet/Webex/Discord/Slack
- 💾 **Codec Opus 32 kbps** — 10× menos CPU que MP3, ~6× menor em disco; concat com `-c copy` (zero reencode quando layout é homogêneo)
- 🔇 **Watchdog inteligente** — `parec` mede mic em paralelo (não disputa com captura); para sozinho após 10min mudo, cap absoluto 4h
- 📝 **Transcrição automática** via faster-whisper (pt-BR local, sem cloud) — backend pluggable (Whisper ou Parakeet ONNX via sherpa-onnx)
- 🦜 **Parakeet ONNX** (sherpa-onnx) — ~2GB RAM peak vs 6-8GB do NeMo, backend default
- 🖥️ **Hardware preflight** — RAM/CPU/GPU detect + recomendação automática de backend + fallback
- 📖 **Renderização markdown integrada** — tabs Nota/Transcrição/Resumo/Tarefas via WebKit (substitui abrir pasta no Files)
- 🧙 **Onboarding wizard** — 3 passos no primeiro uso (backend, hardware check, atalhos)
- ⚙️ **Configurações avançadas Ollama** — think/temperature/top_p/top_k/num_ctx/repeat_penalty/seed
- 📊 **Dashboard único** — substitui sidebar 5-abas; sub-pages via NavigationView push()
- 🗂️ **Pós-pipeline** — move pra `~/Notas/<data>_<assunto>/` com `nota.md` + frontmatter YAML
- 🚀 **Daemon systemd** — sempre vivo, latência ~zero no toggle
- 🧠 **Integração Vicinae** — 4 comandos (toggle/status/last/mark)

## Quick install

```bash
git clone https://github.com/caio-hat/recordo.git ~/Projetos/recordo
cd ~/Projetos/recordo
bash setup.sh
```

Instalador (`setup.sh`) idempotente. Detecta apt, instala deps, cria venv, registra systemd unit, configura keybindings Cinnamon, integra Vicinae. Suporta `--no-systemd`, `--no-cinnamon`, `--no-vicinae`, `--with-transcribe`.

Após instalar, **logout/login** ou `cinnamon --replace &` pra Cinnamon recarregar os atalhos.

### Pré-requisitos

- Linux Ubuntu/Mint/Debian (apt-based)
- Python 3.10+
- PulseAudio/PipeWire (default em Mint 22+)
- Cinnamon (opcional — keybindings; outros DEs funcionam sem hotkey)
- Vicinae (opcional — integração launcher)

Setup auto-instala via apt: `ffmpeg`, `pulseaudio-utils` (inclui `parec` usado pelo watchdog de silêncio), `libnotify-bin`, `xdotool`, `zenity`, `dconf-cli`, `wmctrl`, `socat`, `jq`, `xdg-utils`, `python3-venv`. Para a GUI GTK4: `python3-gi`, `gir1.2-gtk-4.0`, `gir1.2-adw-1`. Para o markdown viewer integrado: `gir1.2-webkit2-4.1`. Em Wayland (sway/i3/hyprland), também detecta `swaymsg`/`hyprctl` para captura de janela ativa.

## Uso

| Ação | Como |
|---|---|
| Iniciar/parar gravação | `Super+R` (ou `recordo --toggle`) |
| Marcar momento | `Super+Shift+M` (ou `recordo --mark "nota"`) |
| Status atual | `recordo --status` |
| TUI moderna (Textual) | `recordo --tui` — auto-conecta no daemon |
| GUI desktop (GTK4) | `recordo --gui` — dashboard + páginas |
| Listar dispositivos | `recordo --list-devices` |
| Recarregar config | `recordo --reload-config` (sem restart do daemon) |

A TUI Textual é a forma recomendada de interagir pelo terminal: painéis live de status, dispositivos detectados e últimas gravações; help completo via `?`. Atalhos: `r` toggle, `m` marcar, `s` parar, `R` reload config, `q` sair.

Logs em `/tmp/recordo.log`. Resultado em `~/Notas/<YYYY-MM-DD>_<assunto>/`.

## Estrutura da nota gerada

```
~/Notas/2026-05-19_Daily_Standup/
├── audio.opus              ← áudio (Opus 32k, ~10MB/hora)
├── nota.md                 ← markdown editável com frontmatter
├── transcricao.txt         ← texto puro
└── transcricao.srt         ← legendas com timestamp
```

`nota.md` contém:

```markdown
---
subject: Daily Standup
date: 2026-05-19T09:00:00
duration_min: 23.4
audio: ./audio.opus
transcricao: ./transcricao.txt
segments: 1
tags: [reuniao]
---

# Daily Standup

## Marcas durante gravação
- [00:05:30] decisão chave sobre X

## Notas manuais


## Transcrição
```

## Auto-detect (opt-in)

Ligar via TUI/GUI (Settings) ou direto no `~/.config/recordo/config.toml`:

```toml
[auto_detect]
enabled = true
```

Aplicar sem restart:

```bash
recordo --reload-config
```

Daemon vai monitorar mic via `pactl subscribe` (event-driven, baixa latência). Quando detectar Teams/Zoom/Meet/Slack capturando áudio por ≥8s, inicia gravação sozinho. Quiet period de 5min pós-stop evita re-trigger indesejado.

A lista de apps permitidos vive em `[auto_detect].apps` no `config.toml`. Veja `config/config.toml.example`.

## Troubleshooting

```bash
# Diagnóstico completo
bash ~/Projetos/recordo/doctor.sh
# (ou)
make doctor

# Status daemon
systemctl --user status recordo
recordo --status

# Logs
tail -f /tmp/recordo.log
journalctl --user -u recordo -f

# Reiniciar
systemctl --user restart recordo

# Hotkey não funciona?
# → logout/login OU `cinnamon --replace &`

# Desinstalar (preserva ~/Notas e venv)
bash uninstall.sh

# Desinstalar tudo (purge venv + config)
bash uninstall.sh --purge
```

## Arquitetura (resumo)

```
[Super+R] → bin/gravar → recordo --toggle → UNIX socket → Daemon (asyncio)
                                                            ↓
                                                       Recorder (ffmpeg ×2)
                                                            ↓
                                                    post_pipeline → ~/Notas/
                                                            ↓
                                                  thread: faster-whisper / sherpa-onnx
                                                            ↓
                                                  thread: ollama LLM (resumo + tarefas)
```

Detalhes em [ARCHITECTURE.md](ARCHITECTURE.md).

## Roadmap

- **v0.2.4** (atual): Parakeet ONNX, hardware preflight, dashboard redesign, markdown viewer integrado, onboarding wizard
- **v0.3.0**: GTK headerbar status indicator, suite E2E ampliada
- **v0.4.0**: integração calendário (auto-detect call agendada)

Detalhes em [ROADMAP.md](ROADMAP.md).

## Contribuindo

Pull requests são bem-vindos. Para mudanças grandes, abra uma issue primeiro pra discutir.

```bash
make install         # setup local
make test            # roda pytest
make lint            # ruff
make format          # ruff format
make shellcheck      # bash scripts
```

## Arquitetura UI (Atomic Design)

Todos componentes seguem hierarquia componível para facilitar manutenção
e geração por LLMs:

- `gui/atoms/` — widgets básicos (StatusBadge, Heading, ActionButton, PulseDot, progress.LinearBar/Spinner/StepProgress)
- `gui/molecules/` — composições de atoms (Card, EmptyState, InfoDialog, ConfirmDialog)
- `gui/organisms/` — components com lógica via callbacks (HardwareCard, RecordingCard, MarkdownView)
- `gui/pages/` — telas top-level (Dashboard, Settings, Models, Logs, RecordingDetail)
- `gui/wizards/` — fluxos guiados (Onboarding)
- `gui/theme.css` — design tokens centralizados (cores, espaçamento, tipografia)

## License

[GPL-3.0-only](LICENSE) — © 2026 Caio Hat. See [AUTHORS.md](AUTHORS.md) for credits.

You may modify and redistribute Recordo under the terms of the GPL v3. Derivative works must remain open source under the same license. Original authorship must be preserved.
