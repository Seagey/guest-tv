"""Make the icons Guest TV carries on the Apple TV (from couch-tv's tvos/make-assets.py).

    python3 tv-apps/tvos/make-assets.py

The outputs are committed (GuestTV/Assets.xcassets), so you only run this to change the look. It needs
ImageMagick (`magick`). The fonts in GuestTV/Fonts are couch-tv's own (Antonio Light and Inter at 400, 500
and 600, made by couch-tv's tvos/make-assets.py from the same files as web/fonts here).

- the app icon on Apple's home row: two layers (a guest-tv home photo behind, the words guest tv in front),
  so tvOS can give it its parallax when it is focused;
- the Top Shelf pictures Apple's home shows above the row when Guest TV is in the top row.
"""
import json
import os
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
APP = os.path.join(HERE, "GuestTV")
CAT = os.path.join(APP, "Assets.xcassets")
PHOTO = os.path.join(ROOT, "web", "homes", "lake-hero.jpg")
FONT = os.path.join(APP, "Fonts", "CouchAntonio-Light.ttf")
INFO = {"author": "xcode", "version": 1}


def run(*cmd):
    subprocess.run(cmd, check=True)


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def back(path, w, h):
    run("magick", PHOTO, "-resize", f"{w}x{h}^", "-gravity", "center", "-extent", f"{w}x{h}",
        "-brightness-contrast", "-18x0", "-sampling-factor", "4:2:0", "-strip", "-quality", "76", path)


def front(path, w, h):
    pt = int(h * 0.34)
    run("magick", "-size", f"{w}x{h}", "xc:none", "-font", FONT, "-pointsize", str(pt), "-fill", "white",
        "-gravity", "center", "-annotate", "+0+0", "guest tv", "(", "+clone", "-background", "black",
        "-shadow", "40x8+0+6", ")", "+swap", "-background", "none", "-layers", "merge", "+repage",
        "-gravity", "center", "-extent", f"{w}x{h}", "-strip", "PNG32:" + path)


def imageset(folder, files):
    """files: [(scale, filename)]"""
    write_json(os.path.join(folder, "Contents.json"), {
        "images": [{"idiom": "tv", "filename": f, "scale": s} for s, f in files], "info": INFO})


def stack(folder, sizes):
    """A two layer icon (Front over Back) at the given [(scale, w, h)]."""
    write_json(os.path.join(folder, "Contents.json"),
               {"layers": [{"filename": "Front.imagestacklayer"}, {"filename": "Back.imagestacklayer"}], "info": INFO})
    for layer, draw in (("Front", front), ("Back", back)):
        ld = os.path.join(folder, f"{layer}.imagestacklayer")
        write_json(os.path.join(ld, "Contents.json"), {"info": INFO})
        cd = os.path.join(ld, "Content.imageset")
        os.makedirs(cd, exist_ok=True)
        files = []
        for scale, w, h in sizes:
            fn = f"{layer.lower()}-{w}x{h}." + ("png" if layer == "Front" else "jpg")
            draw(os.path.join(cd, fn), w, h)
            files.append((scale, fn))
        imageset(cd, files)


def icons():
    brand = os.path.join(CAT, "App Icon & Top Shelf Image.brandassets")
    write_json(os.path.join(CAT, "Contents.json"), {"info": INFO})
    write_json(os.path.join(brand, "Contents.json"), {"assets": [
        {"filename": "App Icon - App Store.imagestack", "idiom": "tv", "role": "primary-app-icon", "size": "1280x768"},
        {"filename": "App Icon.imagestack", "idiom": "tv", "role": "primary-app-icon", "size": "400x240"},
        {"filename": "Top Shelf Image Wide.imageset", "idiom": "tv", "role": "top-shelf-image-wide", "size": "2320x720"},
        {"filename": "Top Shelf Image.imageset", "idiom": "tv", "role": "top-shelf-image", "size": "1920x720"},
    ], "info": INFO})
    stack(os.path.join(brand, "App Icon.imagestack"), [("1x", 400, 240), ("2x", 800, 480)])
    stack(os.path.join(brand, "App Icon - App Store.imagestack"), [("1x", 1280, 768)])
    for folder, w, h in (("Top Shelf Image.imageset", 1920, 720), ("Top Shelf Image Wide.imageset", 2320, 720)):
        d = os.path.join(brand, folder)
        os.makedirs(d, exist_ok=True)
        files = []
        for scale, k in (("1x", 1), ("2x", 2)):
            fn = f"top-shelf-{w * k}x{h * k}.jpg"
            tmp = os.path.join(tempfile.mkdtemp(), "f.png")
            back(os.path.join(d, fn), w * k, h * k)
            front(tmp, w * k, h * k)
            run("magick", os.path.join(d, fn), tmp, "-composite", "-sampling-factor", "4:2:0", "-strip", "-quality", "70", os.path.join(d, fn))
            files.append((scale, fn))
        imageset(d, files)
    write_json(os.path.join(CAT, "AccentColor.colorset", "Contents.json"), {
        "colors": [{"idiom": "universal", "color": {"color-space": "srgb", "components": {
            "red": "1.000", "green": "1.000", "blue": "1.000", "alpha": "1.000"}}}], "info": INFO})


if __name__ == "__main__":
    icons()
    print("done:", subprocess.run(["du", "-sh", CAT], capture_output=True, text=True).stdout.strip())
