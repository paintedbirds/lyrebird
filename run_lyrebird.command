#!/bin/zsh
# Lanza Lyrebird directo (sin pasar por LaunchServices / bundle trampoline).
# Esto evita un bug confirmado de macOS 26 (FB21015611) que rompe el
# NSStatusItem cuando el proceso se abre vía Finder/LaunchServices y luego
# hace exec() a otro binario. Lanzado directo desde una shell, no pasa.
cd "$(dirname "$0")"
rm -f /tmp/lyrebird.pid
nohup .venv/bin/python app.py >/tmp/lyrebird.log 2>&1 &
disown
sleep 1
exit 0
