#!/usr/bin/env bash
# Recordo — doctor.sh
# Diagnóstico read-only. Sai 0 se OK, 1 se algum check falha.

set -u
EXIT=0
ok()   { echo "  ✓ $*"; }
warn() { echo "  ⚠ $*"; EXIT=1; }
err()  { echo "  ✗ $*"; EXIT=1; }
sec()  { echo ""; echo "── $1"; }

VENV="$HOME/.local/share/recordo/venv"
BIN="$HOME/.local/bin"
SOCK="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/recordo.sock"

sec "Binários do sistema"
for b in ffmpeg pactl notify-send xdotool zenity dconf socat jq xdg-open systemctl; do
    if command -v "$b" >/dev/null; then ok "$b ($(command -v "$b"))"; else err "$b ausente"; fi
done

sec "Python venv"
if [[ -x "$VENV/bin/python" ]]; then
    PYVER=$("$VENV/bin/python" --version 2>&1)
    ok "$VENV → $PYVER"
    if "$VENV/bin/python" -c "import recordo; print('recordo', recordo.__version__)" 2>/dev/null; then
        ok "$($VENV/bin/python -c 'import recordo; print("recordo", recordo.__version__)')"
    else
        err "pacote 'recordo' não importável no venv"
    fi
    if "$VENV/bin/python" -c "import faster_whisper" 2>/dev/null; then
        ok "faster-whisper $($VENV/bin/python -c 'import faster_whisper; print(faster_whisper.__version__)')"
    else
        warn "faster-whisper não instalado (lazy install na 1ª transcrição)"
    fi
else
    err "venv ausente em $VENV — rode setup.sh"
fi

sec "Entry points"
for b in recordo gravar marcar; do
    if [[ -L "$BIN/$b" ]]; then ok "$BIN/$b → $(readlink "$BIN/$b")"
    elif [[ -x "$BIN/$b" ]]; then ok "$BIN/$b (não symlink)"
    else err "$BIN/$b ausente"; fi
done

sec "systemd"
if systemctl --user list-unit-files recordo.service 2>/dev/null | grep -q recordo; then
    ENA=$(systemctl --user is-enabled recordo.service 2>/dev/null || echo "?")
    ACT=$(systemctl --user is-active  recordo.service 2>/dev/null || echo "?")
    if [[ "$ACT" == "active" ]]; then ok "recordo.service: active+$ENA"
    else warn "recordo.service: $ACT+$ENA"; fi
else
    err "recordo.service não instalado"
fi

sec "Socket / daemon"
if [[ -S "$SOCK" ]]; then
    ok "$SOCK existe"
    if command -v "$BIN/recordo" >/dev/null; then
        RESP=$("$BIN/recordo" --status 2>/dev/null || echo "")
        if echo "$RESP" | grep -q '"ok": true'; then ok "daemon responde --status"
        else err "daemon não respondeu --status corretamente"; fi
    fi
else
    err "socket ausente — daemon não rodando?"
fi

sec "Cinnamon keybindings"
if command -v dconf >/dev/null; then
    LIST=$(dconf read /org/cinnamon/desktop/keybindings/custom-list 2>/dev/null || echo "")
    HIT=0
    for slot in $(echo "$LIST" | grep -oE "custom[0-9]+"); do
        cmd=$(dconf read "/org/cinnamon/desktop/keybindings/custom-keybindings/$slot/command" 2>/dev/null || echo "")
        bind=$(dconf read "/org/cinnamon/desktop/keybindings/custom-keybindings/$slot/binding" 2>/dev/null || echo "")
        if echo "$cmd" | grep -qE "/(gravar|marcar)'?\$"; then
            ok "$slot: $bind → $cmd"
            HIT=$((HIT+1))
        fi
    done
    [[ $HIT -lt 2 ]] && warn "menos de 2 keybindings Recordo encontradas (esperado: Super+R + Super+Shift+M)"
fi

sec "Config"
if [[ -f "$HOME/.config/recordo/auto-detect.json" ]]; then
    ENA=$(jq -r '.enabled' "$HOME/.config/recordo/auto-detect.json" 2>/dev/null)
    ok "auto-detect.json (enabled=$ENA)"
else
    warn "~/.config/recordo/auto-detect.json ausente"
fi

sec "Notas dir"
if [[ -d "$HOME/Notas" ]]; then
    COUNT=$(find "$HOME/Notas" -maxdepth 1 -type d -name "2*" 2>/dev/null | wc -l)
    ok "$HOME/Notas existe ($COUNT gravações)"
else
    warn "$HOME/Notas ausente (será criado na 1ª gravação)"
fi

echo ""
if [[ $EXIT -eq 0 ]]; then echo "✓ Tudo OK"
else echo "⚠ Há alertas/erros acima"; fi
exit $EXIT
