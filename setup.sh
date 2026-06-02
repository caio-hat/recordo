#!/usr/bin/env bash
# Recordo — setup.sh
# Instalador idempotente. Funciona em Ubuntu/Mint/Debian (apt-based).
#
# Uso:
#   bash setup.sh                    # install completo (recomendado)
#   bash setup.sh --with-transcribe  # já instala faster-whisper (default = lazy)
#   bash setup.sh --with-parakeet    # instala backend Parakeet (~1.5GB)
#   bash setup.sh --no-systemd       # pula systemd user unit
#   bash setup.sh --no-cinnamon      # pula keybindings Cinnamon
#   bash setup.sh --no-vicinae       # pula integração Vicinae
#   bash setup.sh --no-gui           # pula instalação GUI (deps GTK)

set -euo pipefail

# ─── Args ────────────────────────────────────────────────────────────────
WITH_TRANSCRIBE=0
WITH_PARAKEET=0
NO_SYSTEMD=0
NO_CINNAMON=0
NO_VICINAE=0
NO_GUI=0
WITH_TRAY_AUTOSTART=0
for arg in "$@"; do
    case "$arg" in
        --with-transcribe) WITH_TRANSCRIBE=1 ;;
        --with-parakeet)   WITH_PARAKEET=1 ;;
        --with-tray-autostart) WITH_TRAY_AUTOSTART=1 ;;
        --no-systemd)      NO_SYSTEMD=1 ;;
        --no-cinnamon)     NO_CINNAMON=1 ;;
        --no-vicinae)      NO_VICINAE=1 ;;
        --no-gui)          NO_GUI=1 ;;
        -h|--help)
            sed -n '2,14p' "$0"
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
echo "[1/12] Verificando dependências do sistema..."
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

# GTK4 + libadwaita pra GUI (opcional, mas default ligado)
if [[ $NO_GUI -eq 0 ]]; then
    if ! python3 -c "import gi; gi.require_version('Adw','1')" 2>/dev/null; then
        NEED+=("python3-gi" "gir1.2-gtk-4.0" "gir1.2-adw-1")
    fi
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
echo "[2/12] Criando venv em $VENV_DIR..."
mkdir -p "$INSTALL_PREFIX"
# venv com system-site-packages pra herdar PyGObject (python3-gi via apt)
if [[ ! -d "$VENV_DIR" ]]; then
    if command -v uv >/dev/null; then
        uv venv "$VENV_DIR" --python 3.12 --seed --system-site-packages
    else
        python3 -m venv --system-site-packages "$VENV_DIR"
        "$VENV_DIR/bin/python" -m pip install --upgrade pip wheel
    fi
    echo "  ✓ venv criado (com system-site-packages pra PyGObject)"
else
    echo "  ✓ venv já existe"
    # Auto-repair: venvs antigos podem ter sido criados sem --system-site-packages
    # (ou com versão de uv que ignorou a flag). Sem isso, GUI falha porque
    # python3-gi não fica visível dentro do venv.
    PYVENV_CFG="$VENV_DIR/pyvenv.cfg"
    if [[ -f "$PYVENV_CFG" ]] && grep -q "^include-system-site-packages = false" "$PYVENV_CFG"; then
        sed -i 's/^include-system-site-packages = false/include-system-site-packages = true/' "$PYVENV_CFG"
        echo "  ✓ corrigido pyvenv.cfg (system-site-packages = true)"
    fi
fi

# ─── STEP 3: install pacote recordo ──────────────────────────────────────
echo ""
echo "[3/12] Instalando pacote 'recordo' (editable)..."
if command -v uv >/dev/null; then
    uv pip install --python "$VENV_DIR/bin/python" -e "$REPO_DIR"
else
    "$VENV_DIR/bin/pip" install -e "$REPO_DIR"
fi
RECORDO_BIN="$VENV_DIR/bin/recordo"
[[ -x "$RECORDO_BIN" ]] || { echo "ERRO: $RECORDO_BIN não foi criado pelo pip" >&2; exit 1; }
echo "  ✓ recordo = $RECORDO_BIN"

# faster-whisper opcional (upfront vs lazy)
if [[ $WITH_TRANSCRIBE -eq 1 ]]; then
    echo "  → instalando faster-whisper (pode demorar)..."
    if command -v uv >/dev/null; then
        uv pip install --python "$VENV_DIR/bin/python" faster-whisper
    else
        "$VENV_DIR/bin/pip" install faster-whisper
    fi
    echo "  ✓ faster-whisper instalado"
fi

# Parakeet opt-in (NVIDIA NeMo — pesado!)
if [[ $WITH_PARAKEET -eq 1 ]]; then
    echo "  → instalando nemo_toolkit[asr] (pode demorar muito, ~1.5GB)..."
    if command -v uv >/dev/null; then
        uv pip install --python "$VENV_DIR/bin/python" "nemo_toolkit[asr]" Cython
    else
        "$VENV_DIR/bin/pip" install "nemo_toolkit[asr]" Cython
    fi
    echo "  ✓ Parakeet backend instalado"
    echo "  ⚠ NOTA: modelo treinado em pt-PT (Europeu). Pode errar termos pt-BR."
fi

# ─── STEP 4: symlinks bin ────────────────────────────────────────────────
echo ""
echo "[4/12] Symlinks bin → $BIN_DIR..."
mkdir -p "$BIN_DIR"
ln -sfn "$RECORDO_BIN"            "$BIN_DIR/recordo"
ln -sfn "$REPO_DIR/bin/gravar"    "$BIN_DIR/gravar"
ln -sfn "$REPO_DIR/bin/marcar"    "$BIN_DIR/marcar"
ln -sfn "$REPO_DIR/bin/recordo-gui" "$BIN_DIR/recordo-gui"
ln -sfn "$REPO_DIR/bin/recordo-tray" "$BIN_DIR/recordo-tray"
chmod +x "$REPO_DIR/bin/gravar" "$REPO_DIR/bin/marcar" "$REPO_DIR/bin/recordo-gui" "$REPO_DIR/bin/recordo-tray"
echo "  ✓ $BIN_DIR/{recordo,gravar,marcar,recordo-gui,recordo-tray}"

# Detecta se BIN_DIR está no PATH; alerta se não
if ! echo ":$PATH:" | grep -q ":$BIN_DIR:"; then
    echo "  ⚠  ATENÇÃO: $BIN_DIR não está no PATH"
    echo "     Adicione em ~/.bashrc ou ~/.zshrc: export PATH=\"$BIN_DIR:\$PATH\""
fi

# ─── STEP 5: systemd user unit ───────────────────────────────────────────
echo ""
if [[ $NO_SYSTEMD -eq 1 ]]; then
    echo "[5/12] systemd: pulado (--no-systemd)"
else
    echo "[5/12] Configurando systemd user unit..."
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
    echo "[6/12] Cinnamon: pulado (--no-cinnamon)"
elif command -v dconf >/dev/null && [[ "${XDG_CURRENT_DESKTOP:-}" == *"Cinnamon"* || -n "${CINNAMON_VERSION:-}" ]]; then
    echo "[6/12] Aplicando keybindings Cinnamon (Super+R, Super+Shift+M)..."
    bash "$REPO_DIR/keybindings/apply-cinnamon.sh" "$BIN_DIR"
else
    echo "[6/12] Cinnamon não detectado — pulando keybindings"
fi

# ─── STEP 7: Vicinae scripts ─────────────────────────────────────────────
echo ""
if [[ $NO_VICINAE -eq 1 ]]; then
    echo "[7/12] Vicinae: pulado (--no-vicinae)"
elif command -v vicinae >/dev/null && [[ -f "$HOME/.config/vicinae/settings.json" ]]; then
    echo "[7/12] Adicionando customDir ao Vicinae..."
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
    echo "[7/12] Vicinae não detectado — pulando"
fi

# ─── STEP 8: config TOML ─────────────────────────────────────────────────
echo ""
echo "[8/12] Config TOML em $CONFIG_DIR/config.toml..."
mkdir -p "$CONFIG_DIR"
# load_config() do recordo cria config.toml automaticamente no 1º run.
# Aqui só copiamos exemplo se nem o TOML nem o JSON legacy existem.
if [[ ! -f "$CONFIG_DIR/config.toml" && ! -f "$CONFIG_DIR/auto-detect.json" ]]; then
    cp "$REPO_DIR/config/config.toml.example" "$CONFIG_DIR/config.toml"
    echo "  ✓ $CONFIG_DIR/config.toml criado (com defaults)"
elif [[ -f "$CONFIG_DIR/config.toml" ]]; then
    echo "  ✓ config.toml existe — preservado"
else
    echo "  ✓ auto-detect.json legacy detectado — será migrado no 1º run"
fi

# ─── STEP 9: GUI assets (.desktop + ícones) ──────────────────────────────
echo ""
if [[ $NO_GUI -eq 1 ]]; then
    echo "[9/12] GUI: pulado (--no-gui)"
else
    echo "[9/12] Instalando .desktop + ícones GUI..."
    APPS_DIR="$HOME/.local/share/applications"
    ICONS_DIR="$HOME/.local/share/icons/hicolor"
    mkdir -p "$APPS_DIR" "$ICONS_DIR/scalable/apps" "$ICONS_DIR/symbolic/apps" "$ICONS_DIR/32x32/apps"
    cp "$REPO_DIR/share/applications/recordo.desktop" "$APPS_DIR/recordo.desktop"
    cp "$REPO_DIR/share/icons/hicolor/scalable/apps/recordo.svg" "$ICONS_DIR/scalable/apps/recordo.svg"
    cp "$REPO_DIR/share/icons/hicolor/symbolic/apps/recordo-symbolic.svg" "$ICONS_DIR/symbolic/apps/recordo-symbolic.svg"
    cp "$REPO_DIR/share/icons/hicolor/32x32/apps/recordo.svg" "$ICONS_DIR/32x32/apps/recordo.svg"

    # T0: Tray agora é gerenciado pelo daemon (config.tray.auto_start=true default).
    # Flag legacy --with-tray-autostart ignorada — daemon spawna tray automaticamente.
    if [[ ${WITH_TRAY_AUTOSTART:-0} -eq 1 ]]; then
        echo "  ℹ --with-tray-autostart: ignorado em v0.2 (tray agora é spawnado pelo daemon)"
        echo "    → ajuste config.tray.auto_start em ~/.config/recordo/config.toml se desejar"
    fi
    # Garante que o backend de tray (XApp ou Ayatana) está disponível
    if ! python3 -c "import gi; gi.require_version('XApp', '1.0'); from gi.repository import XApp" 2>/dev/null; then
        if ! python3 -c "import gi; gi.require_version('AyatanaAppIndicator3', '0.1'); from gi.repository import AyatanaAppIndicator3" 2>/dev/null; then
            echo "  ⚠ Nenhum backend de tray detectado — instalando gir1.2-xapp-1.0..."
            sudo apt install -y gir1.2-xapp-1.0 || \
                echo "    ✗ falhou. Tray pode não aparecer. Instale manual:"
            echo "       sudo apt install gir1.2-xapp-1.0  # Cinnamon/Mint"
            echo "       sudo apt install gir1.2-ayatanaappindicator3-0.1  # GNOME/Ubuntu"
        fi
    fi
    if command -v update-desktop-database >/dev/null; then
        update-desktop-database -q "$APPS_DIR" || true
    fi
    if command -v gtk-update-icon-cache >/dev/null; then
        gtk-update-icon-cache -q -t "$ICONS_DIR" || true
    fi
    echo "  ✓ recordo.desktop + ícones instalados (lançável no menu)"
fi

# ─── STEP 10: doctor ─────────────────────────────────────────────────────
echo ""
echo "[10/12] Diagnóstico (doctor.sh)..."
bash "$REPO_DIR/doctor.sh" || true

# ─── STEP 11: reload daemon ──────────────────────────────────────────────
echo ""
if [[ $NO_SYSTEMD -eq 0 ]] && systemctl --user is-active recordo.service >/dev/null 2>&1; then
    echo "[11/12] Recarregando config no daemon..."
    "$RECORDO_BIN" --reload-config 2>/dev/null || true
    echo "  ✓ reload enviado"
else
    echo "[11/12] Daemon não ativo — skip reload"
fi

# ─── STEP 12: resumo ─────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════"
echo "  ✓ Recordo instalado"
echo "════════════════════════════════════════════════"
echo ""
echo "Use:"
echo "  Super+R                → toggle gravação (após relogin/cinnamon --replace)"
echo "  Super+Shift+M          → marcar momento"
echo "  recordo --gui          → janela desktop GTK4"
echo "  recordo-gui            → mesmo, atalho direto"
echo "  recordo --status       → status do daemon"
echo "  recordo --reload-config → recarrega config.toml sem restart"
echo "  recordo --help         → ajuda completa"
echo ""
echo "Config:  ~/.config/recordo/config.toml"
echo "Logs:    /tmp/recordo.log  +  journalctl --user -u recordo"
