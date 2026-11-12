#!/bin/sh
# Build Guest TV's Android TV app: build/guest-tv.apk at the top of the repo (git ignored).
#
#   tv-apps/android/build.sh                 # the app owners install (looks on port 5410)
#   tv-apps/android/build.sh -Pport=5499     # a test build that looks on another port
#
# Needs the Android SDK (ANDROID_HOME, else ~/Library/Android/sdk) and Java 17 or 21. It is signed
# with Android's debug key in ~/.android/debug.keystore, the same key as couch-tv's releases.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
SDK=${ANDROID_HOME:-$HOME/Library/Android/sdk}
[ -d "$SDK" ] || { echo "No Android SDK at $SDK: set ANDROID_HOME" >&2; exit 1; }
[ -f "$HERE/local.properties" ] || printf 'sdk.dir=%s\n' "$SDK" >"$HERE/local.properties"
if [ -z "$JAVA_HOME" ] && [ -x /usr/libexec/java_home ]; then
  JAVA_HOME=$(/usr/libexec/java_home -v 21 2>/dev/null || /usr/libexec/java_home -v 17 2>/dev/null || true)
  export JAVA_HOME
fi
cd "$HERE"
./gradlew --quiet testReleaseUnitTest assembleRelease "$@"
mkdir -p "$ROOT/build"
cp app/build/outputs/apk/release/app-release.apk "$ROOT/build/guest-tv.apk"
echo "Built $ROOT/build/guest-tv.apk"
