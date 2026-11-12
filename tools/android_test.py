"""Test Guest TV's Android TV app (tv-apps/android) with no TV.

    .venv/bin/python tools/android_test.py

1. The search code's own tests (FinderTest.kt) on this computer: typed addresses, the /api/health
   answer, the /24 list, a scan of a whole /24 inside its time budget, and real probes against small
   web servers on 127.0.0.1 (guest-tv is found, a look-alike is not).
2. If build/guest-tv.apk exists (tv-apps/android/build.sh makes it), what Android will see in it: its
   id, label, TV launcher entry, minimum Android, the Home button watch, and that it is signed with
   the key in ~/.android/debug.keystore. Nothing is installed anywhere.

Needs the Android SDK (ANDROID_HOME, else ~/Library/Android/sdk) and Java 17 or 21.
"""
import glob, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
APP = os.path.join(ROOT, "tv-apps", "android")
APK = os.path.join(ROOT, "build", "guest-tv.apk")
SDK = os.environ.get("ANDROID_HOME") or os.path.expanduser("~/Library/Android/sdk")
passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print("ok   ", name)
    else:
        failed += 1
        print("FAIL ", name, detail)


def java_env():
    env = dict(os.environ)
    if not env.get("JAVA_HOME") and os.path.exists("/usr/libexec/java_home"):
        for v in ("21", "17"):
            r = subprocess.run(["/usr/libexec/java_home", "-v", v], capture_output=True, text=True)
            if r.returncode == 0:
                env["JAVA_HOME"] = r.stdout.strip()
                break
    return env


def tool(name):
    found = sorted(glob.glob(os.path.join(SDK, "build-tools", "*", name)))
    return found[-1] if found else None


# 1. the search code's tests
lp = os.path.join(APP, "local.properties")
if not os.path.exists(lp):
    with open(lp, "w") as f:
        f.write("sdk.dir=%s\n" % SDK)
r = subprocess.run(["./gradlew", "--quiet", "testReleaseUnitTest"], cwd=APP, env=java_env(), capture_output=True, text=True)
check("FinderTest.kt passes", r.returncode == 0, (r.stdout + r.stderr)[-2000:])
for xml in glob.glob(os.path.join(APP, "app", "build", "test-results", "testReleaseUnitTest", "*.xml")):
    m = re.search(r'tests="(\d+)" skipped="\d+" failures="(\d+)" errors="(\d+)"', open(xml).read())
    if m:
        check("%s tests ran, none failed" % m.group(1), int(m.group(1)) >= 6 and m.group(2) == "0" and m.group(3) == "0")

# 2. the built app
if not os.path.exists(APK):
    print("\n(no build/guest-tv.apk yet: run tv-apps/android/build.sh to check the app itself)")
else:
    aapt = tool("aapt")
    badging = subprocess.run([aapt, "dump", "badging", APK], capture_output=True, text=True).stdout if aapt else ""
    check("package app.guesttv.home", "package: name='app.guesttv.home'" in badging)
    check("label Guest TV", "application-label:'Guest TV'" in badging)
    check("a TV launcher entry (Google TV, Android TV, Fire TV)", "leanback-launchable-activity" in badging)
    check("runs on Android 6 and newer (so Fire OS 6)", "sdkVersion:'23'" in badging)
    xml = subprocess.run([aapt, "dump", "xmltree", APK, "AndroidManifest.xml"], capture_output=True, text=True).stdout if aapt else ""
    check("Home button watch is an accessibility service", "BIND_ACCESSIBILITY_SERVICE" in xml and "FireWatch" in xml)
    check("can be the home screen (HOME category)", "android.intent.category.HOME" in xml)
    signer = tool("apksigner")
    certs = subprocess.run([signer, "verify", "--print-certs", APK], capture_output=True, text=True, env=java_env()).stdout if signer else ""
    apk_sha = re.search(r"certificate SHA-256 digest: ([0-9a-f]+)", certs)
    ks = os.path.expanduser("~/.android/debug.keystore")
    keytool = os.path.join(java_env().get("JAVA_HOME", ""), "bin", "keytool")
    if not os.path.exists(keytool):
        keytool = "keytool"
    out = subprocess.run([keytool, "-list", "-v", "-keystore", ks, "-storepass", "android", "-alias", "androiddebugkey"],
                         capture_output=True, text=True).stdout if os.path.exists(ks) else ""
    ks_sha = re.search(r"SHA256: ([0-9A-F:]+)", out)
    check("signed with the key in ~/.android/debug.keystore",
          bool(apk_sha and ks_sha) and apk_sha.group(1) == ks_sha.group(1).replace(":", "").lower(),
          "(apk %s, keystore %s)" % (apk_sha and apk_sha.group(1), ks_sha and ks_sha.group(1)))

print("\n%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
