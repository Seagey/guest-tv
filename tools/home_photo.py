#!/usr/bin/env python3
"""Use your own photo of your home on the TV and the phone pages.

    .venv/bin/python tools/home_photo.py <home-id> <photo.jpg>                 the main photo
    .venv/bin/python tools/home_photo.py <home-id> <photo.jpg> --inside        the photo beside the house guide
    .venv/bin/python tools/home_photo.py <home-id> <photo.jpg> --area          the photo on "Around here"

Any JPG, PNG or HEIC-converted photo works. A landscape photo (wider than tall) looks best: it is cut
to 16:9 from the middle and sized to 1920x1080. The main photo also gets a frosted copy for the glass
clock. The demo homes also have a cut-out that puts the clock behind the scenery; your own photo does
not need one, the clock simply sits on top.

The files go in web/homes/ and the home's home.json is pointed at them. Run it again to change photo.
"""
import json, os, sys

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W, H = 1920, 1080


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 2:
        sys.exit(__doc__)
    hid, src = args
    which = "inside" if "--inside" in sys.argv else "area" if "--area" in sys.argv else "hero"
    hp = os.path.join(HERE, "data", "homes", hid, "home.json")
    if not os.path.isfile(hp):
        sys.exit("No home called %s. Homes: %s" % (hid, ", ".join(sorted(os.listdir(os.path.join(HERE, "data", "homes"))))))
    img = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    if img.width < img.height:
        print("This photo is portrait (taller than wide). It will be cut to a wide strip from the middle.")
    img = ImageOps.fit(img, (W, H), Image.LANCZOS)
    name = "%s-own-%s" % (hid, which)
    out = os.path.join(HERE, "web", "homes", name)
    img.save(out + ".jpg", quality=86, optimize=True, progressive=True)
    glass = ImageEnhance.Brightness(img.filter(ImageFilter.GaussianBlur(16))).enhance(1.3)
    ImageEnhance.Color(glass).enhance(1.25).save(out + "-glass.jpg", quality=80)
    with open(hp) as f:
        home = json.load(f)
    home.setdefault("photos", {})[which] = name
    tmp = hp + ".tmp"
    with open(tmp, "w") as f:
        json.dump(home, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, hp)
    print("Done: web/homes/%s.jpg is now the %s photo for %s. Reload the TV page to see it." % (name, which, home.get("name", hid)))


if __name__ == "__main__":
    main()
