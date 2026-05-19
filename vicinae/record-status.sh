#!/bin/bash
# @vicinae.schemaVersion 1
# @vicinae.title 📊 Status da Gravação
# @vicinae.description Mostra se há gravação em curso e por quanto tempo
# @vicinae.mode fullOutput
# @vicinae.exec ["/bin/bash"]

SOCK="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/recordo.sock"

if [[ ! -S "$SOCK" ]]; then
    echo "⚫ Daemon offline"
    echo ""
    echo "Inicie com: systemctl --user start recordo"
    exit 0
fi

STATUS=$(recordo --status 2>/dev/null)
if echo "$STATUS" | grep -q '"recording": true'; then
    ELAPSED=$(echo "$STATUS" | grep -oP '"elapsed_seconds":\s*\K\d+')
    SUBJECT=$(echo "$STATUS" | grep -oP '"subject":\s*"\K[^"]+')
    SEGS=$(echo "$STATUS" | grep -oP '"segments":\s*\K\d+')
    MARKS=$(echo "$STATUS" | grep -oP '"marks":\s*\K\d+')
    MIN=$((ELAPSED / 60))
    SEC=$((ELAPSED % 60))
    echo "🔴 GRAVANDO"
    echo ""
    echo "Assunto: $SUBJECT"
    printf "Tempo: %02d:%02d\n" "$MIN" "$SEC"
    echo "Segmentos: $SEGS"
    echo "Marcas: $MARKS"
else
    echo "⚫ Idle (daemon ativo, sem gravação)"
fi
