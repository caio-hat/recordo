# CLAUDE.md — Recordo

Contexto pra agentes (Claude Code, Cursor, etc) trabalharem neste repositório.

## O que é

**Recordo** — gravador de reuniões CLI/daemon para Linux. Nome = trocadilho **record** (gravar) + **recordar** (lembrar em pt-BR). Repositório público em `caio-hat/recordo` (MIT).

Objetivo principal: reduzir início de gravação a **um único atalho global** (`Super+R`), com pós-pipeline 100% automático (Opus + transcrição faster-whisper + arquivamento em `~/Notas/`). Especialmente pensado para usuários com TDAH — zero decisões na emergência.

## Stack

- **Python 3.10+** (venv dedicado em `~/.local/share/recordo/venv`)
- **asyncio** no daemon (socket UNIX `/run/user/$UID/recordo.sock`)
- **ffmpeg** + **libopus** + filtros `loudnorm`/`join`/`amerge`/`volumedetect`
- **PulseAudio/PipeWire** via `pactl`
- **Rich** para TUI standalone
- **faster-whisper** (lazy install, opcional)
- **systemd user unit** (`WantedBy=default.target` — workaround Cinnamon)
- **Cinnamon dconf** keybindings
- **Vicinae** custom scripts

## Layout

```
recordo/
├── src/recordo/             ← pacote Python
│   ├── cli.py               argparse + dispatch
│   ├── daemon.py            Daemon asyncio + comandos socket
│   ├── recorder.py          Recorder, Segment, SessionState, Mark
│   ├── sources.py           AudioSource, list_sources, auto_pick, detect_active_call
│   ├── ffmpeg_cmds.py       builders puros (build_capture/merge/concat)
│   ├── subject.py           heurísticas Teams/Meet/Zoom/Slack/Discord
│   ├── notify.py            notify-send com replace-id
│   ├── pipeline.py          post_pipeline + transcribe + ensure_whisper_installed
│   ├── tui.py               Rich Live + KeyReader (modo standalone)
│   ├── client.py            send_to_daemon (JSON-lines UNIX socket)
│   ├── config.py            constantes, XDG paths, DEFAULT_AUTO_DETECT
│   └── __main__.py          python -m recordo
├── bin/{gravar,marcar}      wrappers shell pra hotkeys
├── systemd/recordo.service  template (placeholder __RECORDO_BIN__)
├── vicinae/*.sh             4 scripts pra Vicinae
├── keybindings/             cinnamon.dconf.template + apply-cinnamon.sh
├── assets/                  logo.svg (color) + logo-mono.svg + icon-tray.svg + favicon.svg
├── config/auto-detect.json.example
├── tests/                   pytest (subject, sources, ffmpeg_cmds, config)
├── docs/                    installation, configuration, troubleshooting, architecture
├── setup.sh                 instalador idempotente (10 steps)
├── uninstall.sh             reverte tudo (--purge p/ apagar venv + config)
├── doctor.sh                diagnóstico read-only
├── Makefile                 atalhos: install, test, lint, doctor, status, logs
└── pyproject.toml           hatchling, entry point `recordo`
```

## Modos de execução

1. **Daemon** (`recordo --daemon`): asyncio loop, escuta socket UNIX. Iniciado por systemd user unit.
2. **Client** (`recordo --toggle|--status|--mark|--stop|--quit-daemon`): conecta socket, envia JSON, imprime resposta.


## Comandos do daemon (JSON-lines)

| cmd | args | resposta |
|---|---|---|
| `toggle` | — | dispatcha start ou stop |
| `start` | `subject?`, `auto?` | `{ok, session_id, subject}` |
| `stop` | — | `{ok, target_dir}` |
| `mark` | `text?` | `{ok, mark: {ts_seconds, iso_time, text}}` |
| `status` | — | `{ok, recording, elapsed_seconds, ...}` |
| `quit` | — | termina daemon (SIGTERM autoinvocado) |

## Hard requirements

- **Lockfile** + **signal handlers** (SIGINT/SIGTERM/SIGHUP) — sem ffmpeg órfão jamais
- **Hard cap 4h** por sessão — proteção catastrófica
- **Watchdog silêncio mic** 10min → auto-stop
- **Auto-cycle de segmento** a cada `max-segment` (default 30min)
- **Notify-send com replace-id** (`/tmp/recordo.notif_id`) — padrão `mute.sh` do user

## Convenções

- **Idioma:** código + commits + docs em inglês; UI/help/CLI em pt-BR
- **Commits:** `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:` (Conventional Commits)
- **Tests:** pytest, funções puras (subject, sources, ffmpeg_cmds, config). Sem testar ffmpeg real (smoke E2E manual)
- **Lint:** ruff (config em pyproject)
- **CI:** GitHub Actions — matrix Python 3.10/3.11/3.12 + shellcheck + SVG/JSON/YAML validate

## Padrões reutilizados (referência rápida)

- `next-meeting@caio-hat/setup.sh` (`~/Projetos/cinnamon-applet-next-meeting/setup.sh`): padrão idempotente STEP-by-STEP, fallback `pip install --user --break-system-packages`, detect apt
- `~/Scripts/mute.sh` (no Dropbox sync, antes user-only): padrão `notify-send -r ID` com state file
- `~/Projetos/geminae-app/`: monorepo + `WantedBy=default.target` workaround Cinnamon documentado
- Cinnamon spices convention: `<UUID>/files/<UUID>/` — relevante na Fase 2 (applet)

## Fase 2 — Applet Cinnamon (planejado)

UUID: `recordo@caio-hat`. Estrutura `<repo>/recordo@caio-hat/files/recordo@caio-hat/`. Comunicação via `Gio.Subprocess(["recordo", "--status"])` (sem D-Bus — mais simples, igual `next-meeting` invocando `fetch_meetings.py`). Detalhes em [ROADMAP.md](ROADMAP.md).

## Cuidados ao mexer

- **Não tocar** em `Recorder._terminate` sem entender lockfile + signal flow — risco de regression de órfão
- **`os.execv` pra re-exec dentro de venv** existia no script antigo; foi REMOVIDO no refator (setup.sh é a única forma suportada agora)
- **`notify-send -p`** retorna ID novo no stdout; preservar lógica de replace
- **Auto-detect agressivo**: respeitar `quiet_period_after_stop_minutes` pra evitar restart imediato após user parar manualmente
- **Vicinae customDirs**: append, nunca overwrite (preservar outros paths do user)

## Histórico

- v0.1.0: refator de `~/Scripts/ffmpeg-grava-audio.py` (~1410 linhas, arquivo único) → pacote modular instalável. Empacotamento Recordo. Logo SVG criado.
- Antes do empacotamento: script já tinha daemon + hotkeys + auto-detect + Vicinae scripts funcionando localmente na Akira. Migração feita preservando comportamento (smoke E2E validou).
