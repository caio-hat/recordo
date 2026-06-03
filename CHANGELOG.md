# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/).

## [0.2.4] - 2026-06-02

### BREAKING
- Sidebar de 5 abas removida em favor de Adw.NavigationView com Dashboard
  como tela principal. Sub-pages Settings/Models/Logs são empurradas via push().
- Backend Parakeet default mudou de NeMo para sherpa-onnx (ONNX). NeMo
  permanece disponível via `engine='nemo'` em config.
- Licença alterada de MIT para GPL-3.0-only.

### Adicionado
- `recordo.hardware`: probe de RAM/CPU/GPU + `recommend_backends` + `preflight`
  bloqueia transcribe se RAM insuficiente, com auto-fallback para Whisper.
- `recordo.transcribers.parakeet_onnx`: backend leve via sherpa-onnx (~2GB RAM).
- `recordo.markdown_render`: pipeline MD→HTML com markdown-it-py + Pygments.
- `recordo.meeting_name`: regex patterns para Teams/Zoom/Meet/Webex/Discord/
  Slack/Skype/Jitsi extraírem nome da reunião do título da janela.
- 7 advanced settings Ollama: think_enabled, temperature, top_p, top_k,
  num_ctx, repeat_penalty, seed.
- Onboarding wizard 3-step (escolha backend, preflight hardware, atalhos).
- Atomic Design layers: `gui/atoms/`, `gui/molecules/`, `gui/organisms/`,
  `gui/pages/`, `gui/wizards/`.
- Markdown viewer integrado: tabs Nota/Transcrição/Resumo/Tarefas/Tópicos
  renderizadas inline com WebKit (substitui necessidade de abrir pasta no Files).
- HardwareCard live no Dashboard mostrando recursos detectados.
- LICENSE GPL-3.0-only + AUTHORS.md + SPDX headers.

### Mudado
- Default `transcriber.parakeet.engine = 'onnx'` (anterior: NeMo via use_onnx flag).
- `pipeline._do_transcribe_step` agora consulta `hardware.preflight` antes de
  carregar modelo; se falhar, tenta Whisper-base como fallback automaticamente.
- `daemon.tray` ganha `_query_state()` testavel + ícone state-aware durante
  recording (vermelho).
- Models registry: campo `ram_required_mb` em todas entries; nova função
  `viable_models(report)` filtra por hardware disponível.

### Corrigido (herança v0.2.1–0.2.3)
- UnicodeDecodeError ASCII em ambientes systemd com locale C/POSIX.
- daemon._cmd_reload_config deep diff (era apenas 4 campos).
- ensure_daemon retornava sucesso silencioso em systemctl falho.
- Modelo Whisper custom HF não encontrado: mensagem amigável.

## [0.2.3] - 2026-06-02

### Corrigido
- Parakeet OOM em áudio longo (chunking inicial; substituído por ONNX em 0.2.4).
- Backend card stale após reload_config.
- LC_ALL=C.UTF-8 forçado no env do package + systemd unit.

## [0.2.2] - 2026-06-02

### Corrigido
- Download de modelo falha sem log/feedback.
- Restart daemon via GUI falha silenciosamente.
- Aviso 'modelo não baixado' não atualizava ao trocar dropdown.
- 'Salvar & recarregar' retornava 'nada mudou' indevidamente.

## [0.2.0]

Phase II features: pipeline opt-in, Models Manager, multi-signal meeting
detection, audio player + waveform, live log viewer.
