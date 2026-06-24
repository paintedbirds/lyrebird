#!/bin/zsh
# Reconstruye ~/Applications/Lyrebird.app con el launcher actualizado
# (ver build_app.sh). Doble clic para correrlo.
cd "$(dirname "$0")"
zsh build_app.sh
echo
echo "Podés cerrar esta ventana."
sleep 2
