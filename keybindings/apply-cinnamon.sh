#!/usr/bin/env bash
# Aplica keybindings Cinnamon Super+R e Super+Shift+M idempotentemente.
# Detecta slots livres (custom0..customN), evita colisão com bindings existentes.

set -euo pipefail

BIN_DIR="${1:-$HOME/.local/bin}"
FORCE="${2:-}"  # passe "--force" pra sobrescrever colisões

LIST_KEY="/org/cinnamon/desktop/keybindings/custom-list"
KEYS_BASE="/org/cinnamon/desktop/keybindings/custom-keybindings"

if ! command -v dconf >/dev/null; then
    echo "ERROR: dconf não instalado (apt: dconf-cli)" >&2
    exit 1
fi

current_list=$(dconf read "$LIST_KEY" 2>/dev/null || echo "[]")
if [[ "$current_list" == "" || "$current_list" == "@as []" ]]; then
    current_list="[]"
fi

# Coleta slots já em uso
existing_slots=()
while read -r slot; do
    [[ -n "$slot" ]] && existing_slots+=("$slot")
done < <(echo "$current_list" | grep -oE "custom[0-9]+" | sort -u)

# Verifica colisão de binding (Super+R já mapeado?)
check_collision() {
    local binding="$1"
    for slot in "${existing_slots[@]}"; do
        b=$(dconf read "$KEYS_BASE/$slot/binding" 2>/dev/null || echo "")
        if echo "$b" | grep -qF "$binding"; then
            cmd=$(dconf read "$KEYS_BASE/$slot/command" 2>/dev/null || echo "")
            echo "$slot|$cmd"
            return 0
        fi
    done
    return 1
}

find_free_slot() {
    for i in $(seq 0 30); do
        local slot="custom$i"
        local found=0
        for e in "${existing_slots[@]}"; do
            [[ "$e" == "$slot" ]] && { found=1; break; }
        done
        if [[ $found -eq 0 ]]; then
            echo "$slot"
            return 0
        fi
    done
    echo "ERROR: sem slot custom<N> livre" >&2
    exit 1
}

apply_binding() {
    local label="$1"
    local key="$2"
    local cmd="$3"
    local name="$4"

    if collision=$(check_collision "$key"); then
        collide_slot="${collision%%|*}"
        collide_cmd="${collision##*|}"
        if [[ "$collide_cmd" == *"$BIN_DIR/$cmd"* ]]; then
            echo "  ⏭  $label já configurado em $collide_slot — skip"
            return
        fi
        if [[ "$FORCE" != "--force" ]]; then
            echo "  ⚠  $key já mapeado em $collide_slot → $collide_cmd"
            echo "     Para sobrescrever: $0 $BIN_DIR --force"
            return
        fi
        slot=$collide_slot
    else
        slot=$(find_free_slot)
        existing_slots+=("$slot")
    fi

    dconf write "$KEYS_BASE/$slot/name"    "'$name'"
    dconf write "$KEYS_BASE/$slot/command" "'$BIN_DIR/$cmd'"
    dconf write "$KEYS_BASE/$slot/binding" "['$key']"
    echo "  ✓ $label em $slot ($key → $BIN_DIR/$cmd)"
}

echo "=== Aplicando keybindings Recordo (BIN_DIR=$BIN_DIR) ==="
apply_binding "Toggle"      "<Super>r"        "gravar" "Recordo · toggle gravação"
apply_binding "Marcar"      "<Super><Shift>m" "marcar" "Recordo · marcar momento"

# Atualiza custom-list incluindo todos slots usados
new_list="["
first=1
for s in "${existing_slots[@]}"; do
    [[ $first -eq 0 ]] && new_list+=", "
    new_list+="'$s'"
    first=0
done
# preserva __dummy__ no fim (convenção Cinnamon)
[[ "$current_list" == *"__dummy__"* ]] && new_list+=", '__dummy__'"
new_list+="]"
dconf write "$LIST_KEY" "$new_list"

echo ""
echo "Lista final: $(dconf read "$LIST_KEY")"
echo "✓ Keybindings aplicadas. Logout/login ou 'cinnamon --replace &' pra ativar."
