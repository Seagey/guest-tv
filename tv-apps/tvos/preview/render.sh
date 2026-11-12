#!/bin/sh
# Draw Guest TV's screen to PNG files on this Mac, from the app's own SwiftUI views, against a house
# computer or the stand-in (preview/standin.py). Needs Xcode (swiftc), not the tvOS Simulator.
#
#   tv-apps/tvos/preview/render.sh <computer address> [out folder] [home ...]
#   .venv/bin/python tv-apps/tvos/preview/standin.py 5419 &
#   tv-apps/tvos/preview/render.sh http://127.0.0.1:5419 build/tvos-preview lake plain
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
APP=$(cd "$HERE/../GuestTV" && pwd)
ROOT=$(cd "$HERE/../../.." && pwd)
OUT=${2:-"$ROOT/build/tvos-preview"}
BIN=${RENDER_BIN:-"$ROOT/build/tvos-render"}
mkdir -p "$(dirname "$BIN")"
xcrun swiftc -parse-as-library -O -target arm64-apple-macos14 -o "$BIN" \
  "$APP/Style.swift" "$APP/Welcome.swift" "$APP/WelcomeView.swift" "$HERE/Render.swift"
URL=$1
shift
[ $# -gt 0 ] && shift
"$BIN" "$APP/Fonts" "$URL" "$OUT" "$@"
