#!/bin/bash
# @vicinae.schemaVersion 1
# @vicinae.title 📂 Abrir Última Gravação
# @vicinae.description Abre a nota mais recente em ~/Notas (Recordo)
# @vicinae.mode silent
# @vicinae.exec ["/bin/bash"]

NOTAS_DIR="$HOME/Notas"
LAST=$(find "$NOTAS_DIR" -maxdepth 1 -type d -name "2*" -printf "%T@ %p\n" 2>/dev/null \
        | sort -nr | head -1 | cut -d' ' -f2-)

if [[ -z "$LAST" ]]; then
    notify-send -a Recordo "Recordo" "Nenhuma nota encontrada."
    exit 1
fi

xdg-open "$LAST/nota.md" 2>/dev/null || xdg-open "$LAST"
