# Changelog

Todas as mudanças notáveis deste projeto. Formato baseado em [Keep a Changelog](https://keepachangelog.com/), versionamento [SemVer](https://semver.org/).

## [0.1.0] — 2026-05-19

### Added

- Pacote Python `recordo` modular (refator do script monolítico anterior `ffmpeg-grava-audio.py`, 1410 linhas)
  - `recordo.cli` — argparse + dispatch (daemon, client, standalone)
  - `recordo.daemon` — asyncio Daemon + watchdogs + auto-detect
  - `recordo.recorder` — Recorder, Segment, SessionState, Mark
  - `recordo.sources` — AudioSource + detection PulseAudio/PipeWire
  - `recordo.ffmpeg_cmds` — builders puros
  - `recordo.subject` — heurísticas Teams/Meet/Zoom/Slack/Discord
  - `recordo.pipeline` — post_pipeline + transcribe lazy
  - `recordo.notify`, `recordo.tui`, `recordo.client`, `recordo.config`
- `setup.sh` instalador idempotente (apt deps + venv + entry points + systemd + Cinnamon + Vicinae)
- `uninstall.sh` reverte tudo (preserva ~/Notas, opcional --purge)
- `doctor.sh` diagnóstico read-only
- `Makefile` com atalhos (install, test, lint, format, doctor, status, logs)
- Wrappers shell `bin/gravar` + `bin/marcar` pra hotkeys
- systemd user unit `recordo.service` (template, `WantedBy=default.target` para Cinnamon)
- Cinnamon keybindings idempotentes via `keybindings/apply-cinnamon.sh` (detecta slots livres + colisões)
- 4 scripts Vicinae (`record-toggle`, `record-status`, `record-last`, `record-mark`)
- Logo SVG (color + mono + tray + favicon) — conceito: botão record vermelho + arcos de memória
- Testes pytest cobrindo funções puras (subject, sources, ffmpeg_cmds, config)
- GitHub Actions CI (Python 3.10/3.11/3.12 + ruff + pytest + shellcheck + JSON/SVG validate)
- Documentação completa (README, CLAUDE.md, ARCHITECTURE.md, ROADMAP.md)

### Features (herdadas do script original, agora empacotadas)

- Toggle global `Super+R` (Cinnamon dconf keybinding custom4)
- Marcar momento `Super+Shift+M` (Cinnamon dconf keybinding custom5)
- Auto-subject via `xdotool getactivewindow getwindowname` + heurísticas
- Auto-detect fontes Bluetooth > USB > builtin
- Auto-detect call agressivo opt-in (pactl source-outputs + apps permitidos)
- Watchdog silêncio (10min mic mudo → auto-stop)
- Hard cap 4h por sessão
- Auto-cycle de segmento a cada 30min (configurável)
- Post-pipeline automático: `~/Notas/<date>_<subject>/` com `nota.md` + frontmatter YAML
- Transcrição faster-whisper em thread background (pt-BR local, lazy install)
- Codec Opus 32k voz (10× menos CPU que MP3, ~6× menor disco)
- Opção `--layout split` (sys=L, mic=R) pra diarização posterior

### Decisões técnicas

- UNIX socket em vez de D-Bus (simplicidade + portabilidade entre toolkits)
- venv dedicado em `~/.local/share/recordo/venv` (não pollute Python sistema)
- `notify-send -r` com replace-id em `/tmp/recordo.notif_id` (padrão `mute.sh`)
- Tudo em pt-BR na UI/help; código + commits em inglês
- License: MIT
