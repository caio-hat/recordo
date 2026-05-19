<div align="center">

<img src="assets/logo.svg" width="160" alt="Recordo logo">

# Recordo

**Frictionless meeting recorder for Linux. _Record + Recordar._**

[![CI](https://github.com/caio-hat/recordo/actions/workflows/ci.yml/badge.svg)](https://github.com/caio-hat/recordo/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
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
- 🎙️ **Auto-detecção de fontes** — Bluetooth > USB > builtin, mic + system loopback
- 🎚️ **Auto-detect call** (opt-in) — detecta Teams/Meet/Zoom/Slack/Discord usando mic, grava sozinho
- 🤖 **Auto-subject** — pega título da janela ativa (Teams/Meet/Zoom/Slack/Discord)
- 💾 **Codec Opus 32 kbps** — 10× menos CPU que MP3, ~6× menor em disco
- 🔇 **Watchdog inteligente** — para sozinho após 10min de mic mudo, cap absoluto 4h
- 📝 **Transcrição automática** via faster-whisper (pt-BR local, sem cloud)
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

Setup auto-instala via apt: `ffmpeg`, `pulseaudio-utils`, `libnotify-bin`, `xdotool`, `zenity`, `dconf-cli`, `wmctrl`, `socat`, `jq`, `xdg-utils`, `python3-venv`.

## Uso

| Ação | Como |
|---|---|
| Iniciar/parar gravação | `Super+R` (ou `recordo --toggle`) |
| Marcar momento | `Super+Shift+M` (ou `recordo --mark "nota"`) |
| Status atual | `recordo --status` |
| Listar dispositivos | `recordo --list-devices` |
| Modo CLI standalone (Rich TUI) | `recordo -a` |

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

Ligar:

```bash
jq '.enabled = true' ~/.config/recordo/auto-detect.json | sponge ~/.config/recordo/auto-detect.json
systemctl --user restart recordo
```

Daemon vai monitorar mic. Quando detectar Teams/Zoom/Meet/Slack capturando áudio por ≥8s, inicia gravação sozinho. Quiet period de 5min pós-stop evita re-trigger indesejado.

Editar lista de apps permitidos: `~/.config/recordo/auto-detect.json`.

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
                                                  thread: faster-whisper
```

Detalhes em [ARCHITECTURE.md](ARCHITECTURE.md).

## Roadmap

- **v0.1.0** (atual): daemon + hotkeys + auto-detect + Vicinae integration
- **v0.2.0**: applet Cinnamon (`grava-audio@caio-hat`) — controle visual no painel
- **v0.3.0**: GTK settings UI standalone
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

## License

[MIT](LICENSE) — Caio Hat
