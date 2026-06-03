# Recordo Architecture

## High-level overview

```
┌──────────────────────────────────────────────────────────────────┐
│                         User Layer                               │
│                                                                  │
│   Super+R       Super+Shift+M     Vicinae       recordo --tui    │
│   (Cinnamon)    (Cinnamon)        scripts       (Textual)        │
│       │              │                 │             │           │
│       ▼              ▼                 ▼             ▼           │
│   bin/gravar    bin/marcar      recordo --*    tui_textual.py    │
│       │              │                 │       (auto-spin daemon)│
│       └──────────────┴─────────────────┴─────────────┘           │
│                            │                                     │
│                            ▼                                     │
│           UNIX socket: /run/user/$UID/recordo.sock               │
│                  (JSON-lines protocol)                           │
└──────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────────┐
│                  Daemon (asyncio loop)                           │
│                                                                  │
│   ┌─────────────┐  ┌──────────────┐  ┌───────────────────┐       │
│   │ socket      │  │  watchdog    │  │  auto-detect      │       │
│   │ handler     │  │  loop (2s)   │  │  event-driven     │       │
│   │             │  │              │  │                   │       │
│   │ toggle/start│  │  hard-cap 4h │  │  pactl subscribe  │       │
│   │ stop/mark/  │  │  silence 10m │  │  (asyncio.Event)  │       │
│   │ status/quit │  │  remind 15m  │  │  + min_duration   │       │
│   │ reload-cfg  │  │  seg cycle   │  │  + quiet_period   │       │
│   │             │  │  parec RMS   │  │                   │       │
│   └──────┬──────┘  └──────┬───────┘  └─────────┬─────────┘       │
│          │                │                    │                 │
│          └────────────────┴────────────────────┘                 │
│                           │                                      │
│                           ▼                                      │
│                  ┌────────────────┐                              │
│                  │   Recorder     │                              │
│                  │                │                              │
│                  │ Popen(ffmpeg)  │  ──────────────► sys.opus    │
│                  │   sys monitor  │                              │
│                  │ Popen(ffmpeg)  │  ──────────────► mic.opus    │
│                  │   mic source   │                              │
│                  │                │                              │
│                  │ stop_segment() │                              │
│                  │   → merge:     │  ────► seg{N}_merged.opus    │
│                  │     loudnorm   │     (layout/bitrate stored   │
│                  │     OR join    │      per Segment)            │
│                  │     (L=sys     │                              │
│                  │      R=mic)    │                              │
│                  │                │                              │
│                  │ finalize()     │                              │
│                  │   → concat     │  ────► <subject>_<id>.opus   │
│                  │   homogêneo:   │     (-c copy se layouts      │
│                  │     -c copy    │      batem; reencode se      │
│                  │   heterogêneo: │      diferentes)             │
│                  │     reencode   │                              │
│                  └───────┬────────┘                              │
└──────────────────────────┼───────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│            post_pipeline (ThreadPoolExecutor dedicado)           │
│                                                                  │
│   1. _safe_move(<final>.opus, ~/Notas/...)                       │
│      cross-fs detection → log warning                            │
│   2. mkdir ~/Notas/<YYYY-MM-DD>_<safe_subject>/                  │
│   3. write nota.md (frontmatter + marks + placeholder)           │
│   4. spawn thread: get_transcriber(backend)                      │
│      - whisper: ensure_whisper_installed() (lazy)                │
│      - parakeet: ffmpeg → wav 16kHz                              │
│      - .transcribe() → transcricao.txt + transcricao.srt         │
│      - replace placeholder em nota.md                            │
│      - notify "✓ Nota disponível"                                │
└──────────────────────────────────────────────────────────────────┘
```

## Components

### Backend (Python)
- **`daemon.py`** — asyncio server, UNIX socket comm, tray spawning, auto-detect loop
- **`recorder.py`** — ffmpeg subprocess management, segment splitting (max_segment)
- **`pipeline.py`** — post-recording: transcribe → summarize → tasks (each as run_step)
- **`transcribers/`** — Whisper (faster-whisper), Parakeet ONNX (sherpa-onnx, default), Cohere API
- **`summarizer/`** — Ollama local LLM, Gemini cloud, heuristic fallback
- **`hardware.py`** — RAM/CPU/GPU probe + backend recommendations + preflight check
- **`meeting_name.py`** — regex extraction from window titles
- **`models_registry.py`** — Whisper/Parakeet/Ollama models metadata + ram_required_mb

### Frontend (GTK4 + libadwaita)
Atomic Design hierarchy:
```
gui/
├── atoms/         (5 widgets básicos + 4 progress)
├── molecules/     (Card, EmptyState, InfoDialog, ConfirmDialog)
├── organisms/     (HardwareCard, RecordingCard, MarkdownView)
├── pages/         (Dashboard, Settings, Models, Logs, RecordingDetail)
├── wizards/       (Onboarding 3-step)
└── theme.{css,py} (design tokens centralizados)
```
App entry: `gui/app.py` — RecordoApp (Adw.Application) + RecordoWindow
(Adw.NavigationView root). DashboardPage é a home; sub-pages são empilhadas
via `nav_view.push()` e o usuário retorna com botão back nativo.

### Tray (GTK3 separate process)
Usa XApp (Cinnamon/Mint/MATE/Xfce) ou AyatanaAppIndicator3 (GNOME/Ubuntu).
NÃO é GTK4 porque AppIndicator nunca foi portado. Comunica com daemon via
`client.send_to_daemon()`.

## Data flow durante uma gravação

1. User aperta Super+R → `bin/gravar` → `recordo --toggle`
2. Client conecta socket UNIX → daemon recebe comando 'toggle'
3. Daemon spawna `recorder.py` que executa ffmpeg gravando microfone+sistema
4. Hard cap em 4h ou max_segment (30min default — split automático)
5. User aperta Super+R novamente → daemon para recorder, faz post_pipeline:
   a. Concat segmentos → audio.opus em ~/Notas/<data>_<assunto>/
   b. transcribe (whisper ou parakeet-onnx ou cohere) → transcricao.txt + .srt
   c. summarize via Ollama (think mode toggleável) → summary.md
   d. extract_tasks via LLM → tasks.md
   e. extract_topics → topics.json
   f. embed tudo em nota.md (markdown final com YAML frontmatter)
6. GUI Dashboard exibe nova gravação no card; clique abre RecordingDetail
   com tabs renderizadas em MarkdownView

## Hardware preflight

Antes de carregar modelo Whisper/Parakeet, `pipeline._do_transcribe_step`
chama `hardware.preflight(backend)` que:
1. Probes RAM disponível via psutil
2. Compara com `models_registry.<backend>.ram_required_mb`
3. Retorna `(False, msg)` se insuficiente
4. Caller faz auto-fallback para Whisper-base (mais leve)

## Tests structure

```
tests/
├── test_*.py        (unit tests por módulo)
└── e2e/
    ├── test_smoke_pipeline.py     (pipeline com stub transcriber)
    └── test_hardware_recommend.py (recomendações por hardware)
```

Markers:
- `gui` — requer xvfb (GTK widget tests)
- `e2e` — testes mais lentos (geram audio com ffmpeg)

## Decisões de design

### 1. UNIX socket vs D-Bus

Escolhido **UNIX socket** com JSON-lines. Motivos:

- **Simples**: 1 arquivo de socket + `asyncio.start_unix_server`. Sem bibliotecas D-Bus, sem `org.freedesktop.*` paths
- **Portátil entre toolkits**: applet Cinnamon GJS pode invocar `Gio.Subprocess(["recordo", "--status"])` que fala via socket. Sem precisar binding GJS pra D-Bus
- **Debuggable**: `socat - UNIX-CONNECT:...` testa direto
- **0644 perms + cookie-less**: socket cria-se com `chmod 600` (só user)

Trade-off: não temos signals/broadcast nativos. Mitigado com polling 2s no applet (suficiente pra UI de painel).

### 2. Codec Opus 32k voz

Default `--bitrate 32k --application voip --vbr on`. Compromisso:

- **CPU**: 10× menos que MP3 (libopus é otimizado pra voz)
- **Disco**: ~10MB/hora típico (vs ~60MB MP3 q:a 2)
- **Qualidade**: superior pra voz, equivalente a MP3 96k na percepção
- **Whisper-friendly**: faster-whisper aceita Opus nativo, sem reencode

Pra música: `--bitrate 96k --layout merge` (loudnorm) recomendado.

### 3. Stereo-split (sys=L, mic=R)

`--layout split` opcional. Vantagem: facilita diarização posterior (separa locutores em canais). Whisper consegue identificar quem falou (com sintonia fina).

Default = `merge` (amerge + loudnorm EBU R128) — fica num único stream balanceado. Recomendado pra arquivamento de longo prazo.

### 4. Bootstrap venv via setup.sh, não auto-bootstrap

Versão antiga do script (`ffmpeg-grava-audio.py` monolítico) fazia auto-bootstrap via `os.execv` reentrante. Removido. Razões:

- **Surpresa baixa**: `setup.sh` é único ponto de install, claro
- **Sem re-exec em hotkey path**: latência zero no `gravar`
- **Idempotente**: setup.sh detecta venv existente

### 5. `WantedBy=default.target`

Bug documentado em Cinnamon (e XFCE, MATE, LXDE): `graphical-session.target` tem `RefuseManualStart=yes` e só é ativado por compositores com integração systemd nativa (GNOME, KDE Plasma 5.22+, uwsm). Em Cinnamon o target nunca dispara — unit ficaria enabled mas inactive.

Solução: `WantedBy=default.target` ativa no login do user via systemd-user. Funcional em todos DEs.

Referência: `~/Projetos/dotfiles/setup-terminal.sh` (passo 13, install_vicinae) documenta workaround similar pra Vicinae.

### 6. faster-whisper lazy install

faster-whisper + ctranslate2 + numpy + onnxruntime = ~400MB. Setup.sh default NÃO instala (overkill se user não usa transcrição). Lazy install acontece na 1ª chamada a `transcribe()` — em thread background, sem bloquear o toggle.

`setup.sh --with-transcribe` força install upfront (recomendado se user vai transcrever sempre).

### 7. Auto-detect agressivo (opt-in)

`config.toml` `[auto_detect].enabled = false` por default. Quando ligado:

1. `pactl subscribe` (asyncio subprocess) escuta eventos do PulseAudio em
   tempo real — quando há `Event 'new' on source-output`, dispara
   `asyncio.Event` que o loop de auto-detect aguarda
2. Tick de liveness (`max(poll_interval, min_mic_duration)`) garante que
   o filtro de persistência funciona mesmo sem novos eventos
3. Match `app_name` OU `binary` contra lista permitida (substring, case-insensitive)
4. Bloqueia `deny_apps`
5. Requer mic ativo por ≥8s (filtra picos espúrios)
6. Quiet period 5min pós-stop manual (evita re-trigger)

Subscribe se reinicia automaticamente se `pactl` morrer (ex: PulseAudio
restart). Falha silenciosa se `pactl` não existir — neste cenário, o tick
de liveness preserva o comportamento de polling original.

Guardrails contra falso-positivo são fundamentais — auto-iniciar gravação
não-desejada quebra confiança no sistema.

### 8. Watchdog de silêncio com `parec`

`measure_mic_db()` usa `parec` (cliente nativo PulseAudio, parte de
`pulseaudio-utils`) lendo PCM s16le mono @16kHz por 1 segundo, com cálculo
RMS em Python puro. Decisão:

- **`ffmpeg + volumedetect`** (legacy): abre um segundo stream de captura
  — em hardware limitado pode disparar reconfig do device PulseAudio e
  dropar samples no recorder principal.
- **`parec`** (atual): cliente nativo mais leve, melhor multiplexing pelo
  PulseAudio. Fallback para ffmpeg se `parec` ausente.

Trade-off: depende de `pulseaudio-utils` instalado (já é dep do setup.sh).

### 9. Concat com `-c copy` quando homogêneo

`build_concat_cmd` aceita `reencode: bool` (default `False`). O `Recorder`
detecta heterogeneidade dos segmentos (layout ou bitrate diferentes) e
força reencode quando necessário:

```python
layouts = {s.layout for s in valid_segs}
bitrates = {s.bitrate for s in valid_segs}
heterogeneous = len(layouts) > 1 or len(bitrates) > 1
```

Caso comum (gravação sem trocar layout): `-c copy` — instantâneo,
lossless. Caso edge (user trocou via TUI Rich `s`/`m`): reencode com
libopus.

### 10. TUI Textual conectada ao daemon

`recordo --tui` abre `tui_textual.py` (Textual 8+):

- Auto-spin do daemon via `client.ensure_daemon()` (systemd OR spawn
  detached) se não estiver rodando.
- Painéis reativos: Status, Devices, Recent. Polling 1s do `status` e
  5s do filesystem.
- Modal `MarkDialog` (Esc/Ctrl+S), `HelpScreen` documentando atalhos +
  comportamento de watchdogs e auto-detect.
- Bindings sempre visíveis no Footer; banner `?` no topo.

Modo standalone CLI (`-a`) foi removido em v0.2 — sempre use o
daemon (auto-spawn via `--tui`/`--gui` é transparente).

### 11. GUI calls async

A GUI GTK4 nunca chama `send_to_daemon` síncrono no main loop. Helper
`gui/async_client.py:call_async` roda em `threading.Thread(daemon=True)` e
volta pro main loop com `GLib.idle_add(callback, resp)`. Sem isso, durante
`finalize+concat` longo, a janela travaria por até 60s (timeout do socket).

## Fluxo de uma sessão

1. **t=0**: user pressiona `Super+R` → Cinnamon dispara `~/.local/bin/gravar`
2. `gravar` verifica socket. Se vivo: `recordo --toggle`. Se morto: `systemctl --user start recordo` + polling 5s + `--toggle`
3. `recordo --toggle` conecta socket, envia `{"cmd":"toggle"}\n`
4. Daemon recebe → dispatcha `_cmd_start`:
   - `detect_subject()`: `xdotool getactivewindow getwindowname` → heurísticas Teams/Meet/Zoom/Slack
   - `list_sources()` + `auto_pick()`: escolhe mic + sys (Bluetooth > USB > builtin)
   - `make_session()`: cria dir `~/recordings/<safe>_<sid>/` + `session.json`
   - `Recorder.start_segment()`: spawn 2 ffmpeg paralelos (sys + mic), Opus 32k
5. **t=15min**: watchdog notify "🔴 ainda gravando — 15min"
6. **t=30min**: `Recorder.watchdog_tick()` retorna `cycled` → fecha segmento + abre novo
7. **a qualquer momento**: user `Super+Shift+M` → `marcar` → zenity entry → `recordo --mark "texto"` → Daemon registra `Mark(ts, iso, text)`
8. **t=X**: user `Super+R` de novo → `_cmd_stop`:
   - SIGINT em ambos ffmpeg → wait → merge segmento → concat final
   - `post_pipeline()` (executor): move pra `~/Notas/<date>_<safe>/`, gera `nota.md`
   - Thread async: faster-whisper transcreve → anexa ao `nota.md` → notify "✓ Nota disponível"
9. **Sempre que daemon morrer**: systemd `Restart=on-failure` re-spawn em 3s

## Estrutura de arquivos por sessão

Durante gravação (em `~/recordings/<subject>_<sid>/`):

```
session.json            metadata completo (subject, segments, marks)
seg000_system.opus      captura raw sys (loopback PA monitor)
seg000_mic.opus         captura raw mic
seg000_merged.opus      merge (já com loudnorm OU stereo-split)
seg001_system.opus      (segmento 2 quando max-segment ciclar)
...
_concat_list.txt        lista pro ffmpeg concat
<subject>_<sid>.opus    arquivo final concatenado
<sid>_report.md         relatório com tabela de segmentos
```

Pós-pipeline move pra `~/Notas/<date>_<safe>/`:

```
audio.opus              ← <subject>_<sid>.opus renomeado
<sid>_report.md         report técnico
nota.md                 ← gerado pelo post_pipeline (frontmatter + marks + transcrição)
transcricao.txt         ← gerado pela thread whisper
transcricao.srt         ← legendas
```

Originais em `~/recordings/` permanecem (pra debug/auditoria).
