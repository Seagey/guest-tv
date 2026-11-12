#!/bin/sh
# guest-tv, the quick way: one command on the computer that stays on (a Mac, a Linux box or a
# Raspberry Pi). It makes the Python environment, asks the setup questions, and keeps guest-tv
# running after a restart if you say yes. Nothing on the TV is touched here.
#
#   git clone https://github.com/Seagey/guest-tv && cd guest-tv && sh scripts/start.sh
#
# Run it again any time: it skips what is already done and lets you change your answers.
set -e
cd "$(dirname "$0")/.."
DIR=$(pwd)

PY=""
for p in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$p" > /dev/null 2>&1 && "$p" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2> /dev/null; then
    PY=$p; break
  fi
done
if [ -z "$PY" ]; then
  echo "guest-tv needs Python 3.10 or newer."
  echo "  Mac:   brew install python@3.11   (or the installer from python.org)"
  echo "  Linux: sudo apt install python3.11 python3.11-venv"
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "1/3  Making the Python environment (a minute)"
  "$PY" -m venv .venv
fi
.venv/bin/pip install -q --disable-pip-version-check -r requirements.txt
echo "     Python packages ready"

echo "2/3  The setup questions"
.venv/bin/python setup.py

echo
echo "3/3  Keep it running"
printf "Start guest-tv now and again after every restart of this computer? (Y/n) "
read -r ans || ans=""
case "$ans" in
  n*|N*)
    echo "Starting it in this window. Leave the window open (Ctrl+C stops it)."
    exec .venv/bin/python server.py ;;
esac
if [ "$(uname)" = Darwin ]; then
  mkdir -p "$HOME/Library/LaunchAgents"
  PLIST="$HOME/Library/LaunchAgents/guest-tv.plist"
  sed "s|FOLDER|$DIR|g" service/guest-tv.plist > "$PLIST"
  launchctl bootout "gui/$(id -u)/guest-tv" 2> /dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
  echo "guest-tv is running, and starts again after a restart (undo: launchctl bootout gui/$(id -u)/guest-tv)."
  echo "Keep this Mac awake: System Settings, Energy (or Battery, Options), Prevent automatic sleeping."
else
  sed -e "s|FOLDER|$DIR|g" -e "s|USER|$(id -un)|g" service/guest-tv.service > /tmp/guest-tv.service.$$
  sudo cp /tmp/guest-tv.service.$$ /etc/systemd/system/guest-tv.service
  rm -f /tmp/guest-tv.service.$$
  sudo systemctl daemon-reload
  sudo systemctl enable --now guest-tv
  echo "guest-tv is running, and starts again after a restart (undo: sudo systemctl disable --now guest-tv)."
fi

ADDR=$(.venv/bin/python -c 'from server import PORT, lan_ip as ip; print("http://%s:%d" % (ip(), PORT))' 2> /dev/null || echo "")
echo
echo "Now the TV. README, 'The quick way', step 2. guest-tv is at: ${ADDR:-this computer, port 5410}"
echo "Check it in a browser on this Wi-Fi: ${ADDR:-http://<this computer>:5410}/tv/"
