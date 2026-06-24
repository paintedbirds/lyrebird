#!/bin/zsh
# Start Lyrebird, replacing any running/stuck instance (single instance).
DIR="$(cd "$(dirname "$0")" && pwd)"
pkill -f "$DIR/app.py" 2>/dev/null
sleep 0.4
nohup "$DIR/.venv/bin/python" "$DIR/app.py" >/tmp/lyrebird.log 2>&1 &
echo "Lyrebird started (pid $!). Quit from the menu bar or: pkill -f $DIR/app.py"
