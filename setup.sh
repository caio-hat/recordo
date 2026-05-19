#!/usr/bin/env bash
# Recordo — setup.sh
# Instalador idempotente. Funciona em Ubuntu/Mint/Debian (apt-based).
#
# Uso:
#   bash setup.sh                 # install completo (recomendado)
#   bash setup.sh --with-transcribe  # já instala faster-whisper (default = lazy)
#   bash setup.sh --no-systemd    # pula systemd user unit
#   bash setup.sh --no-cinnamon   # pula keybindings Cinnamon
#   bash setup.sh --no-vicinae    # pula integração Vicinae

set -euo pipefail

# ─── Args ────────────────────────────────────────────────────────────────
WITH_TRANSCRIBE=0
NO_SYSTEMD=0
NO_CINNAMON=0
NO_VICINAE=0
for arg in "$@"; do
    case "$arg" in
        --with-transcribe) WITH_TRANSCRIBE=1 ;;
        --no-systemd)      NO_SYSTEMD=1 ;;
        --no-cinnamon)     NO_CINNAMON=1 ;;
        --no-vicinae)      NO_VICINAE=1 ;;
        -h|--help)
            sed -n '2,12p' "$0"
            exit 0 ;;
        *) echo "Arg desconhecido: $arg" >&2; exit 1 ;;
    esac
done

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_PREFIX="${HOME}/.local/share/recordo"
VENV_DIR="$INSTALL_PREFIX/venv"
BIN_DIR="${HOME}/.local/bin"
SYSTEMD_DIR="${HOME}/.config/systemd/user"
CONFIG_DIR="${HOME}/.config/recordo"

echo "════════════════════════════════════════════════"
echo "  Recordo · setup.sh"
echo "  Repo: $REPO_DIR"
echo "  Prefix: $INSTALL_PREFIX"
echo "════════════════════════════════════════════════"

# ─── STEP 1: apt deps ───────────────────────────────────────────────────
echo ""
echo "[1/10] Verificando dependências do sistema..."
NEED=()
for pkg_bin in "ffmpeg:ffmpeg" "pactl:pulseaudio-utils" "notify-send:libnotify-bin" \
                "xdotool:xdotool" "zenity:zenity" "dconf:dconf-cli" \
                "wmctrl:wmctrl" "socat:socat" "jq:jq" "xdg-open:xdg-utils"; do
    bin="${pkg_bin%%:*}"
    pkg="${pkg_bin##*:}"
    if ! command -v "$bin" >/dev/null 2>&1; then
        NEED+=("$pkg")
    fi
done
if ! python3 -c "import venv" 2>/dev/null; then
    NEED+=("python3-venv")
fi
if [[ ${#NEED[@]} -gt 0 ]]; then
    echo "  → faltam: ${NEED[*]}"
    if command -v apt-get >/dev/null; then
        echo "  → sudo apt-get install (pode pedir senha)"
        sudo apt-get update -qq
        sudo apt-get install -y "${NEED[@]}"
    else
        echo "  ERRO: apt-get não disponível e dependências faltando: ${NEED[*]}" >&2
        exit 1
    fi
else
    echo "  ✓ todas as deps OK"
fi

# ─── STEP 2: venv Python ─────────────────────────────────────────────────
echo ""
echo "[2/10] Criando venv em $VENV_DIR..."
mkdir -p "$INSTALL_PREFIX"
if [[ ! -d "$VENV_DIR" ]]; then
    if command -v uv >/dev/null; then
        uv venv "$VENV_DIR" --python 3.12 --seed
    else
        python3 -m venv "$VENV_DIR"
        "$VENV_DIR/bin/python" -m pip install --upgrade pip wheel
    fi
    echo "  ✓ venv criado"
else
    echo "  ✓ venv já existe"
fi

# ─── STEP 3: install pacote recordo ──────────────────────────────────────
echo ""
echo "[3/10] Instalando pacote 'recordo' (editable)..."
if command -v uv >/dev/null; then
    uv pip install --python "$VENV_DIR/bin/python" -e "$REPO_DIR"
else
    "$VENV_DIR/bin/pip" install -e "$REPO_DIR"
fi
RECORDO_BIN="$VENV_DIR/bin/recordo"
[[ -x "$RECORDO_BIN" ]] || { echo "ERRO: $RECORDO_BIN não foi criado pelo pip" >&2; exit 1; }
echo "  ✓ recordo = $RECORDO_BIN"

# faster-whisper opcional
if [[ $WITH_TRANSCRIBE -eq 1 ]]; then
    echo "  → instalando faster-whisper (pode demorar)..."
    if command -v uv >/dev/null; then
        uv pip install --python "$VENV_DIR/bin/python" faster-whisper
    else
        "$VENV_DIR/bin/pip" install faster-whisper
    fi
    echo "  ✓ faster-whisper instalado"
fi

# ─── STEP 4: symlinks bin ────────────────────────────────────────────────
echo ""
echo "[4/10] Symlinks bin → $BIN_DIR..."
mkdir -p "$BIN_DIR"
ln -sfn "$RECORDO_BIN"       "$BIN_DIR/recordo"
ln -sfn "$REPO_DIR/bin/gravar" "$BIN_DIR/gravar"
ln -sfn "$REPO_DIR/bin/marcar" "$BIN_DIR/marcar"
chmod +x "$REPO_DIR/bin/gravar" "$REPO_DIR/bin/marcar"
echo "  ✓ $BIN_DIR/{recordo,gravar,marcar}"

# Detecta se BIN_DIR está no PATH; alerta se não
if ! echo ":$PATH:" | grep -q ":$BIN_DIR:"; then
    echo "  ⚠  ATENÇÃO: $BIN_DIR não está no PATH"
    echo "     Adicione em ~/.bashrc ou ~/.zshrc: export PATH=\"$BIN_DIR:\$PATH\""
fi

# ─── STEP 5: systemd user unit ───────────────────────────────────────────
echo ""
if [[ $NO_SYSTEMD -eq 1 ]]; then
    echo "[5/10] systemd: pulado (--no-systemd)"
else
    echo "[5/10] Configurando systemd user unit..."
    mkdir -p "$SYSTEMD_DIR"
    UNIT_DST="$SYSTEMD_DIR/recordo.service"
    sed "s|__RECORDO_BIN__|$RECORDO_BIN|g" "$REPO_DIR/systemd/recordo.service" > "$UNIT_DST"
    systemctl --user daemon-reload
    systemctl --user enable recordo.service >/dev/null
    if systemctl --user is-active recordo.service >/dev/null 2>&1; then
        echo "  → daemon já ativo, reiniciando..."
        systemctl --user restart recordo.service
    else
        systemctl --user start recordo.service
    fi
    sleep 2
    if systemctl --user is-active recordo.service >/dev/null 2>&1; then
        echo "  ✓ recordo.service ativo (PID=$(systemctl --user show -p MainPID --value recordo.service))"
    else
        echo "  ⚠ recordo.service NÃO ativo — verifique 'systemctl --user status recordo'"
    fi
fi

# ─── STEP 6: Cinnamon keybindings ────────────────────────────────────────
echo ""
if [[ $NO_CINNAMON -eq 1 ]]; then
    echo "[6/10] Cinnamon: pulado (--no-cinnamon)"
elif command -v dconf >/dev/null && [[ "${XDG_CURRENT_DESKTOP:-}" == *"Cinnamon"* || -n "${CINNAMON_VERSION:-}" ]]; then
    echo "[6/10] Aplicando keybindings Cinnamon (Super+R, Super+Shift+M)..."
    bash "$REPO_DIR/keybindings/apply-cinnamon.sh" "$BIN_DIR"
else
    echo "[6/10] Cinnamon não detectado — pulando keybindings"
fi

# ─── STEP 7: Vicinae scripts ─────────────────────────────────────────────
echo ""
if [[ $NO_VICINAE -eq 1 ]]; then
    echo "[7/10] Vicinae: pulado (--no-vicinae)"
elif command -v vicinae >/dev/null && [[ -f "$HOME/.config/vicinae/settings.json" ]]; then
    echo "[7/10] Adicionando customDir ao Vicinae..."
    SETTINGS="$HOME/.config/vicinae/settings.json"
    SCRIPTS_DIR="$REPO_DIR/vicinae"
    # Settings é JSONC (aceita comentários //). Usamos sed pra preservá-los.
    if grep -qF "\"$SCRIPTS_DIR\"" "$SETTINGS" 2>/dev/null; then
        echo "  ✓ customDir já registrado"
    elif grep -qE '"customDirs":\s*\[\s*\]' "$SETTINGS"; then
        # Array vazio: insere primeiro elemento
        sed -i "s|\"customDirs\":\s*\[\s*\]|\"customDirs\": [\n               \"$SCRIPTS_DIR\"\n            ]|" "$SETTINGS"
        echo "  ✓ customDir adicionado (array estava vazio): $SCRIPTS_DIR"
    elif grep -q '"customDirs":' "$SETTINGS"; then
        # Array com itens: insere após "customDirs": [
        sed -i "/\"customDirs\":\s*\[/a\\               \"$SCRIPTS_DIR\"," "$SETTINGS"
        echo "  ✓ customDir adicionado: $SCRIPTS_DIR"
    else
        echo "  ⚠ chave 'customDirs' não encontrada — adicione manualmente:"
        echo "     $SCRIPTS_DIR"
    fi
    if pgrep -x vicinae >/dev/null; then
        vicinae server --replace >/dev/null 2>&1 &
        disown
        echo "  → vicinae server recarregado"
    fi
else
    echo "[7/10] Vicinae não detectado — pulando"
fi

# ─── STEP 8: config dir ──────────────────────────────────────────────────
echo ""
echo "[8/10] Config dir + auto-detect.json..."
mkdir -p "$CONFIG_DIR"
if [[ ! -f "$CONFIG_DIR/auto-detect.json" ]]; then
    cp "$REPO_DIR/config/auto-detect.json.example" "$CONFIG_DIR/auto-detect.json"
    echo "  ✓ $CONFIG_DIR/auto-detect.json criado (enabled=false)"
else
    echo "  ✓ $CONFIG_DIR/auto-detect.json já existe — preservado"
fi

# ─── STEP 9: doctor ──────────────────────────────────────────────────────
echo ""
echo "[9/10] Diagnóstico (doctor.sh)..."
bash "$REPO_DIR/doctor.sh" || true

# ─── STEP 10: resumo ─────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════"
echo "  ✓ Recordo instalado"
echo "════════════════════════════════════════════════"
echo ""
echo "Use:"
echo "  Super+R           → toggle gravação (após relogin/cinnamon --replace)"
echo "  Super+Shift+M     → marcar momento"
echo "  recordo --status  → status do daemon"
echo "  recordo --help    → ajuda completa"
echo ""
echo "Logs: /tmp/recordo.log  +  journalctl --user -u recordo"
