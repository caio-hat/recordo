#!/usr/bin/env bash
# Recordo — uninstall.sh
# Reverte tudo que setup.sh fez. Preserva ~/Notas e ~/.config/recordo (user data).
#
# Uso: bash uninstall.sh [--purge]
#   --purge: apaga também ~/.config/recordo e venv (~/.local/share/recordo)

set -euo pipefail

PURGE=0
[[ "${1:-}" == "--purge" ]] && PURGE=1

INSTALL_PREFIX="${HOME}/.local/share/recordo"
BIN_DIR="${HOME}/.local/bin"
SYSTEMD_DIR="${HOME}/.config/systemd/user"
CONFIG_DIR="${HOME}/.config/recordo"

echo "═══ Desinstalando Recordo ═══"

# 1. systemd
if systemctl --user is-active recordo.service >/dev/null 2>&1; then
    echo "→ stop systemd unit"
    systemctl --user stop recordo.service || true
fi
if systemctl --user is-enabled recordo.service >/dev/null 2>&1; then
    echo "→ disable systemd unit"
    systemctl --user disable recordo.service || true
fi
rm -f "$SYSTEMD_DIR/recordo.service"
rm -f "$SYSTEMD_DIR/default.target.wants/recordo.service"
systemctl --user daemon-reload || true

# 2. socket + locks
rm -f "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/recordo.sock"
rm -f /tmp/recordo.lock /tmp/recordo.notif_id

# 3. bin symlinks
for b in recordo gravar marcar; do
    [[ -L "$BIN_DIR/$b" ]] && rm -f "$BIN_DIR/$b"
done

# 4. Cinnamon keybindings (remove só os com command apontando pra recordo)
if command -v dconf >/dev/null; then
    LIST_KEY="/org/cinnamon/desktop/keybindings/custom-list"
    KEYS_BASE="/org/cinnamon/desktop/keybindings/custom-keybindings"
    current=$(dconf read "$LIST_KEY" 2>/dev/null || echo "[]")
    to_remove=()
    for slot in $(echo "$current" | grep -oE "custom[0-9]+"); do
        cmd=$(dconf read "$KEYS_BASE/$slot/command" 2>/dev/null || echo "")
        if echo "$cmd" | grep -qE "(gravar|marcar)('|$|/)"; then
            echo "→ reset keybinding $slot ($cmd)"
            dconf reset -f "$KEYS_BASE/$slot/" || true
            to_remove+=("$slot")
        fi
    done
    if [[ ${#to_remove[@]} -gt 0 ]]; then
        new=$(echo "$current" | python3 -c "
import sys, ast
removed = sys.argv[1:]
lst = ast.literal_eval(sys.stdin.read().strip() or '[]')
lst = [s for s in lst if s not in removed]
print(repr(lst).replace('\"', \"'\"))
" "${to_remove[@]}")
        dconf write "$LIST_KEY" "$new"
    fi
fi

# 5. Vicinae customDirs (remove só nosso path)
if [[ -f "$HOME/.config/vicinae/settings.json" ]]; then
    REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    python3 - "$HOME/.config/vicinae/settings.json" "$REPO_DIR/vicinae" <<'PYEOF' || true
import json, sys
p, scripts_dir = sys.argv[1], sys.argv[2]
data = json.loads(open(p).read())
try:
    dirs = data["providers"]["scripts"]["preferences"]["customDirs"]
    if scripts_dir in dirs:
        dirs.remove(scripts_dir)
        with open(p, "w") as f:
            json.dump(data, f, indent=3, ensure_ascii=False)
        print(f"→ vicinae customDir removido: {scripts_dir}")
except Exception:
    pass
PYEOF
fi

# 6. purge opcional
if [[ $PURGE -eq 1 ]]; then
    echo "→ --purge: removendo $INSTALL_PREFIX (venv) e $CONFIG_DIR"
    rm -rf "$INSTALL_PREFIX"
    rm -rf "$CONFIG_DIR"
fi

echo ""
echo "✓ Recordo desinstalado"
echo "  Preservado: ~/Notas (gravações), /tmp/recordo*.log"
[[ $PURGE -eq 0 ]] && echo "  Preservado: $INSTALL_PREFIX (venv) + $CONFIG_DIR (config user) — use --purge pra apagar"
